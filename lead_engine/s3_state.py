"""Durable, checksum-verified SQLite snapshots in S3-compatible object storage.

Designed for Cloudflare R2 or any S3-compatible object store. Each run writes an
immutable generation, verifies the uploaded database objects and manifest, then
atomically publishes a small latest-generation pointer. A failed upload never
replaces the last complete generation.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any

DB_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
RETAIN_GENERATIONS = 2
CHUNK_BYTES = 1024 * 1024


def _config() -> dict[str, str]:
    values = {
        "endpoint_url": os.environ.get("THORIO_STATE_S3_ENDPOINT_URL", "").strip(),
        "bucket": os.environ.get("THORIO_STATE_S3_BUCKET", "").strip(),
        "access_key_id": os.environ.get("THORIO_STATE_S3_ACCESS_KEY_ID", "").strip(),
        "secret_access_key": os.environ.get("THORIO_STATE_S3_SECRET_ACCESS_KEY", "").strip(),
        "region_name": os.environ.get("THORIO_STATE_S3_REGION", "auto").strip() or "auto",
        "prefix": os.environ.get("THORIO_STATE_S3_PREFIX", "thorio/lead-engine").strip().strip("/"),
    }
    missing = [key for key in ("endpoint_url", "bucket", "access_key_id", "secret_access_key") if not values[key]]
    if missing:
        names = {
            "endpoint_url": "THORIO_STATE_S3_ENDPOINT_URL",
            "bucket": "THORIO_STATE_S3_BUCKET",
            "access_key_id": "THORIO_STATE_S3_ACCESS_KEY_ID",
            "secret_access_key": "THORIO_STATE_S3_SECRET_ACCESS_KEY",
        }
        raise RuntimeError("Durable S3 state storage is not configured; missing " + ", ".join(names[key] for key in missing))
    if not values["endpoint_url"].startswith(("https://", "http://")):
        raise RuntimeError("THORIO_STATE_S3_ENDPOINT_URL must be an HTTP(S) S3-compatible endpoint.")
    return values


def _client():
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError("S3 state storage requires boto3; install the project requirements.") from exc
    config = _config()
    return boto3.client(
        "s3",
        endpoint_url=config["endpoint_url"],
        aws_access_key_id=config["access_key_id"],
        aws_secret_access_key=config["secret_access_key"],
        region_name=config["region_name"],
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 4, "mode": "standard"},
            s3={"addressing_style": "path"},
        ),
    )


def _prefix() -> str:
    return _config()["prefix"]


def _sqlite_files(data_dir: Path) -> list[tuple[str, Path]]:
    root = data_dir.resolve()
    files = []
    if not root.exists():
        return []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in DB_SUFFIXES:
            continue
        resolved = path.resolve()
        try:
            name = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise RuntimeError(f"Refusing to snapshot a SQLite database outside the data directory: {path}") from exc
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"Unsafe SQLite database path: {name}")
        files.append((name, path))
    return files


def _backup_compressed(source: Path, compressed_path: Path) -> tuple[str, str, int, int]:
    """Create a consistent SQLite online backup and stream-compress it with hashes."""
    raw_hash = hashlib.sha256()
    compressed_hash = hashlib.sha256()
    raw_bytes = compressed_bytes = 0
    source_uri = f"file:{source.resolve()}?mode=ro"
    backup_path = compressed_path.with_suffix(".sqlite-backup")
    try:
        with sqlite3.connect(source_uri, uri=True, timeout=30) as src:
            src.execute("PRAGMA busy_timeout=30000")
            with sqlite3.connect(backup_path, timeout=30) as dst:
                dst.execute("PRAGMA journal_mode=OFF")
                dst.execute("PRAGMA synchronous=OFF")
                src.backup(dst, pages=512, sleep=0.05)
                dst.commit()
        with backup_path.open("rb") as raw_file, compressed_path.open("wb") as raw_out:
            class HashingWriter:
                def write(self, data: bytes) -> int:
                    nonlocal compressed_bytes
                    compressed_hash.update(data)
                    compressed_bytes += len(data)
                    return raw_out.write(data)
                def flush(self) -> None:
                    raw_out.flush()
            hashing_writer = HashingWriter()
            with gzip.GzipFile(fileobj=hashing_writer, mode="wb", compresslevel=6, mtime=0) as gz:
                while True:
                    block = raw_file.read(CHUNK_BYTES)
                    if not block:
                        break
                    raw_hash.update(block)
                    raw_bytes += len(block)
                    gz.write(block)
        return raw_hash.hexdigest(), compressed_hash.hexdigest(), raw_bytes, compressed_bytes
    finally:
        backup_path.unlink(missing_ok=True)


def _client_error_code(exc: BaseException) -> str:
    response = getattr(exc, "response", {})
    if isinstance(response, dict):
        error = response.get("Error", {})
        if isinstance(error, dict):
            return str(error.get("Code", ""))
    return ""


def _get_json(client: Any, bucket: str, key: str) -> dict[str, Any] | None:
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except Exception as exc:
        if _client_error_code(exc) in {"NoSuchKey", "NotFound", "404"}:
            return None
        raise
    try:
        value = json.loads(response["Body"].read().decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid JSON in durable state object {key}.") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Invalid JSON object in durable state object {key}.")
    return value


def _validate_database(path: Path, *, primary: bool = False) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Durable state database is missing or empty: {path}")
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise RuntimeError(f"SQLite integrity_check failed for {path}: {integrity!r}")
            if primary:
                tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                missing = sorted({"leads", "checkpoints"} - tables)
                if missing:
                    raise RuntimeError(f"Primary Lead Engine database is missing required tables: {missing}")
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(f"Cannot validate durable state database {path}: {exc}") from exc


def _object_key(generation: str, database_name: str) -> str:
    safe_name = PurePosixPath(database_name)
    if safe_name.is_absolute() or ".." in safe_name.parts or not safe_name.parts:
        raise RuntimeError(f"Unsafe database path in durable state manifest: {database_name}")
    return f"{_prefix()}/generations/{generation}/databases/{safe_name.as_posix()}.gz"


def _readback_hash(client: Any, bucket: str, key: str) -> tuple[str, int]:
    response = client.get_object(Bucket=bucket, Key=key)
    digest = hashlib.sha256()
    total = 0
    body = response["Body"]
    try:
        while True:
            block = body.read(CHUNK_BYTES)
            if not block:
                break
            digest.update(block)
            total += len(block)
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()
    return digest.hexdigest(), total


def _prune_old_generations(client: Any, bucket: str, current_generation: str) -> None:
    """Best-effort cleanup only after latest points at a verified generation."""
    try:
        root = f"{_prefix()}/generations/"
        paginator = client.get_paginator("list_objects_v2")
        keys_by_generation: dict[str, list[str]] = {}
        for page in paginator.paginate(Bucket=bucket, Prefix=root):
            for item in page.get("Contents", []):
                key = str(item.get("Key", ""))
                remainder = key[len(root):]
                generation = remainder.split("/", 1)[0]
                if generation:
                    keys_by_generation.setdefault(generation, []).append(key)
        keep = sorted(keys_by_generation, reverse=True)[:RETAIN_GENERATIONS]
        keep_set = set(keep) | {current_generation}
        doomed = [key for generation, keys in keys_by_generation.items() if generation not in keep_set for key in keys]
        for start in range(0, len(doomed), 1000):
            batch = doomed[start:start + 1000]
            if batch:
                client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True})
        print(f"S3 STATE RETENTION: kept={sorted(keep_set)} removed_objects={len(doomed)}.", flush=True)
    except Exception as exc:
        print(f"S3 STATE RETENTION WARNING: old-generation cleanup deferred: {type(exc).__name__}: {exc}", flush=True)


def snapshot(data_dir: Path) -> None:
    """Publish a complete, verified generation without replacing the prior good pointer early."""
    config = _config()
    client = _client()
    bucket = config["bucket"]
    files = _sqlite_files(data_dir)
    by_name = dict(files)
    if "leads.sqlite3" not in by_name:
        raise RuntimeError("Cannot snapshot Thorio state: data/leads.sqlite3 is missing.")
    _validate_database(by_name["leads.sqlite3"], primary=True)

    created_at = datetime.now(timezone.utc).isoformat()
    generation = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
    generation_prefix = f"{config['prefix']}/generations/{generation}"
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "generation": generation,
        "created_at": created_at,
        "databases": [],
    }

    with tempfile.TemporaryDirectory(prefix="thorio-s3-state-") as temp:
        temp_root = Path(temp)
        for name, source in files:
            compressed_path = temp_root / (hashlib.sha256(name.encode()).hexdigest() + ".gz")
            raw_hash, compressed_hash, raw_bytes, compressed_bytes = _backup_compressed(source, compressed_path)
            key = _object_key(generation, name)
            print(f"S3 STATE UPLOAD START: generation={generation} database={name} bytes={compressed_bytes}.", flush=True)
            client.upload_file(
                str(compressed_path),
                bucket,
                key,
                ExtraArgs={"Metadata": {"sha256": compressed_hash, "raw-sha256": raw_hash, "generation": generation}},
            )
            head = client.head_object(Bucket=bucket, Key=key)
            if int(head.get("ContentLength", -1)) != compressed_bytes:
                raise RuntimeError(f"S3 state upload size mismatch for {name}: expected {compressed_bytes}, got {head.get('ContentLength')}.")
            metadata = {str(k).lower(): str(v) for k, v in head.get("Metadata", {}).items()}
            if metadata.get("sha256") != compressed_hash or metadata.get("raw-sha256") != raw_hash:
                raise RuntimeError(f"S3 state upload metadata verification failed for {name}.")
            readback_hash, readback_bytes = _readback_hash(client, bucket, key)
            if readback_hash != compressed_hash or readback_bytes != compressed_bytes:
                raise RuntimeError(f"S3 state read-back checksum failed for {name}.")
            manifest["databases"].append({
                "name": name,
                "key": key,
                "sha256": raw_hash,
                "compressed_sha256": compressed_hash,
                "raw_bytes": raw_bytes,
                "compressed_bytes": compressed_bytes,
            })
            print(f"S3 STATE DATABASE VERIFIED: generation={generation} database={name} bytes={compressed_bytes}.", flush=True)

        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        manifest_key = f"{generation_prefix}/manifest.json"
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        client.put_object(
            Bucket=bucket, Key=manifest_key, Body=manifest_bytes, ContentType="application/json",
            Metadata={"sha256": manifest_hash, "generation": generation},
        )
        readback_manifest = _get_json(client, bucket, manifest_key)
        if readback_manifest != manifest:
            raise RuntimeError("S3 state manifest read-back validation failed.")

        pointer = {
            "schema_version": 1,
            "generation": generation,
            "created_at": created_at,
            "manifest_key": manifest_key,
            "manifest_sha256": manifest_hash,
        }
        pointer_bytes = json.dumps(pointer, sort_keys=True, separators=(",", ":")).encode("utf-8")
        latest_key = f"{config['prefix']}/latest.json"
        client.put_object(Bucket=bucket, Key=latest_key, Body=pointer_bytes, ContentType="application/json")
        published = _get_json(client, bucket, latest_key)
        if published != pointer:
            raise RuntimeError("S3 state latest-generation pointer read-back validation failed.")

    _prune_old_generations(client, bucket, generation)
    print(f"S3 STATE SNAPSHOT COMPLETE: generation={generation}; databases={len(files)}; verified read-back and latest pointer.", flush=True)


def restore(data_dir: Path) -> bool:
    """Restore the latest complete generation only after checksums and SQLite integrity pass."""
    config = _config()
    client = _client()
    bucket = config["bucket"]
    latest_key = f"{config['prefix']}/latest.json"
    pointer = _get_json(client, bucket, latest_key)
    if pointer is None:
        print("S3 STATE: no published generation exists yet; verified GitHub artifact recovery remains available.", flush=True)
        print("restored=false")
        return False
    generation = str(pointer.get("generation", "")).strip()
    manifest_key = str(pointer.get("manifest_key", "")).strip()
    if not generation or not manifest_key or not manifest_key.startswith(f"{config['prefix']}/generations/{generation}/"):
        raise RuntimeError("S3 state latest pointer is malformed or references an unsafe generation.")
    manifest_response = client.get_object(Bucket=bucket, Key=manifest_key)
    manifest_bytes = manifest_response["Body"].read()
    if hashlib.sha256(manifest_bytes).hexdigest() != str(pointer.get("manifest_sha256", "")):
        raise RuntimeError("S3 state manifest checksum mismatch.")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("S3 state manifest is not valid JSON.") from exc
    if not isinstance(manifest, dict) or manifest.get("generation") != generation or not isinstance(manifest.get("databases"), list):
        raise RuntimeError("S3 state manifest schema or generation is invalid.")

    data_dir = data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="thorio-s3-restore-") as temp:
        staging = Path(temp)
        restored_names: set[str] = set()
        for entry in manifest["databases"]:
            if not isinstance(entry, dict):
                raise RuntimeError("S3 state manifest contains an invalid database entry.")
            name = str(entry.get("name", ""))
            expected_key = _object_key(generation, name)
            key = str(entry.get("key", ""))
            if key != expected_key:
                raise RuntimeError(f"S3 state manifest contains an unsafe or mismatched object key for {name}.")
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise RuntimeError(f"S3 state manifest contains an unsafe database path: {name}")
            target = staging.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            compressed_path = target.with_name(target.name + ".gz")
            client.download_file(bucket, key, str(compressed_path))
            compressed_hash = hashlib.sha256()
            with compressed_path.open("rb") as source:
                while True:
                    block = source.read(CHUNK_BYTES)
                    if not block:
                        break
                    compressed_hash.update(block)
            if compressed_hash.hexdigest() != str(entry.get("compressed_sha256", "")):
                raise RuntimeError(f"S3 state compressed checksum mismatch for {name}.")
            raw_hash = hashlib.sha256()
            try:
                with gzip.open(compressed_path, "rb") as source, target.open("wb") as destination:
                    while True:
                        block = source.read(CHUNK_BYTES)
                        if not block:
                            break
                        raw_hash.update(block)
                        destination.write(block)
            except (OSError, EOFError) as exc:
                raise RuntimeError(f"S3 state compressed database is corrupt for {name}: {exc}") from exc
            if raw_hash.hexdigest() != str(entry.get("sha256", "")):
                raise RuntimeError(f"S3 state database checksum mismatch for {name}.")
            _validate_database(target, primary=(name == "leads.sqlite3"))
            restored_names.add(name)
            compressed_path.unlink(missing_ok=True)
        if "leads.sqlite3" not in restored_names:
            raise RuntimeError("S3 state manifest does not contain the primary leads.sqlite3 database.")

        existing_names = {name for name, _ in _sqlite_files(data_dir)}
        unexpected = sorted(existing_names - restored_names)
        if unexpected:
            raise RuntimeError(
                "S3 restore would remove local SQLite state absent from the selected generation; "
                f"refusing destructive restore and preserving files: {unexpected}"
            )
        for name in sorted(restored_names):
            source = staging.joinpath(*PurePosixPath(name).parts)
            destination = data_dir.joinpath(*PurePosixPath(name).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary_target = destination.with_name(destination.name + ".s3-restore")
            shutil.copy2(source, temporary_target)
            os.replace(temporary_target, destination)

    created_at = str(pointer.get("created_at", manifest.get("created_at", "")))
    print(f"S3 STATE RESTORED: generation={generation}; databases={len(restored_names)}; checksums and SQLite integrity verified.", flush=True)
    print("restored=true")
    print(f"restored_at={created_at}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("snapshot", "restore"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    if args.command == "snapshot":
        snapshot(args.data_dir)
    else:
        restore(args.data_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
