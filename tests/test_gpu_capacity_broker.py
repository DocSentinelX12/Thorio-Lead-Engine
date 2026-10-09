import os

from lead_engine.gpu_capacity_broker import provider_readiness_from_environment


def test_provider_readiness_requires_complete_kaggle_inputs(monkeypatch):
    for name in (
        "THORIO_KAGGLE_ENABLED",
        "THORIO_KAGGLE_USERNAME",
        "KAGGLE_API_TOKEN",
        "GITHUB_RUNNER_JIT_TOKEN",
        "THORIO_GITHUB_RUNNER_JIT_TOKEN",
        "THORIO_COMPUTE_COORDINATOR_URL",
        "THORIO_COMPUTE_AUTH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("THORIO_KAGGLE_ENABLED", "1")
    state = provider_readiness_from_environment()["kaggle"]

    assert state["enabled"] is True
    assert state["ready"] is False
    assert set(state["missing"]) == {
        "THORIO_KAGGLE_USERNAME",
        "KAGGLE_API_TOKEN",
        "GITHUB_RUNNER_JIT_TOKEN",
        "THORIO_COMPUTE_COORDINATOR_URL",
        "THORIO_COMPUTE_AUTH_TOKEN",
    }


def test_disabled_providers_are_not_marked_missing(monkeypatch):
    for name in (
        "THORIO_KAGGLE_ENABLED",
        "THORIO_KAGGLE_USERNAME",
        "KAGGLE_API_TOKEN",
        "GITHUB_RUNNER_JIT_TOKEN",
        "THORIO_GITHUB_RUNNER_JIT_TOKEN",
        "THORIO_COMPUTE_COORDINATOR_URL",
        "THORIO_COMPUTE_AUTH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)

    readiness = provider_readiness_from_environment()

    assert readiness["kaggle"] == {"enabled": False, "ready": False, "missing": ()}


def test_ready_kaggle_requires_all_inputs(monkeypatch):
    monkeypatch.setenv("THORIO_KAGGLE_ENABLED", "1")
    monkeypatch.setenv("THORIO_KAGGLE_USERNAME", "example")
    monkeypatch.setenv("KAGGLE_API_TOKEN", "token")
    monkeypatch.setenv("GITHUB_RUNNER_JIT_TOKEN", "runner-management-token")
    monkeypatch.setenv("THORIO_COMPUTE_COORDINATOR_URL", "https://example.invalid")
    monkeypatch.setenv("THORIO_COMPUTE_AUTH_TOKEN", "coordinator-token")

    state = provider_readiness_from_environment()["kaggle"]

    assert state["enabled"] is True
    assert state["ready"] is True
    assert state["missing"] == ()
