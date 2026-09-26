from __future__ import annotations

import pytest

from lead_engine.healing_closure import HealingClosureError, HealingClosureValidator
from lead_engine.healing_learning import HealingLearning


def test_closure_requires_authoritative_and_healing_verification():
    validator = HealingClosureValidator()
    with pytest.raises(HealingClosureError, match="authoritative verification"):
        validator.close(authoritative_verified=False, healing_verified=True, secondary_damage=False)
    with pytest.raises(HealingClosureError, match="secondary damage"):
        validator.close(authoritative_verified=True, healing_verified=True, secondary_damage=True)
    assert validator.close(authoritative_verified=True, healing_verified=True, secondary_damage=False)["state"] == "CLOSED"


def test_learning_keeps_experiments_out_of_production_until_proven(tmp_path):
    learning = HealingLearning(str(tmp_path / "learning.sqlite3"))
    learning.record("strategy-new", success=True, evidence={"sample": 1})
    assert learning.status("strategy-new")["state"] == "EXPERIMENTAL"
    learning.record("strategy-new", success=True, evidence={"sample": 2})
    learning.record("strategy-new", success=True, evidence={"sample": 3})
    assert learning.promote("strategy-new", known_good_available=True)["state"] == "PROMOTED"


def test_learning_regression_demotes_strategy_and_preserves_known_good(tmp_path):
    learning = HealingLearning(str(tmp_path / "learning.sqlite3"))
    for i in range(3):
        learning.record("candidate", success=True, evidence={"sample": i})
    learning.promote("candidate", known_good_available=True)
    learning.record("candidate", success=False, evidence={"sample": 4})
    learning.record("candidate", success=False, evidence={"sample": 5})
    assert learning.demote_on_regression("candidate")["state"] == "DEMOTED"
