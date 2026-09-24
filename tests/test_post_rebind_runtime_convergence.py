from lead_engine.compute_fabric_telemetry import reconcile_post_rebind_runtime


def test_post_rebind_convergence_requires_selected_standby_to_be_observed():
    rebind = {"to_path_id": "path-standby", "next_generation": 9}
    observations = (
        {"fabric_path_id": "path-standby"},
        {"fabric_path_id": "path-standby"},
    )
    result = reconcile_post_rebind_runtime(rebind, observations)
    assert result == {
        "required": True,
        "converged": True,
        "expected_path_id": "path-standby",
        "observed_path_ids": ("path-standby",),
        "reason": "selected_standby_observed",
    }


def test_post_rebind_convergence_rejects_wrong_runtime_path():
    rebind = {"to_path_id": "path-standby", "next_generation": 9}
    observations = (
        {"fabric_path_id": "path-other"},
    )
    result = reconcile_post_rebind_runtime(rebind, observations)
    assert result["required"] is True
    assert result["converged"] is False
    assert result["expected_path_id"] == "path-standby"
    assert result["observed_path_ids"] == ("path-other",)
    assert result["reason"] == "selected_standby_not_observed"


def test_post_rebind_convergence_is_not_required_without_rebind():
    assert reconcile_post_rebind_runtime(None, ()) == {
        "required": False,
        "converged": True,
        "reason": "no_pending_rebind",
    }
