import time

from lead_engine.compute_inventory import ComputeInventory
from lead_engine.compute_provider import ProviderResourceSnapshot
from lead_engine.compute_resources import CpuResource, GpuResource, NodeResource, ResourceState


def _snapshot(*, gpus=(), ephemeral=False, expires_at=None, authentication_state="authenticated"):
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
        authentication_state=authentication_state,
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


def test_one_gpu_failure_does_not_quarantine_unrelated_gpu(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot(gpus=(_gpu("0", "uuid-0"), _gpu("1", "uuid-1"))))
    failed_key = "provider-a/domain-a/node-1/gpu/uuid-0"
    healthy_key = "provider-a/domain-a/node-1/gpu/uuid-1"
    assert inventory.mark_state(failed_key, ResourceState.QUARANTINED)
    assert inventory.get(failed_key)["state"] == ResourceState.QUARANTINED.value
    assert inventory.get(healthy_key)["state"] != ResourceState.QUARANTINED.value


def test_provider_authentication_state_is_retained(tmp_path):
    inventory = ComputeInventory(str(tmp_path / "inventory.sqlite3"))
    inventory.observe(_snapshot(authentication_state="reauth_required"))
    resource = inventory.get("provider-a/domain-a/node-1/cpu")
    assert resource is not None
    assert resource["authentication_state"] == "reauth_required"


def test_existing_inventory_schema_is_migrated(tmp_path):
    db_path = tmp_path / "inventory.sqlite3"
    import sqlite3

    with sqlite3.connect(db_path) as connection:
        connection.execute("""CREATE TABLE compute_resource_inventory (
            resource_key TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL,
            domain_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            gpu_id TEXT,
            identity_key TEXT,
            resource_type TEXT NOT NULL,
            state TEXT NOT NULL,
            observed_at REAL NOT NULL,
            expires_at REAL,
            ephemeral INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            first_seen_at REAL NOT NULL,
            last_seen_at REAL NOT NULL)""")
        connection.commit()

    inventory = ComputeInventory(str(db_path))
    columns = {row[1] for row in sqlite3.connect(db_path).execute("PRAGMA table_info(compute_resource_inventory)")}
    assert "authentication_state" in columns
