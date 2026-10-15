from __future__ import annotations

import sqlite3
from pathlib import Path

from lead_engine import turso_state


class PersistentConnection:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")

    def execute(self, *args, **kwargs):
        return self.connection.execute(*args, **kwargs)

    def commit(self):
        return self.connection.commit()

    def close(self):
        # Simulate a remote database connection that can be reopened between calls.
        return None


class BatchPersistentConnection(PersistentConnection):
    def __init__(self):
        super().__init__()
        self.batch_calls = []

    def batch(self, statements, mode=None):
        statements = list(statements)
        self.batch_calls.append((len(statements), mode))
        if mode == "immediate":
            self.connection.execute("BEGIN IMMEDIATE")
        try:
            for sql, parameters in statements:
                self.connection.execute(sql, parameters)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return [None] * len(statements)


class ExpiringConnection:
    def __init__(self, delegate):
        self.delegate = delegate
        self.expire_next_execute = True

    def execute(self, *args, **kwargs):
        if self.expire_next_execute:
            self.expire_next_execute = False
            raise RuntimeError("HTTP 404: stream not found")
        return self.delegate.execute(*args, **kwargs)

    def commit(self):
        return self.delegate.commit()

    def close(self):
        return None


def test_resilient_connection_reopens_expired_turso_stream():
    remote = PersistentConnection()
    connections = []

    def factory():
        if not connections:
            connection = ExpiringConnection(remote)
        else:
            connection = remote
        connections.append(connection)
        return connection

    connection = turso_state._ResilientConnection(factory)
    connection.execute("CREATE TABLE IF NOT EXISTS stream_recovery (value TEXT)")
    connection.execute("INSERT OR REPLACE INTO stream_recovery (rowid, value) VALUES (1, 'preserved')")
    connection.commit()

    row = connection.execute("SELECT value FROM stream_recovery WHERE rowid = 1").fetchone()
    assert row[0] == "preserved"
    assert len(connections) == 2


class ExpiringFetchCursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.expire_next_fetch = True

    def fetchone(self):
        if self.expire_next_fetch:
            self.expire_next_fetch = False
            raise RuntimeError("stream not found")
        return self.cursor.fetchone()

    def fetchall(self):
        if self.expire_next_fetch:
            self.expire_next_fetch = False
            raise RuntimeError("stream not found")
        return self.cursor.fetchall()

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class ExpiringFetchConnection:
    def __init__(self, delegate):
        self.delegate = delegate

    def execute(self, *args, **kwargs):
        cursor = self.delegate.execute(*args, **kwargs)
        if args and str(args[0]).lstrip().upper().startswith("SELECT"):
            return ExpiringFetchCursor(cursor)
        return cursor

    def commit(self):
        return self.delegate.commit()

    def close(self):
        return None



def test_resilient_connection_does_not_replay_non_idempotent_insert_after_stream_loss():
    remote = PersistentConnection()
    remote.execute("CREATE TABLE unsafe_replay (value TEXT)")
    remote.commit()
    connections = []

    def factory():
        connection = ExpiringConnection(remote) if not connections else remote
        connections.append(connection)
        return connection

    connection = turso_state._ResilientConnection(factory)
    try:
        connection.execute("INSERT INTO unsafe_replay(value) VALUES ('must-not-be-replayed')")
    except RuntimeError as exc:
        assert "cannot be replayed safely" in str(exc)
    else:
        raise AssertionError("a non-idempotent statement must not be replayed after an ambiguous stream failure")

    assert len(connections) == 1
    assert remote.execute("SELECT COUNT(*) FROM unsafe_replay").fetchone()[0] == 0


def test_resilient_connection_reopens_stream_that_expires_during_read():
    remote = PersistentConnection()
    connections = []

    def factory():
        connection = ExpiringFetchConnection(remote) if not connections else remote
        connections.append(connection)
        return connection

    connection = turso_state._ResilientConnection(factory)
    connection.execute("CREATE TABLE IF NOT EXISTS fetch_recovery (value TEXT)")
    connection.execute("INSERT OR REPLACE INTO fetch_recovery (rowid, value) VALUES (1, 'preserved')")
    connection.commit()

    rows = connection.execute("SELECT value FROM fetch_recovery").fetchall()
    assert rows == [("preserved",)]
    assert len(connections) == 2


