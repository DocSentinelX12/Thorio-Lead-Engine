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


class FakeGpuApiClient:
    def __init__(self):
        self.calls = []

    def gpu_api_execute(self, data, required_capabilities=None):
        self.calls.append((data, required_capabilities))
        return {
            "provider_id": "huggingface-zerogpu",
            "result": {"checksum": 13.0, "cuda": True},
            "capabilities": {"api_gpu_execution": True, "cuda_execution": True},
        }


def test_execute_compute_task_routes_gpu_api_through_coordinator_client():
    client = FakeGpuApiClient()
    result = execute_compute_task({
        "kind": "gpu_api",
        "data": ["probe"],
        "required_capabilities": {"api_gpu_execution": True, "cuda_execution": True},
    }, client)
    assert result["kind"] == "gpu_api"
    assert result["provider_id"] == "huggingface-zerogpu"
    assert result["result"] == {"checksum": 13.0, "cuda": True}
    assert client.calls == [
        (["probe"], {"api_gpu_execution": True, "cuda_execution": True}),
    ]


def test_execute_compute_task_rejects_gpu_api_without_coordinator_client():
    try:
        execute_compute_task({"kind": "gpu_api", "data": ["probe"]})
    except ComputeWorkerError as error:
        assert "requires a coordinator client" in str(error)
    else:
        raise AssertionError("GPU API execution bypassed the coordinator")
