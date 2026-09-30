"""Canonical unified opportunity signal graph.

The graph is a deterministic projection of persisted opportunity state. It connects
canonical identity, source observations, signals, evidence, research, qualification,
routing, outreach activity, outcomes, and revenue attribution without replacing any
existing subsystem or inferring causality.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .lead_identity import validate_materialized_opportunity_identity
from .opportunity_provenance import canonical_evidence_key, normalize_evidence_event
from .revenue_signal_observation import build_revenue_signal_observation

GRAPH_VERSION = "1"
GRAPH_STATE_KEY = "unified_opportunity_signal_graph"
_SIGNAL_TYPES = {"signal", "signal_observation"}
_STRUCTURAL_RESEARCH_SECTIONS = (
    "business_need_research",
    "current_intent_research",
    "technical_product_hiring_research",
    "commercial_research",
    "route_research",
    "company_research",
    "decision_maker_research",
    "closer_package",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize(value: Any) -> str:
    return " ".join(_text(value).lower().split())


def _hash(kind: str, value: Any) -> str:
    raw = json.dumps([kind, value], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _node(kind: str, key: Any, **payload: Any) -> tuple[str, dict[str, Any]]:
    node_id = f"{kind}:{_hash(kind, key)}"
    return node_id, {"id": node_id, "type": kind, **payload}


def _edge(kind: str, source: str, target: str, **payload: Any) -> dict[str, Any]:
    edge_id = f"edge:{_hash(kind, [source, target, payload])}"
    return {"id": edge_id, "type": kind, "from": source, "to": target, **payload}


def _list_mappings(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _outcome_events(lead: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return explicit outcome events once, with deterministic source precedence.

    A commercial outcome is the canonical terminal business outcome when present.
    Conversation and outreach records remain useful outcome observations when they
    are distinct events. Lifecycle states are never converted into outcomes because
    states such as conversation_active and outreach_sent are not outcomes.
    """
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(kind: str, item: Mapping[str, Any], outcome: str) -> None:
        normalized = _normalize(outcome)
        if not normalized:
            return
        event_id = _text(item.get("event_id") or item.get("action_id"))
        observed_at = _text(item.get("at") or item.get("observed_at"))
        evidence = _text(item.get("evidence"))
        key = (
            f"id:{event_id}" if event_id else
            f"event:{kind}|{observed_at}|{normalized}|{evidence}"
        )
        if key in seen:
            return
        seen.add(key)
        events.append({"kind": kind, **dict(item), "outcome": normalized})

    commercial = lead.get("commercial_outcome")
    if isinstance(commercial, Mapping):
        add("commercial_outcome", commercial, _text(commercial.get("type")))

    for item in _list_mappings(lead.get("conversation_events")):
        add("conversation_outcome", item, _text(item.get("outcome")))
    for item in _list_mappings(lead.get("outreach_history")):
        add("outreach_outcome", item, _text(item.get("outcome")))

    return events


def _add_evidence(
    nodes: dict[str, dict[str, Any]],
    evidence: Mapping[str, Any],
    *,
    opportunity_id: str,
    research_section: str,
) -> str:
    normalized = normalize_evidence_event(
        evidence,
        opportunity_id=opportunity_id,
        research_section=research_section,
        route=_text(evidence.get("route")) or None,
        collector="unified_opportunity_signal_graph",
    )
    key = _text(normalized.get("canonical_evidence_key")) or canonical_evidence_key(normalized)
    node_id, node = _node(
        "evidence",
        key,
        opportunity_id=opportunity_id,
        canonical_evidence_key=key,
        evidence=_text(normalized.get("evidence") or normalized.get("signal")),
        signal=_text(normalized.get("signal")),
        source=_text(normalized.get("source")),
        source_id=_text(normalized.get("source_id")),
        source_url=_text(normalized.get("url") or normalized.get("source_url")),
        observed_at=_text(normalized.get("observed_at")),
        verification_status=_text(normalized.get("verification_status")) or "observed_evidence",
        research_section=research_section,
        provenance=dict(normalized.get("provenance") or {}),
    )
    nodes.setdefault(node_id, node)
    return node_id


