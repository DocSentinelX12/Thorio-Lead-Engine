from __future__ import annotations

import pytest

from lead_engine.healing_control_plane import ControlPlaneRecovery, ControlPlaneRecoveryError


def test_control_plane_takeover_fences_stale_controller(tmp_path):
    cp = ControlPlaneRecovery(str(tmp_path / "control.sqlite3"))
    cp.register("controller-a", generation=1)
    takeover = cp.takeover("controller-b", generation=2)
    assert takeover["state"] == "FENCED_PENDING_RECONCILIATION"
    assert takeover["fencing_token"] == 2
    assert cp.is_fenced("controller-a") is True


def test_control_plane_requires_reconciliation_before_return_to_service(tmp_path):
    cp = ControlPlaneRecovery(str(tmp_path / "control.sqlite3"))
    cp.register("controller-a", generation=1)
    cp.takeover("controller-b", generation=2)
    with pytest.raises(ControlPlaneRecoveryError, match="reconciliation"):
        cp.activate("controller-b", generation=2)
    cp.reconcile("controller-b", generation=2, authoritative_state={"allocations": 2})
    assert cp.activate("controller-b", generation=2)["state"] == "ACTIVE"


def test_control_plane_partition_blocks_dual_authority(tmp_path):
    cp = ControlPlaneRecovery(str(tmp_path / "control.sqlite3"))
    cp.register("controller-a", generation=1)
    cp.mark_partition()
    with pytest.raises(ControlPlaneRecoveryError, match="partition"):
        cp.takeover("controller-b", generation=2)


def test_control_plane_recovery_uses_replicated_fencing_and_restores_conservatively(tmp_path):
    from lead_engine.healing_replication import ReplicatedHealingState

    paths = tuple(str(tmp_path / f"replica-{index}.sqlite3") for index in range(3))
    replicated = ReplicatedHealingState(paths)
    control_path = str(tmp_path / "control.sqlite3")
    cp = ControlPlaneRecovery(control_path, replicated_state=replicated)

    first = cp.register("controller-a", generation=1)
    assert first["fencing_token"] == replicated.leadership()["fencing_token"]
    cp.takeover("controller-b", generation=2)
    with pytest.raises(ControlPlaneRecoveryError, match="reconciliation"):
        cp.activate("controller-b", generation=2)

    cp.reconcile("controller-b", generation=2, authoritative_state={"allocations": 4})
    cp.activate("controller-b", generation=2)

    restored = ControlPlaneRecovery(str(tmp_path / "restored-control.sqlite3"), replicated_state=replicated)
    recovered = restored.restore_from_replicated_state()
    assert recovered["controller_id"] == "controller-b"
    assert recovered["state"] == "FENCED_PENDING_RECONCILIATION"
    assert recovered["reconciled"] == 0
    with pytest.raises(ControlPlaneRecoveryError, match="reconciliation"):
        restored.activate("controller-b", generation=2)
