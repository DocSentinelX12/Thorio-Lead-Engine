import json

from .cli import main


def test_cli_status(monkeypatch, capsys):
    class FakeApplication:
        def status(self):
            return {
                "total_leads": 3,
                "synced_leads": 2,
                "pending_leads": 1,
                "healthy": False,
            }

        def health(self):
            return {"healthy": True}

        def work_queue(self):
            return []

        def run_sources(self, sources):
            return {}


    monkeypatch.setattr(
        "lead_engine.cli.create_application",
        lambda: FakeApplication(),
    )

    result = main(["status"])

    assert result == 0

    output = json.loads(
        capsys.readouterr().out
    )

    assert output["total_leads"] == 3
    assert output["pending_leads"] == 1


def test_cli_health(monkeypatch, capsys):
    class FakeApplication:
        def status(self):
            return {}

        def health(self):
            return {
                "healthy": True,
            }

        def work_queue(self):
            return []

        def run_sources(self, sources):
            return {}

    monkeypatch.setattr(
        "lead_engine.cli.create_application",
        lambda: FakeApplication(),
    )

    result = main(["health"])

    assert result == 0

    output = json.loads(
        capsys.readouterr().out
    )

    assert output["healthy"] is True


def test_cli_work_queue(monkeypatch, capsys):
    class FakeApplication:
        def status(self):
            return {}

        def health(self):
            return {
                "healthy": True
            }

        def work_queue(self):
            return [
                {
                    "company": "Example Corp",
                    "priority": "High",
                }
            ]

        def run_sources(self, sources):
            return {}

    monkeypatch.setattr(
        "lead_engine.cli.create_application",
        lambda: FakeApplication(),
    )

    result = main(
        ["work-queue"]
    )

    assert result == 0

    output = json.loads(
        capsys.readouterr().out
    )

    assert len(output) == 1
    assert output[0]["company"] == "Example Corp"


def test_cli_import_json(
    monkeypatch,
    capsys,
    tmp_path,
):
    path = tmp_path / "leads.json"

    path.write_text(
        """
        [
            {
                "source": "test",
                "source_id": "cli-json-001",
                "url": "https://example.com/cli-json-001",
                "company": "CLI Corp",
                "signal": "remote developer",
                "evidence": "Remote developer opening."
            }
        ]
        """,
        encoding="utf-8",
    )

    class FakeApplication:
        def status(self):
            return {}

        def health(self):
            return {
                "healthy": True
            }

        def work_queue(self):
            return []

        def run_sources(self, sources):
            collected = list(
                sources[0].collect()
            )

            return {
                "source_count": len(sources),
                "lead_count": len(collected),
            }

    monkeypatch.setattr(
        "lead_engine.cli.create_application",
        lambda: FakeApplication(),
    )

    result = main(
        [
            "import-json",
            str(path),
        ]
    )

    assert result == 0

    output = json.loads(
        capsys.readouterr().out
    )

    assert output["source_count"] == 1
    assert output["lead_count"] == 1
