import pytest

from lead_engine.openhydra_execution import (
    OpenHydraExecutionConfig,
    OpenHydraExecutionProvider,
)


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.posts = []
        self.gets = []

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return FakeResponse({"ok": True})

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse({"id": "chatcmpl-test", "choices": [{"message": {"content": "ok"}}]})


def test_openhydra_requires_local_or_explicit_http_gateway():
    with pytest.raises(ValueError, match="http"):
        OpenHydraExecutionConfig(base_url="not-a-url")


def test_openhydra_declares_community_inference_without_claiming_cuda_or_physical_inventory():
    provider = OpenHydraExecutionProvider(
        OpenHydraExecutionConfig(base_url="http://127.0.0.1:16527"),
    )
    capabilities = provider.capabilities().to_dict()
    assert capabilities["community_inference"] is True
    assert capabilities["openai_compatible_api"] is True
    assert capabilities["peer_network"] is True
    assert capabilities["api_gpu_execution"] is True
    assert capabilities["gpu_acquisition"] is False
    assert capabilities["cuda_execution"] is False
    assert capabilities["physical_identity_attestation"] is False


def test_openhydra_health_and_chat_execution_use_openai_gateway():
    session = FakeSession()
    provider = OpenHydraExecutionProvider(
        OpenHydraExecutionConfig(base_url="http://127.0.0.1:16527"),
        session=session,
    )

    assert provider.health()["state"] == "available"
    result = provider.execute([{
        "model": "llama3.2",
        "messages": [{"role": "user", "content": "hello"}],
    }])

    assert result["choices"][0]["message"]["content"] == "ok"
    assert session.gets[0][0].endswith("/health")
    assert session.posts[0][0].endswith("/v1/chat/completions")
    assert session.posts[0][1]["json"]["model"] == "llama3.2"


def test_openhydra_can_be_selected_by_shared_capability_registry():
    from lead_engine.compute_fabric import ComputeExecutionRegistry

    provider = OpenHydraExecutionProvider(
        OpenHydraExecutionConfig(base_url="http://127.0.0.1:16527"),
        session=FakeSession(),
    )
    registry = ComputeExecutionRegistry()
    registry.register(provider)

    result = registry.execute(
        [{
            "model": "llama3.2",
            "messages": [{"role": "user", "content": "hello"}],
        }],
        required_capabilities={
            "community_inference": True,
            "openai_compatible_api": True,
            "peer_network": True,
        },
    )

    assert result["provider_id"] == "openhydra"
    assert result["result"]["choices"][0]["message"]["content"] == "ok"


def test_openhydra_is_not_selected_for_physical_cuda_or_nccL_requirements():
    from lead_engine.compute_fabric import ComputeExecutionRegistry

    provider = OpenHydraExecutionProvider(
        OpenHydraExecutionConfig(base_url="http://127.0.0.1:16527"),
        session=FakeSession(),
    )
    registry = ComputeExecutionRegistry()
    registry.register(provider)

    with pytest.raises(RuntimeError, match="no registered execution provider"):
        registry.execute(
            [{"model": "llama3.2", "messages": [{"role": "user", "content": "hello"}]}],
            required_capabilities={"cuda_execution": True},
        )
