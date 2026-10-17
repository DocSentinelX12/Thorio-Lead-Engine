from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

from lead_engine import s3_state


class FakeBody(io.BytesIO):
    pass


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakePaginator:
    def __init__(self, client):
        self.client = client

    def paginate(self, Bucket, Prefix):
        return [{"Contents": [
            {"Key": key} for key in self.client.objects
            if key.startswith(Prefix)
        ]}]


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.metadata = {}

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.objects[key] = Path(filename).read_bytes()
        self.metadata[key] = dict((ExtraArgs or {}).get("Metadata", {}))

    def put_object(self, Bucket, Key, Body, ContentType=None, Metadata=None):
        self.objects[Key] = Body.read() if hasattr(Body, "read") else bytes(Body)
        self.metadata[Key] = dict(Metadata or {})
        return {"ETag": '"fake"'}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise FakeClientError("NoSuchKey")
        return {"Body": FakeBody(self.objects[Key])}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise FakeClientError("NoSuchKey")
        return {"ContentLength": len(self.objects[Key]), "Metadata": self.metadata.get(Key, {})}

    def download_file(self, bucket, key, filename):
        Path(filename).write_bytes(self.objects[key])

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return FakePaginator(self)

    def delete_objects(self, Bucket, Delete):
        for item in Delete["Objects"]:
            self.objects.pop(item["Key"], None)
            self.metadata.pop(item["Key"], None)


def configure(monkeypatch):
    monkeypatch.setenv("THORIO_STATE_S3_ENDPOINT_URL", "https://example.invalid")
    monkeypatch.setenv("THORIO_STATE_S3_BUCKET", "thorio-state")
    monkeypatch.setenv("THORIO_STATE_S3_ACCESS_KEY_ID", "test-access")
    monkeypatch.setenv("THORIO_STATE_S3_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("THORIO_STATE_S3_REGION", "auto")
    monkeypatch.setenv("THORIO_STATE_S3_PREFIX", "thorio/lead-engine")


def make_data_dir(path: Path, label: str):
    path.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path / "leads.sqlite3") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS leads (fingerprint TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS checkpoints (collector TEXT PRIMARY KEY, checkpoint TEXT NOT NULL)")
        conn.execute("DELETE FROM leads")
        conn.execute("DELETE FROM checkpoints")
        conn.execute("INSERT INTO leads VALUES (?, ?)", (label, json.dumps({"name": label})))
        conn.execute("INSERT INTO checkpoints VALUES (?, ?)", ("source", label))
    with sqlite3.connect(path / "queue.sqlite3") as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS queue (task_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute("DELETE FROM queue")
        conn.execute("INSERT INTO queue VALUES (?, ?)", ("task-1", label))


def test_s3_snapshot_restores_all_databases_with_integrity(monkeypatch, tmp_path):
    configure(monkeypatch)
    client = FakeS3()
    monkeypatch.setattr(s3_state, "_client", lambda: client)
    data_dir = tmp_path / "data"
    make_data_dir(data_dir, "remote-version")

    s3_state.snapshot(data_dir)

    assert f"{s3_state._prefix()}/latest.json" in client.objects
    make_data_dir(data_dir, "local-version")
    assert s3_state.restore(data_dir) is True

    with sqlite3.connect(data_dir / "leads.sqlite3") as conn:
        assert conn.execute("SELECT fingerprint FROM leads").fetchone()[0] == "remote-version"
        assert conn.execute("SELECT checkpoint FROM checkpoints").fetchone()[0] == "remote-version"
    with sqlite3.connect(data_dir / "queue.sqlite3") as conn:
        assert conn.execute("SELECT payload FROM queue").fetchone()[0] == "remote-version"


def test_s3_restore_returns_false_without_published_generation(monkeypatch, tmp_path):
    configure(monkeypatch)
    monkeypatch.setattr(s3_state, "_client", lambda: FakeS3())
    assert s3_state.restore(tmp_path / "data") is False


def test_s3_restore_rejects_manifest_checksum_tampering(monkeypatch, tmp_path):
    configure(monkeypatch)
    client = FakeS3()
    monkeypatch.setattr(s3_state, "_client", lambda: client)
    data_dir = tmp_path / "data"
    make_data_dir(data_dir, "verified")
    s3_state.snapshot(data_dir)

    latest_key = f"{s3_state._prefix()}/latest.json"
    pointer = json.loads(client.objects[latest_key])
    pointer["manifest_sha256"] = "0" * 64
    client.objects[latest_key] = json.dumps(pointer, sort_keys=True, separators=(",", ":")).encode()

    make_data_dir(data_dir, "local-preserved")
    try:
        s3_state.restore(data_dir)
    except RuntimeError as exc:
        assert "manifest checksum mismatch" in str(exc)
    else:
        raise AssertionError("tampered manifest pointer must be rejected")

    with sqlite3.connect(data_dir / "leads.sqlite3") as conn:
        assert conn.execute("SELECT fingerprint FROM leads").fetchone()[0] == "local-preserved"


def test_s3_configuration_fails_closed_when_credentials_are_missing(monkeypatch):
    for name in (
        "THORIO_STATE_S3_ENDPOINT_URL",
        "THORIO_STATE_S3_BUCKET",
        "THORIO_STATE_S3_ACCESS_KEY_ID",
        "THORIO_STATE_S3_SECRET_ACCESS_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    try:
        s3_state._config()
    except RuntimeError as exc:
        assert "not configured" in str(exc)
    else:
        raise AssertionError("durable storage must not silently disable itself")
