from .agent_registry import ALL_AGENT_ROLES
from .agent_specializations import get_specialization, specialization_registry


def test_every_registered_agent_has_one_professional_specialization():
    registry = specialization_registry()
    assert set(registry) == {role.name for role in ALL_AGENT_ROLES}
    for role in ALL_AGENT_ROLES:
        specialist = registry[role.name]
        assert specialist.agent == role.name
        assert specialist.mission
        assert specialist.responsibilities
        assert specialist.outputs
        assert specialist.forbidden_actions


def test_specializations_are_task_specific():
    assert "qualification decisions" in get_specialization("x_signal").forbidden_actions
    assert "current need" in get_specialization("qualification_a").responsibilities
    assert "verify consent evidence" in get_specialization("paxus_research").responsibilities
    assert "merging distinct opportunities" in get_specialization("duplicate_resolution").forbidden_actions
    assert "hiding failures" in get_specialization("monitoring").forbidden_actions


def test_unknown_agent_cannot_receive_a_specialization():
    try:
        get_specialization("not_a_real_agent")
    except ValueError as exc:
        assert "No professional specialization" in str(exc)
    else:
        raise AssertionError("Unknown agents must not receive an implicit specialization")
