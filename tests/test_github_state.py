from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from lead_engine import github_state


def make_data(root: Path, label: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(root / "leads.sqlite3") as conn:
        conn.execute("CREATE TABLE leads (fingerprint TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute("CREATE TABLE checkpoints (collector TEXT PRIMARY KEY, checkpoint TEXT NOT NULL)")
        conn.execute("INSERT INTO leads VALUES (?, ?)", (label, json.dumps({"company": label})))
        conn.execute("INSERT INTO checkpoints VALUES (?, ?)", ("source", label))


def test_encrypted_snapshot_round_trip_restores_sqlite_and_other_state(tmp_path, monkeypatch):
    monkeypatch.setenv("THORIO_STATE_ENCRYPTION_KEY", "a-test-key-that-is-long-enough-for-encryption")
    source = tmp_path / "source"
    target = tmp_path / "target"
    archive = tmp_path / "state.enc"
    make_data(source, "lead-a")
    (source / "queue.json").write_text('{"pending": 3}', encoding="utf-8")
    original_tar_open = github_state.tarfile.open
    compression = {}

    def record_archive_compression(*args, **kwargs):
        if kwargs.get("mode") == "w:gz":
            compression["level"] = kwargs.get("compresslevel")
        return original_tar_open(*args, **kwargs)

    monkeypatch.setattr(github_state.tarfile, "open", record_archive_compression)
    github_state.snapshot(source, archive)
    assert compression["level"] == 1
    assert archive.is_file()
    assert b"lead-a" not in archive.read_bytes()
    assert github_state.restore(target, archive) is True

    with sqlite3.connect(target / "leads.sqlite3") as conn:
        assert conn.execute("SELECT fingerprint FROM leads").fetchone()[0] == "lead-a"
        assert conn.execute("SELECT checkpoint FROM checkpoints").fetchone()[0] == "lead-a"
    assert (target / "queue.json").read_text(encoding="utf-8") == '{"pending": 3}'


def test_tampered_encrypted_archive_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("THORIO_STATE_ENCRYPTION_KEY", "a-test-key-that-is-long-enough-for-encryption")
    source = tmp_path / "source"
    archive = tmp_path / "state.enc"
    make_data(source, "lead-a")
    github_state.snapshot(source, archive)
    content = bytearray(archive.read_bytes())
    content[len(github_state.MAGIC) + 16 + 1] ^= 0x40
    archive.write_bytes(content)

    with pytest.raises(RuntimeError, match="authentication failed"):
        github_state.restore(tmp_path / "target", archive)


def test_wrong_key_is_rejected(tmp_path, monkeypatch):
    source = tmp_path / "source"
    archive = tmp_path / "state.enc"
    monkeypatch.setenv("THORIO_STATE_ENCRYPTION_KEY", "a-test-key-that-is-long-enough-for-encryption")
    make_data(source, "lead-a")
    github_state.snapshot(source, archive)
    monkeypatch.setenv("THORIO_STATE_ENCRYPTION_KEY", "a-different-key-that-is-also-long-enough")
    with pytest.raises(RuntimeError, match="authentication failed"):
        github_state.restore(tmp_path / "target", archive)


def test_missing_archive_is_a_first_run_not_a_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("THORIO_STATE_ENCRYPTION_KEY", "a-test-key-that-is-long-enough-for-encryption")
    assert github_state.restore(tmp_path / "data", tmp_path / "missing.enc") is False

def test_restore_validates_primary_once_and_each_secondary_database_once(tmp_path, monkeypatch):
    monkeypatch.setenv("THORIO_STATE_ENCRYPTION_KEY", "a-test-key-that-is-long-enough-for-encryption")
    source = tmp_path / "source"
    target = tmp_path / "target"
    archive = tmp_path / "state.enc"
    make_data(source, "lead-a")
    with sqlite3.connect(source / "worker.db") as connection:
        connection.execute("CREATE TABLE worker_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO worker_state VALUES (?, ?)", ("checkpoint", "worker-a"))
    github_state.snapshot(source, archive)

    original_validate = github_state._validate_sqlite
    validated = []

    def record_validation(path, primary=False):
        validated.append((Path(path).name, primary))
        return original_validate(path, primary=primary)

    monkeypatch.setattr(github_state, "_validate_sqlite", record_validation)
    assert github_state.restore(target, archive) is True
    assert validated.count(("leads.sqlite3", True)) == 1
    assert validated.count(("worker.db", False)) == 1
