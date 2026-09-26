"""Controlled fault-injection catalog for continuous autonomous recovery."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from .continuous_recovery import ContinuousRecoveryController

@dataclass(frozen=True)
class FaultScenario:
    name: str
    description: str
    expected_state: str

class HealingFaultInjection:
    SCENARIOS=(
        FaultScenario("isolated_failure","One exact path fails and recovers through authoritative gates.","RECOVERED"),
        FaultScenario("independent_failures","Independent paths remain concurrently schedulable.","RECOVERED"),
        FaultScenario("controller_restart","Durable unfinished work is reconciled after controller restart.","RETRY"),
        FaultScenario("verification_failure","Insufficient authoritative evidence remains retryable.","RETRY"),
        FaultScenario("protected_capacity","Unsafe recovery remains degraded rather than crossing a protected floor.","DEGRADED"),
    )
    def __init__(self,controller:ContinuousRecoveryController): self.controller=controller
    def scenario_catalog(self)->tuple[dict[str,str],...]:
        return tuple({"name":s.name,"description":s.description,"expected_state":s.expected_state} for s in self.SCENARIOS)
    def observe_failure(self,**kwargs:Any)->dict[str,Any]:
        return self.controller.observe(**kwargs)
    def run_with_evidence(self,*,evidence_provider,now=None):
        return self.controller.run_cycle(evidence_provider=evidence_provider,now=now)
