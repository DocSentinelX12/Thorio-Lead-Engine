import time

from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_provider import ProviderResourceSnapshot
from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState


def _snapshot(*, gpus=(), ephemeral=False, expires_at=None):
    return ProviderResourceSnapshot(
        provider_id="provider-a",
        domain_id="domain-a",
        observed_at=time.time(),
        nodes=(NodeResource(
            node_id="node-1",
            architecture="x86_64",
            cpu=CpuResource("node-1", 16, 64 * 1024**3),
            gpus=tuple(gpus),
        ),),
        ephemeral=ephemeral,
        expires_at=expires_at,
        evidence={"probe": "test"},
    )


def _gpu(gpu_id, uuid):
    return GpuResource(
        node_id="node-1",
        gpu_id=gpu_id,
        gpu_uuid=uuid,
        model="NVIDIA Test GPU",
        vram_bytes=24 * 1024**3,
    )


def test_multiple_gpus_are_independently_addressable(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    result = inventory.observe(_snapshot(gpus=(_gpu("0", "uuid-0"), _gpu("1", "uuid-1"))))
    assert result["observed_gpus"] == 2
    resources = [item for item in inventory.resources() if item["resource_type"] == "gpu"]
    assert {item["resource_key"] for item in resources} == {
        "provider-a/domain-a/node-1/gpu/uuid-0",
        "provider-a/domain-a/node-1/gpu/uuid-1",
    }


def test_missing_gpu_uuid_is_not_fabricated(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot(gpus=(_gpu("0", ""),)))
    gpu = next(item for item in inventory.resources() if item["resource_type"] == "gpu")
    assert gpu["identity_key"] == "node-1/0"
    assert '"gpu_uuid": ""' in gpu["payload_json"]


def test_provider_disappearance_preserves_history(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot(gpus=(_gpu("0", "uuid-0"),)))
    changed = inventory.mark_provider_missing("provider-a", "domain-a")
    assert changed == 2
    assert len(inventory.resources()) == 2
    assert all(item["state"] == ResourceState.DEGRADED.value for item in inventory.resources())


def test_ephemeral_expiration_removes_eligibility_but_keeps_identity(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot(gpus=(_gpu("0", "uuid-0"),), ephemeral=True, expires_at=time.time() - 1))
    assert inventory.eligible() == []
    assert inventory.get("provider-a/domain-a/node-1/gpu/uuid-0") is not None


def test_quarantined_resource_is_not_eligible(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot(gpus=(_gpu("0", "uuid-0"),)))
    key = "provider-a/domain-a/node-1/gpu/uuid-0"
    assert inventory.mark_state(key, ResourceState.QUARANTINED)
    assert inventory.eligible() == []


def test_resource_state_evidence_is_retained(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot(gpus=(_gpu("0", "uuid-0"),)))
    gpu = inventory.get("provider-a/domain-a/node-1/gpu/uuid-0")
    assert gpu is not None
    assert '"probe": "test"' in gpu["evidence_json"]
