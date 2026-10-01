from lead_engine.execution_recovery import CheckpointManifest, ExecutionRecoveryPlanner


def _checkpoint():
    return CheckpointManifest.create(
        workload_id="w", execution_plan_id="p", checkpoint_id="c1",
        completed_unit_ids=("u1", "u2"), partition_state=(("p0","n0"), ("p1","n1"))
    )


def test_checkpoint_digest_is_deterministic():
    assert _checkpoint().digest == _checkpoint().digest
    assert len(_checkpoint().digest) == 64


def test_elastic_recovery_replaces_unavailable_members():
    result = ExecutionRecoveryPlanner().decide(
        checkpoint=_checkpoint(), active_node_ids=("n0", "n1"),
        unavailable_node_ids=("n1",), candidate_node_ids=("n2","n3"),
        elastic=True,
    )
    assert result.action == "restore_and_rebalance"
    assert result.replacement_node_ids == ("n2",)


def test_non_elastic_recovery_does_not_invent_replacements():
    result = ExecutionRecoveryPlanner().decide(
        checkpoint=_checkpoint(), active_node_ids=("n0", "n1"),
        unavailable_node_ids=("n1",), candidate_node_ids=("n2",),
        elastic=False,
    )
    assert result.action == "restore"
    assert result.replacement_node_ids == ()


def test_elastic_recovery_returns_deterministic_rank_reassignments():
    result = ExecutionRecoveryPlanner().decide(
        checkpoint=_checkpoint(),
        active_node_ids=("n0", "n1"),
        unavailable_node_ids=("n1",),
        candidate_node_ids=("n2", "n3"),
        elastic=True,
    )
    assert result.rank_reassignments == (("n1", "n2"),)
    assert result.checkpoint_digest == _checkpoint().digest
