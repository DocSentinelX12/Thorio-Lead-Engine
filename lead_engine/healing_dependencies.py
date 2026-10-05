"""Dependency and failure correlation over durable healing evidence."""

from __future__ import annotations

from collections import deque
from typing import Any

from .healing_evidence import HealingEvidenceGraph


class RecoveryDependencyConflict(RuntimeError):
    pass


class HealingDependencyAnalyzer:
    def __init__(self, graph: HealingEvidenceGraph):
        self.graph = graph

    def impact(self, scope_id: str) -> dict[str, Any]:
        snapshot = self.graph.snapshot(scope_id)
        observations = snapshot["observations"]
        relationships = snapshot["relationships"]
        seeds = {
            (row["entity_type"], row["entity_id"])
            for row in observations
        }
        edges = []
        adjacency: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for edge in relationships:
            source = (edge["source_type"], edge["source_id"])
            target = (edge["target_type"], edge["target_id"])
            edges.append(edge)
            adjacency.setdefault(source, []).append(target)
            adjacency.setdefault(target, []).append(source)
            seeds.add(source)
            seeds.add(target)

        visited = set(seeds)
        queue = deque(seeds)
        while queue:
            current = queue.popleft()
            for target in adjacency.get(current, ()):
                if target not in visited:
                    visited.add(target)
                    queue.append(target)

        domains = set()
        for row in observations:
            payload = row["payload"]
            domain = payload.get("failure_domain")
            if domain:
                domains.add(str(domain))
        for edge in edges:
            payload = edge["payload"]
            domain = payload.get("failure_domain")
            if domain:
                domains.add(str(domain))

        entities = tuple(sorted(visited))
        return {
            "scope_id": scope_id,
            "affected_entities": entities,
            "failure_domains": tuple(sorted(domains)),
            "dependency_edges": tuple(edges),
        }

    def failure_episode(self, scope_id: str, observed_at: float) -> dict[str, Any]:
        root = self.graph.snapshot(scope_id)
        root_domains = set(self.impact(scope_id)["failure_domains"])
        root_path_ids = set(root["path_ids"])
        correlated = {scope_id}

        all_scopes = sorted(
            {
                row["scope_id"]
                for row in self.graph.observations()
            }
            | {
                row["scope_id"]
                for row in self.graph.relationships()
            }
        )
        for candidate in all_scopes:
            if candidate == scope_id:
                continue
            snapshot = self.graph.snapshot(candidate)
            observations = snapshot["observations"]
            if not observations:
                continue
            latest = max(observations, key=lambda row: float(row["observed_at"]))
            if abs(float(latest["observed_at"]) - float(observed_at)) > 30.0:
                continue
            candidate_domains = set(self.impact(candidate)["failure_domains"])
            shared_path = bool(root_path_ids & set(snapshot["path_ids"]))
            shared_domain = bool(root_domains & candidate_domains)
            shared_dependency = self._shares_dependency(root, snapshot)
            if shared_path or shared_domain or shared_dependency:
                correlated.add(candidate)

        return {
            "scope_id": scope_id,
            "observed_at": float(observed_at),
            "correlated_scopes": tuple(sorted(correlated)),
        }

    @staticmethod
    def _shares_dependency(
        left: dict[str, Any], right: dict[str, Any]
    ) -> bool:
        left_targets = {
            (row["target_type"], row["target_id"])
            for row in left["relationships"]
        }
        right_targets = {
            (row["target_type"], row["target_id"])
            for row in right["relationships"]
        }
        return bool(left_targets & right_targets)
