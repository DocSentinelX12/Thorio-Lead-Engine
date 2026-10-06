import pytest

from lead_engine.zerogpu_execution import (
    ZeroGPUExecutionConfig,
    ZeroGPUExecutionProvider,
)


class FakeResponse:
    def __init__(self, payload=None, lines=(), status_code=200):
        self._payload = payload
        self._lines = list(lines)
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status={self.status_code}")

    def json(self):
        return self._payload

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)


class FakeSession:
    def __init__(self):
        self.posts = []
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return FakeResponse({"event_id": "evt-1"})

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        return FakeResponse(lines=(
            "event: complete",
            'data: {"checksum": 13.0, "cuda": true}',
        ))


def test_zerogpu_config_rejects_non_huggingface_endpoint():
    with pytest.raises(ValueError, match="Hugging Face Space"):
        ZeroGPUExecutionConfig(
            space_url="https://example.com",
            api_name="/predict",
            token="hf-test",
        )


def test_zerogpu_never_claims_networked_nccl_or_arbitrary_process():
    provider = ZeroGPUExecutionProvider(
        ZeroGPUExecutionConfig(
            space_url="https://example.hf.space",
            api_name="/predict",
            token="hf-test",
        )
    )
    capabilities = provider.capabilities().to_dict()
    assert capabilities["api_gpu_execution"] is True
    assert capabilities["cuda_execution"] is True
    assert capabilities["networked_multi_node"] is False
    assert capabilities["nccl_execution"] is False
    assert capabilities["arbitrary_process"] is False


def test_zerogpu_execution_uses_gradio_queue_and_returns_completion(monkeypatch):
    provider = ZeroGPUExecutionProvider(
        ZeroGPUExecutionConfig(
            space_url="https://example.hf.space",
            api_name="/predict",
            token="hf-test",
        ),
        session=FakeSession(),
    )
    monkeypatch.setattr(provider, "_quota", lambda: {"remaining_seconds": 60.0})
    result = provider.execute(["probe"])
    assert result == {"checksum": 13.0, "cuda": True}
    assert provider._session.posts[0][0].endswith("/gradio_api/call/predict")


def test_zerogpu_participates_in_shared_capability_execution_registry():
    from lead_engine.compute_fabric import ComputeExecutionRegistry

    provider = ZeroGPUExecutionProvider(
        ZeroGPUExecutionConfig(
            space_url="https://example.hf.space",
            api_name="/predict",
            token="hf-test",
        ),
        session=FakeSession(),
    )
    registry = ComputeExecutionRegistry()
    registry.register(provider)
    result = registry.execute(
        ["probe"],
        required_capabilities={"api_gpu_execution": True, "cuda_execution": True},
    )
    assert result["provider_id"] == "huggingface-zerogpu"
    assert result["result"] == {"checksum": 13.0, "cuda": True}


def test_shared_execution_registry_does_not_use_zerogpu_for_physical_requirements():
    from lead_engine.compute_fabric import ComputeExecutionRegistry

    provider = ZeroGPUExecutionProvider(
        ZeroGPUExecutionConfig(
            space_url="https://example.hf.space",
            api_name="/predict",
            token="hf-test",
        ),
        session=FakeSession(),
    )
    registry = ComputeExecutionRegistry()
    registry.register(provider)

    with pytest.raises(RuntimeError, match="no registered execution provider"):
        registry.execute(
            ["probe"],
            required_capabilities={"networked_multi_node": True},
        )
