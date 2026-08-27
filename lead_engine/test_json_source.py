import json

import pytest

from .json_source import JsonLeadSource


def test_json_source_reads_lead_array(tmp_path):
    path = tmp_path / "leads.json"

    path.write_text(
        json.dumps(
            [
                {
                    "source": "test",
                    "source_id": "json-001",
                    "url": "https://example.com/json-001",
                    "company": "JSON Corp",
                    "signal": "remote developer",
                    "evidence": "Remote developer opening.",
                }
            ]
        ),
        encoding="utf-8",
    )

    source = JsonLeadSource(
        str(path)
    )

    leads = list(source.collect())

    assert len(leads) == 1
    assert leads[0]["company"] == "JSON Corp"


def test_json_source_reads_wrapped_leads(tmp_path):
    path = tmp_path / "leads.json"

    path.write_text(
        json.dumps(
            {
                "leads": [
                    {
                        "source": "test",
                        "source_id": "json-002",
                        "url": "https://example.com/json-002",
                        "company": "Wrapped Corp",
                        "signal": "developer",
                        "evidence": "Developer opening.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    source = JsonLeadSource(
        str(path)
    )

    leads = list(source.collect())

    assert leads[0]["company"] == "Wrapped Corp"


def test_json_source_requires_existing_file(tmp_path):
    source = JsonLeadSource(
        str(tmp_path / "missing.json")
    )

    with pytest.raises(FileNotFoundError):
        source.collect()


def test_json_source_rejects_invalid_structure(tmp_path):
    path = tmp_path / "invalid.json"

    path.write_text(
        json.dumps(
            {
                "leads": "not-a-list"
            }
        ),
        encoding="utf-8",
    )

    source = JsonLeadSource(
        str(path)
    )

    with pytest.raises(ValueError):
        source.collect()


def test_json_source_rejects_non_object_leads(tmp_path):
    path = tmp_path / "invalid-leads.json"

    path.write_text(
        json.dumps(
            [
                "not-a-lead"
            ]
        ),
        encoding="utf-8",
    )

    source = JsonLeadSource(
        str(path)
    )

    with pytest.raises(ValueError):
        source.collect()