class ExpiringCommitConnection:
    def __init__(self, delegate):
        self.delegate = delegate
        self.commit_count = 0

    def execute(self, *args, **kwargs):
        return self.delegate.execute(*args, **kwargs)

    def commit(self):
        self.commit_count += 1
        self.delegate.commit()
        if self.commit_count == 2:
            raise RuntimeError("HTTP 404: stream not found")

    def close(self):
        return None


def test_resilient_connection_replays_idempotent_write_after_ambiguous_commit():
    remote = PersistentConnection()
    connections = []

    def factory():
        connection = ExpiringCommitConnection(remote) if not connections else remote
        connections.append(connection)
        return connection

    connection = turso_state._ResilientConnection(factory)
    connection.execute("CREATE TABLE IF NOT EXISTS commit_recovery (value TEXT)")
    connection.commit()
    connection.execute("INSERT OR REPLACE INTO commit_recovery (rowid, value) VALUES (1, 'preserved')")
    connection.commit()

    rows = connection.execute("SELECT value FROM commit_recovery").fetchall()
    assert rows == [("preserved",)]
    assert len(connections) == 2


def make_data_dir(path: Path, lead_name: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path / "leads.sqlite3") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS leads (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS checkpoints (id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("DELETE FROM leads")
        conn.execute("INSERT INTO leads(name) VALUES (?)", (lead_name,))
        conn.execute("INSERT OR REPLACE INTO checkpoints(id, value) VALUES (1, ?)", (lead_name,))
    with sqlite3.connect(path / "queue.sqlite3") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS queue (id INTEGER PRIMARY KEY, payload TEXT)")
        conn.execute("INSERT OR REPLACE INTO queue(id, payload) VALUES (1, ?)", (lead_name,))


class DroppingChunkConnection(PersistentConnection):
    def __init__(self):
        super().__init__()
        self.dropped_chunk = False

    def execute(self, sql, *args, **kwargs):
        if (
            "INSERT OR REPLACE INTO thorio_state_chunks" in str(sql)
            and not self.dropped_chunk
        ):
            self.dropped_chunk = True
            return self.connection.execute("SELECT 1")
        return self.connection.execute(sql, *args, **kwargs)


def test_turso_snapshot_batches_remote_chunk_writes(monkeypatch, tmp_path):
    remote = BatchPersistentConnection()
    monkeypatch.setattr(turso_state, "_connect", lambda: remote)
    data_dir = tmp_path / "data"
    make_data_dir(data_dir, "batched-state")

    turso_state.snapshot(data_dir)

    assert remote.batch_calls == [(1, "immediate")]
    statuses = remote.execute(
        "SELECT status FROM thorio_state_generations"
    ).fetchall()
    assert statuses == [("complete",)]


def test_turso_snapshot_never_marks_missing_remote_chunks_complete(monkeypatch, tmp_path):
    remote = DroppingChunkConnection()
    monkeypatch.setattr(turso_state, "_connect", lambda: remote)
    data_dir = tmp_path / "data"
    make_data_dir(data_dir, "local-state")

    try:
        turso_state.snapshot(data_dir)
    except RuntimeError as exc:
        assert "read-back failed" in str(exc)
    else:
        raise AssertionError("snapshot must reject a generation whose remote chunk is missing")

    statuses = remote.execute(
        "SELECT status FROM thorio_state_generations"
    ).fetchall()
    assert statuses == [("writing",)]


def test_turso_snapshot_restores_all_sqlite_state_with_integrity(monkeypatch, tmp_path):
    remote = PersistentConnection()
    monkeypatch.setattr(turso_state, "_connect", lambda: remote)
    data_dir = tmp_path / "data"
    make_data_dir(data_dir, "remote-version")

    turso_state.snapshot(data_dir)

    make_data_dir(data_dir, "local-corruption-or-newer-run")
    assert turso_state.restore(data_dir) is True

    with sqlite3.connect(data_dir / "leads.sqlite3") as conn:
        assert conn.execute("SELECT name FROM leads").fetchone()[0] == "remote-version"
        assert conn.execute("SELECT value FROM checkpoints WHERE id = 1").fetchone()[0] == "remote-version"
    with sqlite3.connect(data_dir / "queue.sqlite3") as conn:
        assert conn.execute("SELECT payload FROM queue WHERE id = 1").fetchone()[0] == "remote-version"



def test_turso_restore_falls_back_to_older_verified_generation(monkeypatch, tmp_path):
    remote = PersistentConnection()
    monkeypatch.setattr(turso_state, "_connect", lambda: remote)
    data_dir = tmp_path / "data"
    make_data_dir(data_dir, "older-good-state")
    turso_state.snapshot(data_dir)

    make_data_dir(data_dir, "newer-corrupt-state")
    turso_state.snapshot(data_dir)
    newest = remote.execute(
        "SELECT generation_id FROM thorio_state_generations "
        "WHERE status = 'complete' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()[0]
    remote.execute(
        "UPDATE thorio_state_chunks SET payload = ? "
        "WHERE generation_id = ? AND database_name = 'leads.sqlite3' AND chunk_index = 0",
        (b"corrupt-newest-generation", newest),
    )
    remote.commit()

    make_data_dir(data_dir, "local-state-to-recover")
    assert turso_state.restore(data_dir) is True
    with sqlite3.connect(data_dir / "leads.sqlite3") as conn:
        assert conn.execute("SELECT name FROM leads").fetchone()[0] == "older-good-state"


def test_turso_restore_refuses_corrupt_or_incomplete_snapshot(monkeypatch, tmp_path):
    remote = PersistentConnection()
    monkeypatch.setattr(turso_state, "_connect", lambda: remote)
    data_dir = tmp_path / "data"
    make_data_dir(data_dir, "good-state")
    turso_state.snapshot(data_dir)

    remote.execute("UPDATE thorio_state_chunks SET payload = ? WHERE database_name = 'leads.sqlite3' AND chunk_index = 0", (b"corrupt",))
    remote.commit()

    with sqlite3.connect(data_dir / "leads.sqlite3") as conn:
        conn.execute("UPDATE leads SET name = 'must-not-be-overwritten'")
    try:
        turso_state.restore(data_dir)
    except RuntimeError as exc:
        assert "checksum mismatch" in str(exc) or "integrity" in str(exc)
    else:
        raise AssertionError("corrupt remote state must be rejected")
    with sqlite3.connect(data_dir / "leads.sqlite3") as conn:
        assert conn.execute("SELECT name FROM leads").fetchone()[0] == "must-not-be-overwritten"


def test_turso_restore_returns_false_when_no_complete_generation_exists(monkeypatch, tmp_path):
    remote = PersistentConnection()
    monkeypatch.setattr(turso_state, "_connect", lambda: remote)
    assert turso_state.restore(tmp_path / "data") is False

def test_turso_restore_refuses_to_delete_local_database_missing_from_snapshot(monkeypatch, tmp_path):
    remote = PersistentConnection()
    monkeypatch.setattr(turso_state, "_connect", lambda: remote)
    data_dir = tmp_path / "data"
    make_data_dir(data_dir, "known-state")
    turso_state.snapshot(data_dir)

    extra_database = data_dir / "newer-state.sqlite3"
    with sqlite3.connect(extra_database) as conn:
        conn.execute("CREATE TABLE preserved (value TEXT)")
        conn.execute("INSERT INTO preserved(value) VALUES ('must-survive')")

    try:
        turso_state.restore(data_dir)
    except RuntimeError as exc:
        assert "refusing destructive restore" in str(exc)
    else:
        raise AssertionError("restore must not delete a local database absent from the selected generation")

    assert extra_database.is_file()
    with sqlite3.connect(extra_database) as conn:
        assert conn.execute("SELECT value FROM preserved").fetchone()[0] == "must-survive"
