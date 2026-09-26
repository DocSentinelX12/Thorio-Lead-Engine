# Research Intelligence and Evidence Graph Design

## Goal

Build a canonical research intelligence layer that converts the existing opportunity-scoped research package into a traceable intelligence model containing company context, opportunity need, decision-maker context, commercial context, evidence relationships, claims, conflicts, staleness, unknowns, and downstream handoff state.

## Architectural contract

Research intelligence is derived only from the canonical opportunity and research already present on that opportunity. It never creates external facts, contacts, URLs, timestamps, verification, qualification, or route eligibility.

Every evidence node remains attached to the canonical opportunity and retains source, source record, URL, evidence text, observation time, research section, route when applicable, and verification status.

Claims are machine-readable conclusions or observations. A claim is not verified merely because it exists. Observed, corroborated, contested, and verified states remain distinct.

Conflicting claims are preserved. The system records the conflict and does not silently select a winner.

Stale evidence remains durable and is marked stale. It is never silently deleted.

Research gaps and unknowns remain explicit and are carried to downstream consumers.

## Intelligence shape

The canonical object contains:

- opportunity_id and fingerprint
- company profile
- need profile
- decision-maker profile
- commercial and route context
- stakeholder context
- evidence graph
- claims
- conflicts
- stale evidence
- unknowns and research gaps
- downstream handoff state

## Evidence graph

Evidence nodes use the existing canonical evidence key and provenance contract. Claims reference evidence nodes by canonical evidence key. Cross-opportunity evidence is rejected.

## Downstream contract

The intelligence object is included in the Lead model, sales handoff projection and digest, research synchronization payload, and stateful company-research persistence. It is available to qualification, sales handoff, outreach closer, and follow-up stages without replacing their existing contracts.

## Verification

Only explicit existing verification state can produce a verified intelligence status. Research intelligence does not upgrade observed evidence.

## Freshness

Evidence older than 90 days is marked stale when a timestamp is available. Missing or malformed timestamps remain freshness unknown rather than being treated as current or stale.