def _signal_entries(
    lead: Mapping[str, Any],
    opportunity_id: str,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in lead.get("signal_matches") if isinstance(lead.get("signal_matches"), list) else []:
        trigger = _text(raw)
        if not trigger:
            continue
        key = f"configured|{_normalize(trigger)}"
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            "signal_key": key,
            "signal_type": _text(lead.get("signal_type")) or "unknown",
            "category": "configured_signal",
            "phrase": trigger,
            "exact_evidence": _text(lead.get("evidence")) or _text(lead.get("signal")),
            "source": _text(lead.get("source")),
            "source_id": _text(lead.get("source_id")),
            "source_url": _text(lead.get("source_url") or lead.get("url")),
            "observed_at": _text(lead.get("observed_at") or lead.get("discovered_at")),
            "promotion_eligible": True,
        })

    broadening = lead.get("commercial_signal_broadening")
    if isinstance(broadening, Mapping):
        for raw in broadening.get("matches") if isinstance(broadening.get("matches"), list) else []:
            if not isinstance(raw, Mapping):
                continue
            phrase = _text(raw.get("phrase"))
            category = _text(raw.get("category") or raw.get("signal_id"))
            if not phrase or not category:
                continue
            key = f"broadened|{_normalize(category)}|{_normalize(phrase)}"
            if key in seen:
                continue
            seen.add(key)
            entries.append({
                "signal_key": key,
                "signal_type": _text(lead.get("signal_type")) or "unknown",
                "category": category,
                "phrase": phrase,
                "exact_evidence": _text(raw.get("evidence_context")),
                "source": _text(lead.get("source")),
                "source_id": _text(lead.get("source_id")),
                "source_url": _text(lead.get("source_url") or lead.get("url")),
                "observed_at": _text(lead.get("observed_at") or lead.get("discovered_at")),
                "attribution": _text(raw.get("attribution")),
                "temporal_status": _text(raw.get("temporal_status")),
                "certainty": _text(raw.get("certainty")),
                "negated": raw.get("negated") is True,
                "technical_context": raw.get("technical_context") is True,
                "promotion_eligible": raw.get("promotion_eligible") is True,
                "source_field": _text(raw.get("source_field")),
            })
    return entries


