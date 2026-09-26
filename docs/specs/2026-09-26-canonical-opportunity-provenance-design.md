# Canonical Opportunity and Provenance Foundation

Date: 2026-09-26
Branch: main
Scope: Build #1, canonical opportunity identity and provenance foundation

## 1. Purpose

Strengthen the existing opportunity identity, evidence, research, routing, and handoff infrastructure so one real commercial opportunity has one canonical identity and every downstream research or commercial artifact remains attributable to that identity.

This is an incremental canonicalization design. Existing lead fingerprints remain the compatibility identity where they already represent the opportunity. The implementation must not create a competing deduplication identity system.

## 2. Existing architecture used as the base

The current main branch already provides:

- Lead.opportunity_id and Lead.fingerprint in lead_engine/models.py.
- Lead.compute_fingerprint(), which derives fingerprint and sets opportunity_id.
- lead_engine/lead_identity.py as the existing identity primitive.
- evidence_events on Lead.
- canonical research sections in research_package.py.
- package_digest() and package_projection() in sales_handoff.py.
- research synchronization and Raw Research Package persistence in research_sync.py.
- routing and route-specific research structures.
- durable revenue execution using opportunity_id.
- existing tests for research package and sales handoff behavior.

The implementation will extend these mechanisms instead of replacing them.

## 3. Canonical identity contract

The canonical opportunity identity is the existing Lead fingerprint unless the repository's identity primitive demonstrates that a distinct stable identifier is required for an existing consumer.

The canonical identity contract must expose:

- opportunity_id
- fingerprint
- company identity
- company website/domain when available
- contact identity when available
- source
- source_id
- discovery URL
- discovery timestamp
- canonical identity version
- identity derivation metadata sufficient to diagnose collisions

opportunity_id and fingerprint must remain equivalent for the existing compatibility path unless an explicit migration contract is introduced.

Identity derivation must be deterministic for the same canonical opportunity input.

A later observation of the same opportunity must not generate a new opportunity solely because additional research was collected.

A genuinely different opportunity must not be collapsed solely because company or contact identity matches.

## 4. Identity isolation

Every research-bearing object must carry or inherit the canonical opportunity identity.

The foundation must validate:

- opportunity_id matches fingerprint where both exist
- evidence fingerprint matches the containing opportunity
- nested research evidence does not reference another opportunity
- source provenance is retained
- route-specific evidence remains associated with its route
- conversation and commercial execution references point to the same opportunity
- Airtable research records contain the canonical fingerprint
- serialized package digests are calculated from the canonical package

Cross-opportunity evidence must fail closed rather than being silently reassigned.

## 5. Provenance contract

A provenance record represents an observation or evidence reference and preserves:

- opportunity_id/fingerprint
- source or source lane
- source record identifier when available
- URL when available
- evidence or signal text
- observed_at or collection timestamp
- research section
- verification status
- route when evidence is route-specific
- collector/research operation when available

Observed evidence is not verified evidence.

Verification status may only become verified through the repository's existing explicit verification path. The foundation must not infer verification from the existence of a URL or evidence string.

Provenance must survive research merging, serialization, Airtable synchronization, package projection, and downstream handoff.

## 6. Research merge behavior

Existing stronger verified research must survive a weaker update.

New observations may be merged with existing observations.

Evidence entries must be deduplicated without deleting distinct observations that differ by source, evidence, or observation timestamp.

A merge must preserve the containing opportunity identity.

A route-specific merge must preserve route boundaries.

A malformed or cross-opportunity evidence item must not be merged into the package.

## 7. Canonical package behavior

The canonical package remains the source object used to derive research and downstream commercial views.

The package must preserve:

- identity
- discovery provenance
- company research
- decision-maker research
- all five verifiable research sections
- research gaps and unknowns
- evidence events
- route-specific evidence
- routing state
- closer package data
- package digest inputs

The implementation must not flatten separate opportunities into one package and must not reconstruct identity from partial downstream fields when the canonical package is available.

## 8. Airtable boundary

Airtable remains durable research persistence and operational observability.

Airtable must receive the canonical identity and complete research-bearing payload.

Airtable synchronization must not become the authority for whether an opportunity exists.

A transient Airtable failure must not mutate or replace canonical opportunity identity.

Existing package digest verification remains the integrity mechanism for detecting stale or mismatched stored research.

## 9. Downstream compatibility

The foundation must remain compatible with:

- existing routing
- Shiftr, Paxus, and Thorio route representation
- research workers
- research queue and durable recovery
- revenue conversation state
- revenue execution
- outreach idempotency
- Airtable research synchronization
- existing production gates

No source is removed.

No research section is removed.

No arbitrary backlog cap is introduced.

No human approval state is introduced into canonical identity.

Machine safety, evidence validation, idempotency, retries, and durable state remain authoritative.

## 10. Error behavior

Canonical identity or provenance validation errors must be deterministic and diagnostic.

Errors must identify the invariant that failed and, where applicable, the opportunity fingerprint and conflicting identity.

Cross-opportunity evidence must be rejected rather than repaired by guessing.

Missing optional provenance fields remain missing when the source did not provide them. The foundation must not invent URLs, source identifiers, timestamps, contacts, or verification.

## 11. Tests

Focused tests must cover:

1. Stable identity for identical opportunity inputs.
2. Different opportunity inputs remain distinct.
3. opportunity_id/fingerprint consistency.
4. Provenance carries the containing opportunity identity.
5. Cross-opportunity evidence is rejected.
6. Missing provenance is not fabricated.
7. Observed evidence does not become verified implicitly.
8. Verified research survives weaker merges.
9. Distinct evidence observations survive merging.
10. Route-specific evidence remains isolated.
11. Canonical package digest changes when canonical package content changes.
12. Canonical package digest is stable for equivalent packages.
13. Airtable research payload preserves canonical identity.
14. Existing handoff verification still rejects stale or mismatched packages.
15. Existing multi-route ordering and routing behavior remain intact.
16. Existing revenue execution opportunity IDs remain compatible.
17. No human approval is required for identity/provenance construction.
18. No existing source or durable queue is reduced or discarded.

## 12. Production verification

Before declaring this layer complete:

- inspect the complete diff
- run the focused identity, provenance, research, handoff, routing, and execution tests
- run the repository's full test workflow
- inspect workflow failures at the actual failing test or production gate
- verify main contains the implementation
- verify feature/gpu-fabric-foundation is untouched by this work
- verify no placeholder, fake URL, or invented evidence behavior was introduced

Completion means the implementation and its integration are verified by actual repository evidence, not merely by code inspection.
