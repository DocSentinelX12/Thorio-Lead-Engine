"""Durable, integrity-checked snapshots of Thorio's local SQLite state in Turso.

The engine continues to use local SQLite during a run. This module stores complete,
compressed SQLite backups remotely between runs; it never points sqlite3 at a remote
database or changes the engine's existing database semantics.
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

CHUNK_BYTES = 48 * 1024
DB_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
RETAIN_GENERATIONS = 2


def _credentials() -> tuple[str, str] | None:
    url = os.environ.get("TURSO_DATABASE_URL", "").strip()
    token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
    if not url and not token:
        return None
    if not url or not token:
        raise RuntimeError("Turso state storage is partially configured: both TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are required.")
    return url, token


def _is_expired_stream_error(exc: BaseException) -> bool:
    """Recognize only the Turso/libSQL stream failures safe to recover by reconnecting."""
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "stream not found",
            "stream expired",
            "unknown stream",
            "stream is no longer valid",
        )
    )


class _ResilientCursor:
    """Retry a failed read only if its stream expires while fetching results."""

    def __init__(self, connection, cursor, sql, args, kwargs):
        self._connection = connection
        self._cursor = cursor
        self._sql = sql
        self._args = args
        self._kwargs = kwargs
        self._consumed = False

    def _fetch(self, method: str):
        try:
            result = getattr(self._cursor, method)()
            self._consumed = True
            return result
        except Exception as exc:
            if not _is_expired_stream_error(exc) or self._consumed:
                raise
            statement = self._sql.lstrip().upper()
            if not statement.startswith(("SELECT", "PRAGMA", "WITH", "EXPLAIN")):
                raise
            self._connection._reconnect()
            self._cursor = self._connection._connection.execute(
                self._sql, *self._args, **self._kwargs
            )
            result = getattr(self._cursor, method)()
            self._consumed = True
            return result

    def fetchone(self):
        return self._fetch("fetchone")

    def fetchall(self):
        return self._fetch("fetchall")

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _ResilientConnection:
    """Reconnect once after a stale Turso stream; never reuse the failed connection.

    State writes made through this wrapper must be idempotent because a transport
    failure can happen after the server applied a statement but before its reply
    reached the client. Snapshot inserts therefore use INSERT OR REPLACE with
    stable generation/database/chunk keys.
    """

    def __init__(self, connection_factory):
        self._connection_factory = connection_factory
        self._connection = connection_factory()
        self._last_statement = None

    @staticmethod
    def _is_idempotent_write(sql: str) -> bool:
        statement = sql.lstrip().upper()
        return statement.startswith((
            "INSERT OR REPLACE",
            "UPDATE",
            "DELETE",
            "CREATE TABLE IF NOT EXISTS",
        ))

    def _reconnect(self) -> None:
        old = self._connection
        try:
            old.close()
        except Exception:
            pass
        self._connection = self._connection_factory()

    def execute(self, sql, *args, **kwargs):
        self._last_statement = (sql, args, kwargs)
        try:
            cursor = self._connection.execute(sql, *args, **kwargs)
        except Exception as exc:
            if not _is_expired_stream_error(exc):
                raise
            self._reconnect()
            # A second failure propagates. Do not loop indefinitely or hide a
            # credential, schema, or genuine database error.
            cursor = self._connection.execute(sql, *args, **kwargs)
        return _ResilientCursor(self, cursor, sql, args, kwargs)

    def commit(self) -> None:
        try:
            self._connection.commit()
        except Exception as exc:
            if not _is_expired_stream_error(exc):
                raise
            self._reconnect()
            if not self._last_statement or not self._is_idempotent_write(self._last_statement[0]):
                raise RuntimeError(
                    "Turso stream expired during commit and the last statement cannot be replayed safely."
                ) from exc
            sql, args, kwargs = self._last_statement
            # Commit outcomes can be ambiguous. Replaying the same idempotent
            # write after reconnect handles both rollback and lost acknowledgments.
            self._connection.execute(sql, *args, **kwargs)
            self._connection.commit()

    def close(self) -> None:
        # Closing an already-expired remote stream is cleanup, not a reason to
        # turn an otherwise verified snapshot/restore into a failed operation.
        try:
            self._connection.close()
        except Exception:
            pass


def _connect():
    credentials = _credentials()
    if credentials is None:
        return None
    try:
        import turso_serverless
    except ImportError as exc:
        raise RuntimeError("Turso state storage is configured, but turso_serverless is not installed.") from exc
    url, token = credentials
    return _ResilientConnection(
        lambda: turso_serverless.connect(url, auth_token=token)
    )


def _ensure_schema(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS thorio_state_generations (
            generation_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            database_count INTEGER NOT NULL,
            manifest_sha256 TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS thorio_state_chunks (
            generation_id TEXT NOT NULL,
            database_name TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_count INTEGER NOT NULL,
            compressed_sha256 TEXT NOT NULL,
            payload BLOB NOT NULL,
            PRIMARY KEY (generation_id, database_name, chunk_index)
        )"""
    )
    conn.commit()


