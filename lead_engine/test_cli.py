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
            return {"healthy": True}

        def work_queue(self):
            return [
                {
                    "company": "Example Corp",
                    "priority": "High",
                }
            ]

    monkeypatch.setattr(
        "lead_engine.cli.create_application",
        lambda: FakeApplication(),
    )

    result = main(["work-queue"])

    assert result == 0

    output = json.loads(
        capsys.readouterr().out
    )

    assert len(output) == 1
    assert output[0]["company"] == "Example Corp"
