from __future__ import annotations

import json

import pytest

from lead_engine.compute_fabric import ComputeExecutionRegistry
from lead_engine.nvidia_api_execution import NvidiaAPIExecutionConfig, NvidiaAPIExecutionProvider


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, *, headers, json, timeout):
        self.calls.append((url, headers, json, timeout))
        return FakeResponse({
            "id": "chatcmpl-test",
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        })


def test_nvidia_api_provider_executes_free_chat_endpoint():
    session = FakeSession()
    provider = NvidiaAPIExecutionProvider(
        NvidiaAPIExecutionConfig(
            api_key="nvapi-test",
            model="nvidia/test-model",
        ),
        session=session,
    )

    result = provider.execute([{"role": "user", "content": "hello"}])

    assert result["choices"][0]["message"]["content"] == "ok"
    assert session.calls[0][0] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert session.calls[0][1]["Authorization"] == "Bearer nvapi-test"
    assert session.calls[0][2]["model"] == "nvidia/test-model"


def test_nvidia_api_provider_is_api_gpu_only_and_never_claims_physical_capabilities():
    provider = NvidiaAPIExecutionProvider(
        NvidiaAPIExecutionConfig(api_key="nvapi-test", model="nvidia/test-model")
    )

    capabilities = provider.capabilities()

    assert capabilities.api_gpu_execution is True
    assert capabilities.cuda_execution is True
    assert capabilities.gpu_acquisition is False
    assert capabilities.networked_multi_node is False
    assert capabilities.arbitrary_process is False
    assert capabilities.physical_identity_attestation is False


def test_nvidia_api_provider_participates_in_shared_registry():
    session = FakeSession()
    provider = NvidiaAPIExecutionProvider(
        NvidiaAPIExecutionConfig(api_key="nvapi-test", model="nvidia/test-model"),
        session=session,
    )
    registry = ComputeExecutionRegistry()
    registry.register(provider)

    result = registry.execute(
        [{"role": "user", "content": "hello"}],
        required_capabilities={"api_gpu_execution": True, "cuda_execution": True},
    )

    assert result["provider_id"] == "nvidia-api"
    assert result["result"]["choices"][0]["message"]["content"] == "ok"


def test_nvidia_api_provider_rejects_non_list_data():
    provider = NvidiaAPIExecutionProvider(
        NvidiaAPIExecutionConfig(api_key="nvapi-test", model="nvidia/test-model")
    )

    with pytest.raises(TypeError, match="list"):
        provider.execute({"role": "user", "content": "hello"})
