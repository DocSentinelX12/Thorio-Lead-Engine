from .audit import AuditLog


def test_audit_log_records_event(tmp_path):
    log = AuditLog(
        str(tmp_path / "audit.jsonl")
    )

    result = log.record(
        "lead_imported",
        fingerprint="audit-001",
        company="Audit Corp",
    )

    assert result["event"] == "lead_imported"
    assert result["fingerprint"] == "audit-001"
    assert result["company"] == "Audit Corp"
    assert "timestamp" in result


def test_audit_log_is_append_only(tmp_path):
    log = AuditLog(
        str(tmp_path / "audit.jsonl")
    )

    log.record(
        "first_event",
        value=1,
    )

    log.record(
        "second_event",
        value=2,
    )

    entries = log.read()

    assert len(entries) == 2
    assert entries[0]["event"] == "first_event"
    assert entries[1]["event"] == "second_event"


def test_audit_log_empty_when_file_missing(tmp_path):
    log = AuditLog(
        str(tmp_path / "missing.jsonl")
    )

    assert log.read() == []
