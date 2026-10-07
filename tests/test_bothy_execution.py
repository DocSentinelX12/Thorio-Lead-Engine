import pytest

from lead_engine.bothy_execution import BothyExecutionConfig, BothyExecutionProvider
from lead_engine.compute_fabric import ComputeExecutionRegistry


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
        return FakeResponse({"state": "ready"})

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse({"choices": [{"message": {"content": "ok"}}]})


def test_bothy_requires_share_key_and_valid_url():
    with pytest.raises(ValueError, match="share_key"):
        BothyExecutionConfig(base_url="http://127.0.0.1:11223", share_key="")

    with pytest.raises(ValueError, match="http"):
        BothyExecutionConfig(base_url="not-a-url", share_key="test")


def test_bothy_declares_remote_community_inference_without_physical_or_model_parallel_claims():
    provider = BothyExecutionProvider(
        BothyExecutionConfig(base_url="http://127.0.0.1:11223", share_key="test"),
    )
    capabilities = provider.capabilities().to_dict()
    assert capabilities["community_inference"] is True
    assert capabilities["openai_compatible_api"] is True
    assert capabilities["peer_network"] is True
    assert capabilities["api_gpu_execution"] is True
    assert capabilities["networked_multi_node"] is False
    assert capabilities["multi_node"] is False
    assert capabilities["cuda_execution"] is False
    assert capabilities["physical_identity_attestation"] is False


def test_bothy_health_and_chat_execution_use_client_endpoint():
    session = FakeSession()
    provider = BothyExecutionProvider(
        BothyExecutionConfig(base_url="http://127.0.0.1:11223", share_key="test"),
        session=session,
    )

    assert provider.health()["state"] == "available"
    result = provider.execute([{
        "model": "llama3.1:8b",
        "messages": [{"role": "user", "content": "hello"}],
    }])

    assert result["choices"][0]["message"]["content"] == "ok"
    assert session.gets[0][0].endswith("/bothy/healthz")
    assert session.posts[0][0].endswith("/v1/chat/completions")
    assert session.posts[0][1]["headers"]["Authorization"] == "Bearer test"


def test_bothy_can_be_selected_by_shared_registry():
    provider = BothyExecutionProvider(
        BothyExecutionConfig(base_url="http://127.0.0.1:11223", share_key="test"),
        session=FakeSession(),
    )
    registry = ComputeExecutionRegistry()
    registry.register(provider)

    result = registry.execute(
        [{"model": "llama3.1:8b", "messages": [{"role": "user", "content": "hello"}]}],
        required_capabilities={
            "community_inference": True,
            "openai_compatible_api": True,
            "peer_network": True,
        },
    )
    assert result["provider_id"] == "bothy"


def test_bothy_is_not_selected_for_cuda_or_model_parallel_requirements():
    provider = BothyExecutionProvider(
        BothyExecutionConfig(base_url="http://127.0.0.1:11223", share_key="test"),
        session=FakeSession(),
    )
    registry = ComputeExecutionRegistry()
    registry.register(provider)

    with pytest.raises(RuntimeError, match="no registered execution provider"):
        registry.execute(
            [{"model": "llama3.1:8b", "messages": [{"role": "user", "content": "hello"}]}],
            required_capabilities={"cuda_execution": True},
        )
    with pytest.raises(RuntimeError, match="no registered execution provider"):
        registry.execute(
            [{"model": "llama3.1:8b", "messages": [{"role": "user", "content": "hello"}]}],
            required_capabilities={"networked_multi_node": True},
        )
