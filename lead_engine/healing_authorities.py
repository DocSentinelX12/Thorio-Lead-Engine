"""Read-only integration gateway for authoritative GPU healing evidence.

This module coordinates existing authorities without creating a competing source
of physical, active-path, or recovery truth.
"""

from __future__ import annotations

from typing import Any

from .healing_dependencies import HealingDependencyAnalyzer
from .healing_evidence import HealingEvidenceGraph
from .healing_intelligence import HealingIntelligence

from .compute_inventory import ComputeInventory
from .recovery_orchestrator import RecoveryOrchestrator
from .healing_closure import HealingClosureValidator
from .healing_control_plane import ControlPlaneRecovery
from .healing_learning import HealingLearning
from .healing_experiments import HealingExperimentManager, HealingExperimentError
from .healing_workloads import WorkloadRecoveryPlanner
from .self_coordinating_fabric import FabricCoordinator, PlacementCandidate


class HealingAuthorityError(RuntimeError):
    """Raised when authoritative healing evidence cannot be established."""


class HealingAuthorityGateway:
    """Expose one exact-path evidence view across existing authorities."""

    AUTHORITIES = (
        "compute_inventory",
        "active_path_intelligence",
        "recovery_orchestrator",
    )

    def __init__(
        self,
        *,
        inventory: ComputeInventory,
        recovery_orchestrator: RecoveryOrchestrator,
        fabric_coordinator: FabricCoordinator | None = None,
    ) -> None:
        if recovery_orchestrator.inventory is not inventory:
            raise ValueError("recovery orchestrator must use the same compute inventory authority")
        if fabric_coordinator is None:
            raise ValueError("fabric coordinator is required for authoritative capacity state")
        self.inventory = inventory
        self.recovery_orchestrator = recovery_orchestrator
        self.fabric_coordinator = fabric_coordinator
        self.evidence_graph = HealingEvidenceGraph(inventory.db_path)
        self.dependencies = HealingDependencyAnalyzer(self.evidence_graph)
        self.intelligence = HealingIntelligence(
            graph=self.evidence_graph, dependencies=self.dependencies,
            db_path=inventory.db_path,
        )


    def recover_path(
        self,
        *,
        path_id: str,
        owner: str,
        physical_evidence: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        active_measurement: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        observed_at: float | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Delegate one exact-path recovery to the existing recovery authority."""
        snapshot = self.path(path_id)
        exact_path_id = snapshot["path_id"]
        self.recovery_orchestrator.discover(now=now)
        due = tuple(
            action
            for action in self.recovery_orchestrator.due(now=now)
            if str(action.get("path_id") or "") == exact_path_id
        )
        if not due:
            raise HealingAuthorityError(
                f"no due authoritative recovery action exists for path: {exact_path_id}"
            )
        if len(due) > 1:
            max_generation = max(int(action.get("generation") or 0) for action in due)
            due = tuple(
                action for action in due
                if int(action.get("generation") or 0) == max_generation
            )
        if len(due) != 1:
            raise HealingAuthorityError(
                f"ambiguous due recovery generation for exact path: {exact_path_id}"
            )

        result = self.recovery_orchestrator.execute(
            action_id=str(due[0]["action_id"]),
            owner=owner,
            physical_evidence=tuple(dict(item) for item in physical_evidence),
            active_measurement=dict(active_measurement) if active_measurement is not None else None,
            evidence=dict(evidence or {}),
            observed_at=observed_at,
            now=now,
        )
        result = dict(result)
        result["delegated_to"] = "recovery_orchestrator"
        result["authority_path_id"] = exact_path_id
        result["active_path"] = self.inventory.active_path_intelligence(path_id=exact_path_id)
        result["physical"] = next(
            row for row in self.inventory.physical_paths()
            if str(row.get("path_id") or "").strip() == exact_path_id
        )
        return result

    def capacity_state(self, *, path_id: str) -> dict[str, Any]:
        exact_path_id = str(path_id or "").strip()
        if not exact_path_id:
            raise HealingAuthorityError("fabric path id is required")
        physical = next(
            (dict(row) for row in self.inventory.physical_paths()
             if str(row.get("path_id") or "").strip() == exact_path_id),
            None,
        )
        if physical is None:
            raise HealingAuthorityError(f"unknown physical fabric path: {exact_path_id}")
        coordinator_state = self.fabric_coordinator.capacity_state()
        source_gpu = str(physical.get("source_gpu") or "").strip()
        destination_gpu = str(physical.get("destination_gpu") or "").strip()
        return {
            "path_id": exact_path_id,
            "redundant_capacity": bool(coordinator_state["recovery_capacity_available"]),
            "standby_capacity_available": bool(coordinator_state["standby_capacity_available"]),
            "available_nodes": int(coordinator_state["available_nodes"]),
            "active_allocations": int(coordinator_state["active_allocations"]),
            "protected_standby_nodes": tuple(coordinator_state["protected_standby_nodes"]),
        }

    def path(self, path_id: str) -> dict[str, Any]:
        exact_path_id = str(path_id or "").strip()
        if not exact_path_id:
            raise HealingAuthorityError("fabric path id is required")

        physical = next(
            (
                dict(row)
                for row in self.inventory.physical_paths()
                if str(row.get("path_id") or "").strip() == exact_path_id
            ),
            None,
        )
        if physical is None:
            raise HealingAuthorityError(f"unknown physical fabric path: {exact_path_id}")

        intelligence = self.inventory.active_path_intelligence(path_id=exact_path_id)
        recovery_actions = tuple(
            dict(row)
            for row in self.inventory.active_path_recovery_actions(path_id=exact_path_id)
        )

        evidence_generation = max(
            (int(action.get("generation") or 0) for action in recovery_actions),
            default=1,
        )
        physical_observed_at = float(
            physical.get("measurement_observed_at")
            or physical.get("updated_at")
            or physical.get("created_at")
            or 0.0
        )
        self.evidence_graph.record_observation(
            scope_id=exact_path_id,
            entity_type="fabric_path",
            entity_id=exact_path_id,
            source_authority="compute_inventory",
            generation=evidence_generation,
            confidence=1.0,
            observed_at=physical_observed_at,
            payload={**dict(physical), "evidence_generation": evidence_generation},
        )
        latest = dict(intelligence.get("latest") or {})
        if latest.get("observed_at") is not None:
            self.evidence_graph.record_observation(
                scope_id=exact_path_id,
                entity_type="active_path",
                entity_id=exact_path_id,
                source_authority="active_path_intelligence",
                generation=evidence_generation,
                confidence=1.0,
                observed_at=float(latest["observed_at"]),
                payload={**dict(intelligence), "evidence_generation": evidence_generation},
            )
        if latest.get("observed_at") is not None:
            self.evidence_graph.record_relationship(
                scope_id=exact_path_id, source_type="active_path", source_id=exact_path_id,
                relation="observes", target_type="fabric_path", target_id=exact_path_id,
                source_authority="active_path_intelligence", generation=evidence_generation, confidence=1.0,
                observed_at=float(latest["observed_at"]), payload={"fabric_path_id": exact_path_id, "evidence_generation": evidence_generation},
            )
        for action in recovery_actions:
            action_observed_at = float(action.get("updated_at") or action.get("created_at") or 0.0)
            action_id = str(action["action_id"])
            action_generation = int(action.get("generation") or 1)
            self.evidence_graph.record_observation(
                scope_id=exact_path_id,
                entity_type="recovery_action",
                entity_id=action_id,
                source_authority="recovery_orchestrator",
                generation=action_generation,
                confidence=1.0,
                observed_at=action_observed_at,
                payload=dict(action),
            )
            self.evidence_graph.record_relationship(
                scope_id=exact_path_id, source_type="recovery_action", source_id=action_id,
                relation="recovers", target_type="fabric_path", target_id=exact_path_id,
                source_authority="recovery_orchestrator", generation=action_generation,
                confidence=1.0, observed_at=action_observed_at,
                payload={"fabric_path_id": exact_path_id},
            )
        return {
            "path_id": exact_path_id,
            "physical": physical,
            "active_path": intelligence,
            "recovery_actions": recovery_actions,
            "evidence": self.evidence_graph.snapshot(exact_path_id),
            "authorities": self.AUTHORITIES,
        }


class HealingIntegrationFabric:
    """Cross-authority healing coordinator with explicit source-of-truth boundaries."""

    def __init__(
        self,
        *,
        inventory: ComputeInventory,
        recovery_orchestrator: RecoveryOrchestrator,
        fabric_coordinator: FabricCoordinator,
        workload_recovery: WorkloadRecoveryPlanner,
        control_plane: ControlPlaneRecovery,
        learning: HealingLearning,
        closure: HealingClosureValidator,
    ) -> None:
        self.inventory = inventory
        self.recovery_orchestrator = recovery_orchestrator
        self.fabric_coordinator = fabric_coordinator
        if getattr(self.fabric_coordinator, "physical_path_authority", None) is None:
            self.fabric_coordinator.bind_physical_path_authority(inventory)
        self.gateway = HealingAuthorityGateway(
            inventory=inventory,
            recovery_orchestrator=recovery_orchestrator,
            fabric_coordinator=fabric_coordinator,
        )
        self.workload_recovery = workload_recovery
        self.control_plane = control_plane
        self.learning = learning
        self.experiments = HealingExperimentManager(inventory.db_path)
        self.closure = closure
        self.evidence_graph = self.gateway.evidence_graph
        self.dependencies = self.gateway.dependencies
        self.intelligence = self.gateway.intelligence

    def path_evidence(self, path_id: str) -> dict[str, Any]:
        return self.gateway.path(path_id)

    def recover_path(self, **kwargs: Any) -> dict[str, Any]:
        return self.gateway.recover_path(**kwargs)

    def coordinate(self, candidates: tuple[PlacementCandidate, ...] | list[PlacementCandidate]) -> dict[str, Any]:
        """Delegate capacity and placement decisions to the global coordinator."""
        result = self.fabric_coordinator.coordinate(tuple(candidates))
        for allocation in result.get("allocations", ()):
            path_id = str(allocation["fabric_path_id"]).strip()
            workload_id = str(allocation["workload_id"]).strip()
            generation = int(allocation.get("generation") or 1)
            observed_at = float(allocation.get("updated") or 0.0)
            self.evidence_graph.record_relationship(
                scope_id=path_id, source_type="fabric_path", source_id=path_id,
                relation="supports", target_type="workload", target_id=workload_id,
                source_authority="self_coordinating_fabric", generation=generation,
                confidence=1.0, observed_at=observed_at,
                payload={"fabric_path_id": path_id, "allocation": dict(allocation)},
            )
            self.evidence_graph.record_relationship(
                scope_id=path_id, source_type="workload", source_id=workload_id,
                relation="allocated_to", target_type="node", target_id=str(allocation["node_id"]),
                source_authority="self_coordinating_fabric", generation=generation,
                confidence=1.0, observed_at=observed_at,
                payload={"fabric_path_id": path_id, "failure_domain": str(allocation["failure_domain"])},
            )
        return result

    def plan_migration(
        self,
        *,
        workload_id: str,
        execution_id: str,
        allocation: dict[str, Any],
        path_verified: bool,
    ) -> dict[str, Any]:
        """Translate an authoritative allocation into the existing workload recovery contract."""
        if not isinstance(allocation, dict):
            raise HealingAuthorityError("authoritative allocation record is required")
        required = ("node_id", "failure_domain", "fabric_path_id", "generation")
        if any(key not in allocation for key in required):
            raise HealingAuthorityError("incomplete authoritative allocation record")
        path_id = str(allocation.get("fabric_path_id") or "").strip()
        if not path_id:
            raise HealingAuthorityError("authoritative allocation is missing fabric path identity")
        physical = next(
            (
                row for row in self.inventory.verified_physical_paths()
                if str(row.get("path_id") or "").strip() == path_id
            ),
            None,
        )
        if physical is None or path_verified is not True:
            raise HealingAuthorityError("exact verified physical path is required for migration")
        destination = {
            "allocation_authoritative": True,
            "capacity_verified": True,
            "fabric_path_id": path_id,
            "fabric_path_verified": True,
            "node_id": str(allocation["node_id"]),
            "failure_domain": str(allocation["failure_domain"]),
            "generation": int(allocation["generation"]),
        }
        result = self.workload_recovery.plan_migration(
            workload_id=workload_id,
            execution_id=execution_id,
            destination=destination,
        )
        self.evidence_graph.record_relationship(
            scope_id=path_id, source_type="workload", source_id=workload_id,
            relation="migrates_over", target_type="fabric_path", target_id=path_id,
            source_authority="workload_recovery", generation=int(allocation["generation"]),
            confidence=1.0, observed_at=float(allocation.get("updated") or 0.0),
            payload={"execution_id": execution_id},
        )
        return result

    def takeover_control_plane(self, controller_id: str, *, generation: int) -> dict[str, Any]:
        return self.control_plane.takeover(controller_id, generation=generation)

    def reconcile_control_plane(
        self,
        controller_id: str,
        *,
        generation: int,
        authoritative_state: dict[str, Any],
    ) -> dict[str, Any]:
        return self.control_plane.reconcile(
            controller_id,
            generation=generation,
            authoritative_state=dict(authoritative_state),
        )

    def activate_control_plane(self, controller_id: str, *, generation: int) -> dict[str, Any]:
        return self.control_plane.activate(controller_id, generation=generation)

    def strategy_context(self, *, path_id: str, failure_domain: str = "", workload_class: str = "") -> str:
        """Return the durable experiment context for one exact physical path."""
        self.path_evidence(path_id)
        return self.experiments.context_key(
            fabric_path_id=str(path_id).strip(),
            failure_domain=failure_domain,
            workload_class=workload_class,
        )

    def select_recovery_strategy(
        self, *, path_id: str, known_good_strategy: str = "known_good_recovery",
        failure_domain: str = "", workload_class: str = "",
    ) -> dict[str, Any]:
        context = self.strategy_context(
            path_id=path_id, failure_domain=failure_domain, workload_class=workload_class
        )
        return self.experiments.select(
            context_key=context, known_good_strategy=known_good_strategy
        )

    def start_strategy_experiment(
        self, *, path_id: str, challenger_strategy: str,
        known_good_strategy: str = "known_good_recovery",
        failure_domain: str = "", workload_class: str = "",
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context = self.strategy_context(
            path_id=path_id, failure_domain=failure_domain, workload_class=workload_class
        )
        self.experiments.select(context_key=context, known_good_strategy=known_good_strategy)
        return self.experiments.start_challenger(
            context_key=context,
            challenger_strategy=challenger_strategy,
            provenance={
                "fabric_path_id": str(path_id),
                **dict(provenance or {}),
            },
        )

    def evaluate_strategy_experiment(self, *, experiment_id: str) -> dict[str, Any]:
        return self.experiments.evaluate(experiment_id=experiment_id)

    def promote_strategy_experiment(self, *, experiment_id: str) -> dict[str, Any]:
        return self.experiments.promote(experiment_id=experiment_id)

    def rollback_strategy_experiment(self, *, experiment_id: str, reason: str) -> dict[str, Any]:
        return self.experiments.rollback(experiment_id=experiment_id, reason=reason)

    def close_recovery(
        self,
        *,
        path_id: str,
        authoritative_verified: bool,
        healing_verified: bool,
        secondary_damage: bool,
        strategy: str,
        success: bool,
        evidence: dict[str, Any],
        promote: bool = False,
    ) -> dict[str, Any]:
        """Close only after both authorities agree, then record the verified outcome."""
        self.path_evidence(path_id)
        closure = self.closure.close(
            authoritative_verified=authoritative_verified,
            healing_verified=healing_verified,
            secondary_damage=secondary_damage,
        )
        learning = self.learning.record(
            strategy,
            success=success,
            evidence={
                "path_id": path_id,
                "closure": closure,
                **dict(evidence),
            },
        )
        if promote:
            if not success:
                raise HealingAuthorityError("failed recovery cannot promote a strategy")
            learning = self.learning.promote(strategy, known_good_available=True)
        observed_at = float(evidence.get("observed_at") or 0.0)
        experiment_id = str(evidence.get("experiment_id") or "").strip()
        if experiment_id:
            try:
                self.experiments.record_outcome(
                    experiment_id=experiment_id,
                    strategy=strategy,
                    success=bool(success),
                    safety_violation=bool(secondary_damage),
                    reversible=bool(evidence.get("reversible", True)),
                    evidence={
                        "path_id": path_id,
                        "closure_state": closure["state"],
                        "authoritative_verified": bool(authoritative_verified),
                        "healing_verified": bool(healing_verified),
                        **dict(evidence),
                    },
                    observed_at=observed_at,
                )
            except HealingExperimentError as exc:
                raise HealingAuthorityError(str(exc)) from exc
        self.evidence_graph.record_observation(
            scope_id=path_id, entity_type="healing_closure",
            entity_id=f"{path_id}:{strategy}", source_authority="healing_closure",
            generation=1, confidence=1.0 if success else 0.0, observed_at=observed_at,
            payload={"path_id": path_id, "strategy": strategy, "success": success, "closure": closure},
        )
        return {"state": closure["state"], "path_id": path_id, "learning": learning}
