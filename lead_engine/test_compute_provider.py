import time

import pytest

from lead_engine.compute_provider import ComputeProvider, ProviderResourceSnapshot
from lead_engine.compute_resources import CpuResource, NodeResource


class FakeProvider(ComputeProvider):
    provider_id = "test-provider"

    def __init__(self, snapshot):
        self.snapshot = snapshot

    def discover(self):
        return self.snapshot


def _snapshot(ephemeral=False, expires_at=None):
    return ProviderResourceSnapshot(
        provider_id="test-provider",
        domain_id="domain-a",
        observed_at=time.time(),
        nodes=(NodeResource(
            node_id="node-1",
            architecture="x86_64",
            cpu=CpuResource("node-1", 8, 16 * 1024**3),
        ),),
        ephemeral=ephemeral,
        expires_at=expires_at,
        evidence={"source": "test"},
    )


def test_provider_requires_nonempty_identity():
    with pytest.raises(ValueError):
        ProviderResourceSnapshot("", "domain-a", time.time(), (), False, None)


def test_ephemeral_snapshot_requires_expiration():
    with pytest.raises(ValueError):
        _snapshot(ephemeral=True)


def test_provider_adapter_returns_normalized_snapshot():
    snapshot = _snapshot()
    provider = FakeProvider(snapshot)
    assert provider.discover().provider_id == "test-provider"
    assert provider.discover().nodes[0].cpu.cpu_count == 8
