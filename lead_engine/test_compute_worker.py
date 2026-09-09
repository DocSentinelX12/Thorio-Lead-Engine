from lead_engine.compute_worker import ComputeWorkerClient, ComputeWorkerError, execute_compute_task


def test_execute_compute_task_prepares_leads_without_external_services():
    result = execute_compute_task({
        "kind": "lead_prepare",
        "leads": [{"company": "Example", "signal": "software engineer", "evidence": "hiring", "url": "https://example.com/job"}],
    })
    assert result["kind"] == "lead_prepare"
    assert result["count"] == 1
    assert result["leads"][0]["company"] == "Example"


def test_execute_compute_task_runs_advanced_discovery_agent():
    result = execute_compute_task({
        "kind": "agent_task",
        "agent": "engineering_demand_discovery",
        "payload": {"lead": {"fingerprint": "w1"}, "evidence_events": [{"source": "linkedin", "signal": "Hiring a backend engineer"}]},
    })
    assert result["kind"] == "agent_task"
    assert result["agent"] == "engineering_demand_discovery"
    assert result["result"]["matched_event_count"] == 1
    assert result["result"]["requires_verification"] is True


def test_execute_compute_task_runs_social_research_agent():
    result = execute_compute_task({
        "kind": "agent_task",
        "agent": "social_hiring_research",
        "payload": {"lead": {"fingerprint": "w2"}, "evidence_events": [{"source": "x", "signal": "We are hiring a CTO"}]},
    })
    assert result["result"]["matched_event_count"] == 1
    assert result["result"]["fabricated_fields"] == []
    assert result["result"]["verification_required"] is True


def test_execute_compute_task_rejects_unsupported_stateful_agent():
    try:
        execute_compute_task({"kind": "agent_task", "agent": "qualification_a", "payload": {}})
    except ComputeWorkerError as error:
        assert "not supported for stateless distributed agent" in str(error)
    else:
        raise AssertionError("stateful agent was incorrectly executed without durable state")


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