def build_unified_opportunity_signal_graph(
    leads: Iterable[Mapping[str, Any]],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the authoritative graph projection from persisted opportunity records."""
    if isinstance(leads, (str, bytes, Mapping)):
        raise ValueError("leads must be an iterable of opportunity mappings.")

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    opportunity_ids: list[str] = []

    for raw_lead in leads:
        if not isinstance(raw_lead, Mapping):
            continue
        lead = dict(raw_lead)
        opportunity_id = _text(lead.get("opportunity_id") or lead.get("fingerprint"))
        if not opportunity_id:
            continue
        validate_materialized_opportunity_identity(lead)

        if opportunity_id not in opportunity_ids:
            opportunity_ids.append(opportunity_id)

        opportunity_id_node, opportunity_node = _node(
            "opportunity",
            opportunity_id,
            opportunity_id=opportunity_id,
            fingerprint=_text(lead.get("fingerprint")),
            identity_version=_text(lead.get("identity_version")),
            company=_text(lead.get("company")),
            company_website=_text(lead.get("company_website") or lead.get("website") or lead.get("domain")),
        )
        nodes.setdefault(opportunity_id_node, opportunity_node)

        source_key = [_text(lead.get("source")), _text(lead.get("source_id")), _text(lead.get("url") or lead.get("source_url"))]
        if any(source_key):
            source_id, source_node = _node(
                "source_observation",
                source_key,
                opportunity_id=opportunity_id,
                source=_text(lead.get("source")),
                source_id=_text(lead.get("source_id")),
                source_url=_text(lead.get("url") or lead.get("source_url")),
                observed_at=_text(lead.get("observed_at") or lead.get("discovered_at")),
            )
            nodes.setdefault(source_id, source_node)
            edge = _edge("opportunity_observed_by_source", opportunity_id_node, source_id)
            edges[edge["id"]] = edge

        for raw in _list_mappings(lead.get("evidence_events")):
            evidence_id = _add_evidence(nodes, raw, opportunity_id=opportunity_id, research_section="evidence_events")
            edge = _edge("opportunity_supported_by_evidence", opportunity_id_node, evidence_id)
            edges[edge["id"]] = edge

        observation = build_revenue_signal_observation(lead)
        observation_key = _hash("signal_observation", [
            opportunity_id,
            observation.get("source"),
            observation.get("source_id"),
            observation.get("source_url"),
            observation.get("observed_at"),
            observation.get("signal"),
            observation.get("evidence"),
        ])
        observation_id, observation_node = _node(
            "signal_observation",
            observation_key,
            opportunity_id=opportunity_id,
            observed_at=_text(observation.get("observed_at")),
            source=_text(observation.get("source")),
            source_id=_text(observation.get("source_id")),
            source_url=_text(observation.get("source_url")),
            signal=dict(observation.get("signal") or {}),
            evidence=dict(observation.get("evidence") or {}),
            provenance=dict(observation.get("provenance") or {}),
        )
        nodes.setdefault(observation_id, observation_node)
        edge = _edge("opportunity_has_signal_observation", opportunity_id_node, observation_id)
        edges[edge["id"]] = edge

        for signal in _signal_entries(lead, opportunity_id):
            signal_id, signal_node = _node(
                "signal",
                signal["signal_key"],
                signal_key=signal["signal_key"],
                category=signal["category"],
                signal_type=signal["signal_type"],
                phrase=signal["phrase"],
            )
            nodes.setdefault(signal_id, signal_node)
            edge = _edge("observation_instantiates_signal", observation_id, signal_id)
            edges[edge["id"]] = edge
            if signal.get("exact_evidence"):
                evidence_id, evidence_node = _node(
                    "signal_evidence",
                    [opportunity_id, signal["signal_key"], signal["exact_evidence"], signal.get("source_url"), signal.get("observed_at")],
                    opportunity_id=opportunity_id,
                    signal_key=signal["signal_key"],
                    exact_evidence=signal["exact_evidence"],
                    source=signal.get("source"),
                    source_id=signal.get("source_id"),
                    source_url=signal.get("source_url"),
                    observed_at=signal.get("observed_at"),
                    attribution=signal.get("attribution"),
                    temporal_status=signal.get("temporal_status"),
                    certainty=signal.get("certainty"),
                    negated=signal.get("negated"),
                    technical_context=signal.get("technical_context"),
                    promotion_eligible=signal.get("promotion_eligible"),
                    source_field=signal.get("source_field"),
                )
                nodes.setdefault(evidence_id, evidence_node)
                edge = _edge("signal_supported_by_observed_evidence", signal_id, evidence_id)
                edges[edge["id"]] = edge

        for field in _STRUCTURAL_RESEARCH_SECTIONS:
            section = lead.get(field)
            if not isinstance(section, Mapping):
                continue
            research_id, research_node = _node(
                "research",
                [opportunity_id, field],
                opportunity_id=opportunity_id,
                research_section=field,
                status=_text(section.get("verification_status") or section.get("status")) or ("verified" if section.get("verified") is True else "observed"),
            )
            nodes.setdefault(research_id, research_node)
            edge = _edge("opportunity_has_research", opportunity_id_node, research_id)
            edges[edge["id"]] = edge
            for raw in _list_mappings(section.get("evidence")):
                evidence_id = _add_evidence(nodes, raw, opportunity_id=opportunity_id, research_section=field)
                edge = _edge("research_supported_by_evidence", research_id, evidence_id)
                edges[edge["id"]] = edge
            routes = section.get("routes")
            if field == "route_research" and isinstance(routes, Mapping):
                for route, route_data in routes.items():
                    if not isinstance(route_data, Mapping):
                        continue
                    route_id, route_node = _node("route", [opportunity_id, _text(route)], opportunity_id=opportunity_id, route=_text(route), status=_text(route_data.get("verification_status") or route_data.get("status")) or ("verified" if route_data.get("verified") is True else "observed"))
                    nodes.setdefault(route_id, route_node)
                    edge = _edge("research_supports_route", research_id, route_id)
                    edges[edge["id"]] = edge
                    for raw in _list_mappings(route_data.get("evidence")):
                        evidence_id = _add_evidence(nodes, raw, opportunity_id=opportunity_id, research_section="route_research")
                        edge = _edge("route_supported_by_evidence", route_id, evidence_id)
                        edges[edge["id"]] = edge

        qualification = lead.get("qualification_results")
        if isinstance(qualification, Mapping):
            qualification_id, qualification_node = _node(
                "qualification",
                opportunity_id,
                opportunity_id=opportunity_id,
                qualified=lead.get("qualified") is True,
                results=dict(qualification),
                status=_text(lead.get("qualification_status")),
            )
            nodes.setdefault(qualification_id, qualification_node)
            edge = _edge("opportunity_has_qualification", opportunity_id_node, qualification_id)
            edges[edge["id"]] = edge

        routes = lead.get("eligible_routes") or lead.get("potential_routes") or lead.get("preserved_routes")
        if isinstance(routes, (list, tuple, set)):
            for route in routes:
                route_text = _text(route)
                if not route_text:
                    continue
                route_id, route_node = _node("route", [opportunity_id, route_text], opportunity_id=opportunity_id, route=route_text)
                nodes.setdefault(route_id, route_node)
                edge = _edge("opportunity_has_route", opportunity_id_node, route_id)
                edges[edge["id"]] = edge

        for item in _list_mappings(lead.get("outreach_history")):
            action_key = [opportunity_id, item.get("action_id"), item.get("conversation_id"), item.get("route"), item.get("channel"), item.get("status"), item.get("kind")]
            action_id, action_node = _node(
                "outreach_action",
                action_key,
                opportunity_id=opportunity_id,
                action_id=_text(item.get("action_id")),
                conversation_id=_text(item.get("conversation_id")),
                route=_text(item.get("route")),
                channel=_text(item.get("channel")),
                status=_text(item.get("status")),
                provider_result=dict(item.get("provider_result") or {}) if isinstance(item.get("provider_result"), Mapping) else {},
            )
            action_node["action_kind"] = _text(item.get("kind")) or "outreach"
            nodes.setdefault(action_id, action_node)
            edge = _edge("opportunity_has_outreach_action", opportunity_id_node, action_id)
            edges[edge["id"]] = edge
        if isinstance(lead.get("commercial_strategy"), Mapping):
            closer_id, closer_node = _node(
                "closer_strategy",
                [opportunity_id, lead.get("outreach_route"), lead.get("commercial_strategy")],
                opportunity_id=opportunity_id,
                route=_text(lead.get("outreach_route") or lead.get("active_route")),
                strategy=dict(lead.get("commercial_strategy")),
            )
            nodes.setdefault(closer_id, closer_node)
            edge = _edge("opportunity_has_closer_strategy", opportunity_id_node, closer_id)
            edges[edge["id"]] = edge

        for item in _outcome_events(lead):
            outcome = _text(item.get("outcome")).lower()
            if not outcome:
                continue
            event_key = [
                opportunity_id,
                item.get("event_id"),
                item.get("action_id"),
                item.get("at"),
                item.get("outcome"),
                item.get("kind"),
                item.get("evidence"),
            ]
            outcome_id, outcome_node = _node(
                "outcome",
                event_key,
                opportunity_id=opportunity_id,
                outcome=outcome,
                outcome_kind=_text(item.get("kind")),
                observed_at=_text(item.get("at") or item.get("observed_at")),
                event_id=_text(item.get("event_id")),
                action_id=_text(item.get("action_id")),
                evidence=_text(item.get("evidence")),
                route=_text(item.get("route")),
            )
            nodes.setdefault(outcome_id, outcome_node)
            edge = _edge("opportunity_observed_outcome", opportunity_id_node, outcome_id)
            edges[edge["id"]] = edge
            for signal in _signal_entries(lead, opportunity_id):
                signal_observed_at = _text(signal.get("observed_at"))
                outcome_observed_at = _text(item.get("at") or item.get("observed_at"))
                if signal_observed_at and outcome_observed_at and signal_observed_at > outcome_observed_at:
                    continue
                signal_id, _ = _node("signal", signal["signal_key"], category=signal["category"], signal_type=signal["signal_type"], phrase=signal["phrase"], signal_key=signal["signal_key"])
                association = _edge(
                    "signal_observed_with_outcome",
                    signal_id,
                    outcome_id,
                    association_only=True,
                    temporal_relation="prior_or_same_time" if signal_observed_at and outcome_observed_at else "temporal_order_unknown",
                )
                edges[association["id"]] = association

        revenue_id, revenue_node = _node(
            "revenue_attribution",
            opportunity_id,
            opportunity_id=opportunity_id,
            lifecycle_state=_text(lead.get("revenue_lifecycle_state")),
            sales_eligibility=_text(lead.get("sales_eligibility")),
            route=_text(lead.get("outreach_route") or lead.get("active_route")),
            commercial_outcome=dict(lead.get("commercial_outcome") or {}) if isinstance(lead.get("commercial_outcome"), Mapping) else {},
        )
        nodes.setdefault(revenue_id, revenue_node)
        edge = _edge("opportunity_has_revenue_attribution", opportunity_id_node, revenue_id)
        edges[edge["id"]] = edge

    timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    graph = {
        "graph_version": GRAPH_VERSION,
        "generated_at": timestamp,
        "authoritative": True,
        "causality": "not_established",
        "node_count": len(nodes),
        "edge_count": len(edges),
        "opportunity_count": len(opportunity_ids),
        "opportunity_ids": opportunity_ids,
        "nodes": nodes,
        "edges": list(edges.values()),
    }
    return graph


def validate_unified_opportunity_signal_graph(graph: Mapping[str, Any]) -> None:
    if not isinstance(graph, Mapping):
        raise ValueError("Unified opportunity signal graph must be a mapping.")
    if _text(graph.get("graph_version")) != GRAPH_VERSION:
        raise ValueError("Unsupported unified opportunity signal graph version.")
    if graph.get("authoritative") is not True:
        raise ValueError("Unified opportunity signal graph must be authoritative.")
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, Mapping) or not nodes:
        raise ValueError("Unified opportunity signal graph requires non-empty nodes.")
    if not isinstance(edges, list):
        raise ValueError("Unified opportunity signal graph requires an edge list.")
    for node_id, node in nodes.items():
        if not isinstance(node, Mapping) or _text(node.get("id")) != str(node_id) or not _text(node.get("type")):
            raise ValueError("Unified opportunity signal graph contains an invalid node.")
    for edge in edges:
        if not isinstance(edge, Mapping):
            raise ValueError("Unified opportunity signal graph contains an invalid edge.")
        if _text(edge.get("from")) not in nodes or _text(edge.get("to")) not in nodes:
            raise ValueError("Unified opportunity signal graph contains a dangling edge.")
        if _text(edge.get("id")) == "":
            raise ValueError("Unified opportunity signal graph edge requires an id.")
        if edge.get("type") == "signal_observed_with_outcome" and edge.get("association_only") is not True:
            raise ValueError("Signal outcome edges must remain association-only.")
    for opportunity_id in graph.get("opportunity_ids", []):
        if f"opportunity:{_hash('opportunity', opportunity_id)}" not in nodes:
            raise ValueError("Unified opportunity signal graph references an unknown opportunity.")


def persist_unified_opportunity_signal_graph(db: Any) -> dict[str, Any]:
    graph = build_unified_opportunity_signal_graph(db.all_leads())
    validate_unified_opportunity_signal_graph(graph)
    db.set_state(GRAPH_STATE_KEY, graph)
    return graph


def load_unified_opportunity_signal_graph(db: Any) -> dict[str, Any]:
    graph = db.get_state(GRAPH_STATE_KEY)
    if not isinstance(graph, Mapping):
        return persist_unified_opportunity_signal_graph(db)
    validate_unified_opportunity_signal_graph(graph)
    return dict(graph)
