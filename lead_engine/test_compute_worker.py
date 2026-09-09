from lead_engine.compute_worker import ComputeWorkerClient, ComputeWorkerError, execute_compute_task


def test_execute_compute_task_prepares_leads_without_external_services():
    result = execute_compute_task({
        "kind": "lead_prepare",
        "leads": [{"company": "Example", "signal": "software engineer", "evidence": "hiring", "url": "https://example.com/job"}],
    })
    assert result["kind"] == "lead_prepare"
    assert result["count"] == 1
    assert result["leads"][0]["company"] == "Example"


def test_execute_compute_task_rejects_unknown_kind():
    try:
        execute_compute_task({"kind": "unknown"})
    except ComputeWorkerError as error:
        assert "unsupported compute task kind" in str(error)
    else:
        raise AssertionError("unknown compute task was accepted")


def test_worker_client_rejects_invalid_configuration():
    for url in ("", "example.com"):
        try:
            ComputeWorkerClient(url, "token", "worker")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid coordinator URL was accepted")
