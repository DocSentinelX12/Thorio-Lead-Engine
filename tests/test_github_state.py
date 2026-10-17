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

    github_state.snapshot(source, archive)
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
