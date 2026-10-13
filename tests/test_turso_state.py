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
