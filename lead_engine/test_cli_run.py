import json

from .cli import main


def test_run_json_processes_leads(tmp_path, capsys):
    source = tmp_path / "leads.json"

    source.write_text(
        json.dumps(
            {
                "leads": [
                    {
                        "source": "test",
                        "source_id": "cli-run-001",
                        "url": "https://example.com/jobs/cli-run-001",
                        "company": "CLI Run Corp",
                        "signal": "remote software engineer",
                        "evidence": "Remote software engineer opening found.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = main(
        [
            "run-json",
            str(source),
        ]
    )

    assert result == 0

    output = json.loads(
        capsys.readouterr().out
    )

    assert output["source_count"] == 1
    assert output["failed_count"] == 0
    assert len(output["results"]) == 1
