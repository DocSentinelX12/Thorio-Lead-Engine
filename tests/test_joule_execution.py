import pytest

from lead_engine.compute_fabric import ComputeExecutionRegistry
from lead_engine.joule_execution import JouleExecutionConfig, JouleExecutionProvider


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
        return FakeResponse({"status": "ok"})

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse({"choices": [{"message": {"content": "ok"}}]})


def test_joule_requires_api_key_and_valid_url():
    with pytest.raises(ValueError, match="api_key"):
        JouleExecutionConfig(base_url="http://127.0.0.1:7700", api_key="")

    with pytest.raises(ValueError, match="http"):
        JouleExecutionConfig(base_url="not-a-url", api_key="joule_test")


def test_joule_declares_distributed_community_inference_without_physical_claims():
    provider = JouleExecutionProvider(
        JouleExecutionConfig(base_url="http://127.0.0.1:7700", api_key="joule_test"),
    )
    capabilities = provider.capabilities().to_dict()
    assert capabilities["community_inference"] is True
    assert capabilities["networked_multi_node"] is True
    assert capabilities["multi_node"] is True
    assert capabilities["openai_compatible_api"] is True
    assert capabilities["api_gpu_execution"] is True
    assert capabilities["gpu_acquisition"] is False
    assert capabilities["cuda_execution"] is False
    assert capabilities["physical_identity_attestation"] is False


def test_joule_health_and_chat_execution_use_gateway():
    session = FakeSession()
    provider = JouleExecutionProvider(
        JouleExecutionConfig(base_url="http://127.0.0.1:7700", api_key="joule_test"),
        session=session,
    )

    assert provider.health()["state"] == "available"
    result = provider.execute([{
        "model": "kimi-open",
        "messages": [{"role": "user", "content": "hello"}],
    }])

    assert result["choices"][0]["message"]["content"] == "ok"
    assert session.gets[0][0].endswith("/healthz")
    assert session.posts[0][0].endswith("/v1/chat/completions")
    assert session.posts[0][1]["headers"]["Authorization"] == "Bearer joule_test"


def test_joule_can_be_selected_by_shared_registry():
    provider = JouleExecutionProvider(
        JouleExecutionConfig(base_url="http://127.0.0.1:7700", api_key="joule_test"),
        session=FakeSession(),
    )
    registry = ComputeExecutionRegistry()
    registry.register(provider)

    result = registry.execute(
        [{"model": "kimi-open", "messages": [{"role": "user", "content": "hello"}]}],
        required_capabilities={
            "community_inference": True,
            "openai_compatible_api": True,
            "networked_multi_node": True,
        },
    )
    assert result["provider_id"] == "joule"


def test_joule_is_not_selected_for_physical_cuda_or_ssh_requirements():
    provider = JouleExecutionProvider(
        JouleExecutionConfig(base_url="http://127.0.0.1:7700", api_key="joule_test"),
        session=FakeSession(),
    )
    registry = ComputeExecutionRegistry()
    registry.register(provider)

    with pytest.raises(RuntimeError, match="no registered execution provider"):
        registry.execute(
            [{"model": "kimi-open", "messages": [{"role": "user", "content": "hello"}]}],
            required_capabilities={"cuda_execution": True},
        )