def _sqlite_files(data_dir: Path) -> list[tuple[str, Path]]:
    found = []
    for path in sorted(data_dir.rglob("*")):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in DB_SUFFIXES:
            continue
        relative = path.relative_to(data_dir).as_posix()
        found.append((relative, path))
    return found


def _backup_bytes(source: Path) -> bytes:
    with tempfile.TemporaryDirectory(prefix="thorio-state-backup-") as temporary:
        backup_path = Path(temporary) / "snapshot.sqlite3"
        source_uri = f"file:{source.resolve()}?mode=ro"
        with sqlite3.connect(source_uri, uri=True, timeout=60) as src:
            with sqlite3.connect(backup_path, timeout=60) as dst:
                src.backup(dst)
                check = dst.execute("PRAGMA integrity_check").fetchone()
                if not check or check[0] != "ok":
                    raise RuntimeError(f"SQLite backup integrity failed for {source}: {check!r}")
        return backup_path.read_bytes()


def _validate_primary_database(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("Turso state snapshot has no non-empty data/leads.sqlite3; refusing to restore empty production state.")
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=60) as conn:
        check = conn.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != "ok":
            raise RuntimeError(f"Restored primary SQLite integrity check failed: {check!r}")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted({"leads", "checkpoints"} - tables)
        if missing:
            raise RuntimeError(f"Restored primary database is missing required tables: {missing}")


def _complete_generations(conn) -> list[tuple]:
    return conn.execute(
        "SELECT generation_id, created_at, database_count, manifest_sha256 "
        "FROM thorio_state_generations WHERE status = 'complete' ORDER BY created_at DESC"
    ).fetchall()


