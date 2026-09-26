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
