"""Encrypted, free GitHub Actions cache persistence for Thorio's local state.

The cache is treated as an untrusted transport: authenticate before decrypting,
validate archive paths, then validate every SQLite database before restoring.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"THORIOSTATE1"
CHUNK_SIZE = 1024 * 1024
META_NAME = ".thorio-state-meta.json"


def _keys() -> tuple[bytes, bytes]:
    secret = os.environ.get("THORIO_STATE_ENCRYPTION_KEY", "")
    if len(secret) < 32:
        raise RuntimeError("THORIO_STATE_ENCRYPTION_KEY must contain at least 32 characters.")
    material = hashlib.sha512(secret.encode("utf-8")).digest()
    return material[:32], material[32:]


def _write_all(source: BinaryIO, destination: BinaryIO, encryptor, mac) -> None:
    while True:
        block = source.read(CHUNK_SIZE)
        if not block:
            break
        output = encryptor.update(block)
        destination.write(output)
        mac.update(output)


def _validate_sqlite(path: Path, primary: bool = False) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"State database is missing or empty: {path}")
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise RuntimeError(f"SQLite integrity check failed for {path}: {result!r}")
            if primary:
                tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                missing = sorted({"leads", "checkpoints"} - tables)
                if missing:
                    raise RuntimeError(f"Primary database is missing required tables: {missing}")
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(f"Cannot validate SQLite database {path}: {exc}") from exc


def _sqlite_files(data_dir: Path) -> list[Path]:
    return sorted(
        path for path in data_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}
        and "-wal" not in path.name and "-shm" not in path.name
    )


def snapshot(data_dir: Path, archive: Path) -> None:
    """Create an authenticated encrypted snapshot from a consistent SQLite backup."""
    data_dir = data_dir.resolve()
    primary = data_dir / "leads.sqlite3"
    _validate_sqlite(primary, primary=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc).isoformat()

    with tempfile.TemporaryDirectory(prefix="thorio-state-pack-") as temp:
        root = Path(temp)
        staged = root / "data"
        staged.mkdir()
        for path in sorted(data_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(data_dir)
            name = path.name.lower()
            if name.endswith(("-wal", "-shm")) or name.endswith(".log"):
                continue
            if name in {"scheduled-run-output.txt", "browser-state.json", "browser-worker.pid"}:
                continue
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
                # SQLite's online backup API captures committed WAL contents without
                # copying a live database file and its sidecars independently.
                source_uri = f"file:{path.resolve()}?mode=ro"
                with sqlite3.connect(source_uri, uri=True, timeout=30) as source_conn:
                    source_conn.execute("PRAGMA busy_timeout=30000")
                    with sqlite3.connect(target, timeout=30) as target_conn:
                        source_conn.backup(target_conn, pages=512, sleep=0.05)
                _validate_sqlite(target, primary=(relative.as_posix() == "leads.sqlite3"))
            else:
                shutil.copy2(path, target)

        databases = _sqlite_files(staged)
        if not any(path.relative_to(staged).as_posix() == "leads.sqlite3" for path in databases):
            raise RuntimeError("Encrypted state snapshot is missing data/leads.sqlite3.")
        for database in databases:
            _validate_sqlite(database, primary=(database.relative_to(staged).as_posix() == "leads.sqlite3"))

        tar_path = root / "state.tar.gz"
        with tarfile.open(tar_path, mode="w:gz", compresslevel=1) as bundle:
            for path in sorted(staged.rglob("*")):
                if path.is_file():
                    bundle.add(path, arcname=path.relative_to(staged).as_posix(), recursive=False)
            metadata = json.dumps(
                {"schema_version": 1, "created_at": created_at, "database_count": len(databases)},
                sort_keys=True,
            ).encode("utf-8")
            info = tarfile.TarInfo(META_NAME)
            info.size = len(metadata)
            info.mtime = int(datetime.now(timezone.utc).timestamp())
            import io
            bundle.addfile(info, io.BytesIO(metadata))

        encryption_key, mac_key = _keys()
        nonce = secrets.token_bytes(16)
        header = MAGIC + nonce
        cipher = Cipher(algorithms.AES(encryption_key), modes.CTR(nonce)).encryptor()
        mac = hmac.new(mac_key, header, hashlib.sha256)
        temporary = archive.with_suffix(archive.suffix + ".tmp")
        try:
            with tar_path.open("rb") as source, temporary.open("wb") as destination:
                destination.write(header)
                _write_all(source, destination, cipher, mac)
                tail = cipher.finalize()
                destination.write(tail)
                mac.update(tail)
                destination.write(mac.digest())
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(temporary, archive)
        finally:
            temporary.unlink(missing_ok=True)

    print(
        f"ENCRYPTED STATE SNAPSHOT COMPLETE: databases={len(databases)} "
        f"encrypted_bytes={archive.stat().st_size} created_at={created_at}.",
        flush=True,
    )


def restore(data_dir: Path, archive: Path) -> bool:
    if not archive.is_file() or archive.stat().st_size == 0:
        print("STATE CACHE: no encrypted state archive exists.")
        print("restored=false")
        return False

    encryption_key, mac_key = _keys()
    file_size = archive.stat().st_size
    minimum = len(MAGIC) + 16 + 32
    if file_size < minimum:
        raise RuntimeError("Encrypted state archive is truncated.")
    with archive.open("rb") as source:
        header = source.read(len(MAGIC) + 16)
        if len(header) != len(MAGIC) + 16 or not header.startswith(MAGIC):
            raise RuntimeError("Encrypted state archive has an unknown format.")
        expected_mac = hmac.new(mac_key, header, hashlib.sha256)
        remaining = file_size - len(header) - 32
        while remaining:
            block = source.read(min(CHUNK_SIZE, remaining))
            if not block:
                raise RuntimeError("Encrypted state archive is truncated during authentication.")
            expected_mac.update(block)
            remaining -= len(block)
        supplied_mac = source.read(32)
        if not hmac.compare_digest(expected_mac.digest(), supplied_mac):
            raise RuntimeError("Encrypted state archive authentication failed; refusing to restore it.")

    nonce = header[len(MAGIC):]
    cipher = Cipher(algorithms.AES(encryption_key), modes.CTR(nonce)).decryptor()
    data_dir = data_dir.resolve()
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="thorio-state-restore-") as temp:
        root = Path(temp)
        tar_path = root / "state.tar.gz"
        with archive.open("rb") as source, tar_path.open("wb") as destination:
            source.seek(len(header))
            remaining = file_size - len(header) - 32
            while remaining:
                block = source.read(min(CHUNK_SIZE, remaining))
                if not block:
                    raise RuntimeError("Encrypted state archive is truncated during decryption.")
                destination.write(cipher.update(block))
                remaining -= len(block)
            destination.write(cipher.finalize())

        extracted = root / "extracted"
        extracted.mkdir()
        metadata: dict = {}
        try:
            with tarfile.open(tar_path, mode="r|gz") as bundle:
                # Stream once through the archive. getmembers() followed by
                # extractfile() forces gzip archives to be replayed from the
                # beginning, doubling decompression work for the multi-GB DB.
                for member in bundle:
                    relative = PurePosixPath(member.name)
                    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                        raise RuntimeError(f"Unsafe path in encrypted state archive: {member.name}")
                    if not member.isfile():
                        raise RuntimeError(f"Unexpected non-file entry in encrypted state archive: {member.name}")
                    source = bundle.extractfile(member)
                    if source is None:
                        raise RuntimeError(f"Cannot read state archive entry: {member.name}")
                    if member.name == META_NAME:
                        try:
                            metadata = json.loads(source.read().decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                            raise RuntimeError("State archive metadata is invalid.") from exc
                        continue
                    target = extracted.joinpath(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination, CHUNK_SIZE)
        except (tarfile.TarError, OSError) as exc:
            raise RuntimeError(f"Encrypted state archive could not be unpacked: {exc}") from exc

        primary = extracted / "leads.sqlite3"
        _validate_sqlite(primary, primary=True)
        databases = [
            path for path in extracted.rglob("*")
            if path.is_file() and path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}
        ]
        # The primary database was validated immediately above. Avoid a
        # second full integrity scan of that same large file; validate every
        # additional database exactly once here.
        for database in databases:
            if database == primary:
                continue
            _validate_sqlite(database)
        if metadata.get("schema_version") != 1:
            raise RuntimeError("Encrypted state archive metadata version is missing or unsupported.")
        data_dir.mkdir(parents=True, exist_ok=True)
        for source in sorted(extracted.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(extracted)
            target = data_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".restore-tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, target)

    created_at = str(metadata.get("created_at", ""))
    print(f"ENCRYPTED STATE RESTORED: databases={len(databases)}; authenticated and integrity-checked.", flush=True)
    print("restored=true")
    print(f"restored_at={created_at}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("snapshot", "restore"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--archive", type=Path, default=Path(".thorio-state-cache/state.enc"))
    args = parser.parse_args()
    if args.command == "snapshot":
        snapshot(args.data_dir, args.archive)
    else:
        restore(args.data_dir, args.archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