def restore(data_dir: Path) -> bool:
    """Restore the newest complete remote snapshot. Return False only if none exists."""
    conn = _connect()
    if conn is None:
        print("TURSO STATE: credentials not configured; existing artifact recovery remains active.")
        return False
    try:
        _ensure_schema(conn)
        generations = _complete_generations(conn)
        if not generations:
            print("TURSO STATE: no complete remote generation exists yet; existing artifact recovery remains active.")
            return False
        generation_id, generation_created_at, expected_count, expected_manifest = generations[0]
        rows = conn.execute(
            "SELECT database_name, chunk_index, chunk_count, compressed_sha256, payload "
            "FROM thorio_state_chunks WHERE generation_id = ? ORDER BY database_name, chunk_index",
            (generation_id,),
        ).fetchall()
        grouped: dict[str, list[tuple]] = {}
        for row in rows:
            grouped.setdefault(str(row[0]), []).append(row)
        if len(grouped) != int(expected_count):
            raise RuntimeError("Turso state snapshot is incomplete: database count does not match its manifest.")
        manifest = []
        staged: list[tuple[str, Path]] = []
        with tempfile.TemporaryDirectory(prefix="thorio-state-restore-") as temporary:
            root = Path(temporary)
            for name, chunks in sorted(grouped.items()):
                relative = PurePosixPath(name)
                if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                    raise RuntimeError(f"Unsafe database path in Turso state manifest: {name!r}")
                expected_chunks = int(chunks[0][2])
                if len(chunks) != expected_chunks or [int(item[1]) for item in chunks] != list(range(expected_chunks)):
                    raise RuntimeError(f"Turso state snapshot has missing or out-of-order chunks for {name}.")
                compressed = b"".join(bytes(item[4]) for item in chunks)
                digest = hashlib.sha256(compressed).hexdigest()
                if digest != str(chunks[0][3]):
                    raise RuntimeError(f"Turso state snapshot checksum mismatch for {name}.")
                target = root.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(gzip.decompress(compressed))
                with sqlite3.connect(f"file:{target.resolve()}?mode=ro", uri=True, timeout=60) as db:
                    check = db.execute("PRAGMA integrity_check").fetchone()
                if not check or check[0] != "ok":
                    raise RuntimeError(f"Turso restored SQLite integrity check failed for {name}: {check!r}")
                staged.append((name, target))
                manifest.append({"name": name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
            actual_manifest = hashlib.sha256(
                json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if actual_manifest != str(expected_manifest):
                raise RuntimeError("Turso state snapshot manifest checksum mismatch.")
            primary = root / "leads.sqlite3"
            _validate_primary_database(primary)
            data_dir.mkdir(parents=True, exist_ok=True)
            staged_names = {name for name, _ in staged}
            existing_names = {name for name, _ in _sqlite_files(data_dir)}
            unexpected = sorted(existing_names - staged_names)
            if unexpected:
                raise RuntimeError(
                    "Turso restore would remove local SQLite state absent from the selected generation; "
                    f"refusing destructive restore and preserving files: {unexpected}"
                )
            for name, source in staged:
                destination = data_dir.joinpath(*PurePosixPath(name).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary_target = destination.with_name(destination.name + ".turso-restore")
                shutil.copy2(source, temporary_target)
                os.replace(temporary_target, destination)
        print(f"TURSO STATE RESTORED: generation={generation_id}; databases={len(staged)}; SQLite integrity and manifest verified.")
        print(f"restored_at={generation_created_at}")
        return True
    finally:
        conn.close()


def snapshot(data_dir: Path) -> None:
    """Write a new complete generation, then prune old generations."""
    conn = _connect()
    if conn is None:
        raise RuntimeError("Turso state snapshot requested without TURSO_DATABASE_URL and TURSO_AUTH_TOKEN.")
    try:
        _ensure_schema(conn)
        files = _sqlite_files(data_dir)
        by_name = dict(files)
        if "leads.sqlite3" not in by_name:
            raise RuntimeError("Cannot snapshot Thorio state: data/leads.sqlite3 is missing.")
        _validate_primary_database(by_name["leads.sqlite3"])
        generation_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO thorio_state_generations (generation_id, created_at, status, database_count, manifest_sha256) VALUES (?, ?, 'writing', ?, '')",
            (generation_id, created_at, len(files)),
        )
        conn.commit()
        manifest = []
        for name, source in files:
            raw = _backup_bytes(source)
            compressed = gzip.compress(raw, mtime=0)
            compressed_hash = hashlib.sha256(compressed).hexdigest()
            count = max(1, (len(compressed) + CHUNK_BYTES - 1) // CHUNK_BYTES)
            for index in range(count):
                payload = compressed[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES]
                conn.execute(
                    "INSERT OR REPLACE INTO thorio_state_chunks (generation_id, database_name, chunk_index, chunk_count, compressed_sha256, payload) VALUES (?, ?, ?, ?, ?, ?)",
                    (generation_id, name, index, count, compressed_hash, payload),
                )
                # Commit each idempotent chunk independently. Long interactive
                # Turso streams can expire during a large snapshot; per-chunk
                # commits bound the amount of work that must be retried.
                conn.commit()
            manifest.append({"name": name, "sha256": hashlib.sha256(raw).hexdigest()})
        manifest_hash = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        conn.execute(
            "UPDATE thorio_state_generations SET status = 'complete', manifest_sha256 = ? WHERE generation_id = ?",
            (manifest_hash, generation_id),
        )
        conn.commit()
        generations = _complete_generations(conn)
        for old_generation in generations[RETAIN_GENERATIONS:]:
            old_id = old_generation[0]
            conn.execute("DELETE FROM thorio_state_chunks WHERE generation_id = ?", (old_id,))
            conn.execute("DELETE FROM thorio_state_generations WHERE generation_id = ?", (old_id,))
        conn.commit()
        print(f"TURSO STATE SNAPSHOT VERIFIED: generation={generation_id}; databases={len(files)}; retained_generations={min(len(generations), RETAIN_GENERATIONS)}.")
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("restore", "snapshot"))
    parser.add_argument("--data-dir", default=os.environ.get("LEAD_ENGINE_DATA_DIR", "data"))
    args = parser.parse_args()
    data_dir = Path(args.data_dir)
    try:
        if args.action == "restore":
            restored = restore(data_dir)
            print(f"restored={'true' if restored else 'false'}")
        else:
            snapshot(data_dir)
    except Exception as exc:
        print(f"TURSO STATE FAILURE: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
