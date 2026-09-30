"""Durable signal to outcome feedback derived from the unified opportunity graph.

Feedback is descriptive association learning. It can prioritize future evidence
collection and research for recurring signals, but it never treats an outcome as
caused by a signal or invents missing evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .unified_opportunity_signal_graph import (
    GRAPH_STATE_KEY,
    build_unified_opportunity_signal_graph,
    validate_unified_opportunity_signal_graph,
)

FEEDBACK_VERSION = "1"
FEEDBACK_STATE_KEY = "signal_outcome_feedback"
_POSITIVE_OUTCOMES = {"converted", "referred", "interested", "replied"}
_RESEARCHABLE_OUTCOMES = _POSITIVE_OUTCOMES | {"objection", "no_response", "closed_lost", "opted_out", "declined"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _outcome_nodes(graph: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    nodes = graph.get("nodes")
    return [
        node for node in nodes.values()
        if isinstance(node, Mapping) and _text(node.get("type")) == "outcome"
    ] if isinstance(nodes, Mapping) else []


def _signal_nodes(graph: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    nodes = graph.get("nodes")
    return [
        node for node in nodes.values()
        if isinstance(node, Mapping) and _text(node.get("type")) == "signal"
    ] if isinstance(nodes, Mapping) else []


def _edges_for(graph: Mapping[str, Any], *, edge_type: str) -> list[Mapping[str, Any]]:
    return [
        edge for edge in graph.get("edges", [])
        if isinstance(edge, Mapping) and _text(edge.get("type")) == edge_type
    ]


def build_signal_outcome_feedback(graph: Mapping[str, Any]) -> dict[str, Any]:
    """Build association feedback from one authoritative graph projection."""
    validate_unified_opportunity_signal_graph(graph)
    nodes = graph["nodes"]
    signals = {str(node["id"]): node for node in _signal_nodes(graph)}
    outcomes = {str(node["id"]): node for node in _outcome_nodes(graph)}
    associations = _edges_for(graph, edge_type="signal_observed_with_outcome")

    by_signal: dict[str, dict[str, Any]] = {}
    for edge in associations:
        signal = signals.get(_text(edge.get("from")))
        outcome = outcomes.get(_text(edge.get("to")))
        if not signal or not outcome:
            continue
        key = _text(signal.get("signal_key")) or _text(signal.get("phrase"))
        outcome_name = _text(outcome.get("outcome")).lower()
        if not key or not outcome_name:
            continue
        bucket = by_signal.setdefault(key, {
            "signal_key": key,
            "category": _text(signal.get("category")),
            "signal_type": _text(signal.get("signal_type")),
            "phrase": _text(signal.get("phrase")),
            "observations": 0,
            "distinct_opportunities": set(),
            "outcomes": {},
            "association_only": True,
        })
        bucket["observations"] += 1
        opportunity_id = _text(outcome.get("opportunity_id"))
        if opportunity_id:
            bucket["distinct_opportunities"].add(opportunity_id)
        bucket["outcomes"][outcome_name] = int(bucket["outcomes"].get(outcome_name, 0)) + 1

    for bucket in by_signal.values():
        opportunities = len(bucket.pop("distinct_opportunities"))
        outcomes = bucket["outcomes"]
        positive = sum(int(outcomes.get(name, 0)) for name in _POSITIVE_OUTCOMES)
        terminal_positive = int(outcomes.get("converted", 0)) + int(outcomes.get("referred", 0))
        bucket["distinct_opportunities"] = opportunities
        bucket["positive_engagement_count"] = positive
        bucket["terminal_positive_count"] = terminal_positive
        bucket["research_priority"] = (
            2 if terminal_positive > 0 else
            1 if positive > 0 else
            0
        )
        bucket["collection_priority"] = bucket["research_priority"]
        bucket["feedback_rule"] = (
            "Historical co-occurrence only. Priority increases evidence collection "
            "and research verification for recurring signals; it does not assert "
            "that the signal caused the outcome."
        )

    return {
        "feedback_version": FEEDBACK_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "graph_version": _text(graph.get("graph_version")),
        "association_only": True,
        "by_signal": dict(sorted(by_signal.items())),
        "interpretation_note": (
            "Feedback is derived only from observed signal and outcome nodes in the "
            "authoritative graph. It is used to prioritize evidence verification, "
            "not to create evidence, infer causality, or alter canonical identity."
        ),
    }


def persist_signal_outcome_feedback(db: Any) -> dict[str, Any]:
    """Rebuild and durably persist feedback from the current authoritative graph."""
    graph = build_unified_opportunity_signal_graph(db.all_leads())
    validate_unified_opportunity_signal_graph(graph)
    db.set_state(GRAPH_STATE_KEY, graph)
    feedback = build_signal_outcome_feedback(graph)
    db.set_state(FEEDBACK_STATE_KEY, feedback)
    return feedback


def refresh_signal_outcome_feedback(db: Any) -> dict[str, Any]:
    """Refresh feedback after a durable opportunity lifecycle transition."""
    return persist_signal_outcome_feedback(db)


def load_signal_outcome_feedback(db: Any) -> dict[str, Any]:
    """Read persisted feedback without constructing or mutating the graph.

    Initial discovery and other pre-opportunity paths may legitimately have no
    persisted feedback yet. Consumers receive an empty, association-only
    projection until the explicit refresh boundary has materialized feedback.
    Test doubles that do not implement durable state are treated the same way.
    """
    if not hasattr(db, "get_state"):
        return {
            "feedback_version": FEEDBACK_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "graph_version": "",
            "association_only": True,
            "by_signal": {},
            "interpretation_note": (
                "No durable feedback state is available. No outcome association "
                "is inferred and no collection or research priority is changed."
            ),
        }
    feedback = db.get_state(FEEDBACK_STATE_KEY)
    if isinstance(feedback, Mapping):
        return dict(feedback)
    return {
        "feedback_version": FEEDBACK_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "graph_version": "",
        "association_only": True,
        "by_signal": {},
        "interpretation_note": (
            "No persisted feedback exists yet. No outcome association is inferred "
            "and no collection or research priority is changed."
        ),
    }


def signal_feedback_priority(
    lead: Mapping[str, Any],
    feedback: Mapping[str, Any],
) -> int:
    """Return the highest observed association priority for this lead's signals."""
    matches = lead.get("signal_matches")
    if not isinstance(matches, list):
        return 0
    by_signal = feedback.get("by_signal")
    if not isinstance(by_signal, Mapping):
        return 0
    priorities = []
    for raw in matches:
        key = _text(raw).lower()
        candidates = (key, f"configured|{key}")
        for candidate in candidates:
            item = by_signal.get(candidate)
            if not isinstance(item, Mapping):
                continue
            try:
                priorities.append(max(0, int(item.get("research_priority", 0) or 0)))
            except (TypeError, ValueError):
                pass
            break
    return max(priorities, default=0)


def apply_feedback_to_research_target(target: dict[str, Any], *, priority: int) -> dict[str, Any]:
    """Annotate a research target with observed-association priority without changing its evidence."""
    result = dict(target)
    base = int(result.get("priority", 1) or 1)
    result["priority"] = base + max(0, int(priority))
    result["feedback"] = {
        "applied": bool(priority),
        "association_only": True,
        "priority_delta": max(0, int(priority)),
        "reason": (
            "Recurring signal has historical outcome co-occurrence; prioritize "
            "verification of current evidence without treating the association as causal."
        ) if priority else "No historical outcome association was available for this signal.",
    }
    return result
