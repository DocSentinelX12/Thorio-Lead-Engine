# Canonical Opportunity and Provenance Foundation Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the canonical opportunity identity and provenance foundation across discovery, research, merging, handoff, Airtable persistence, and downstream execution without removing existing sources, research sections, routes, queues, or revenue behavior.

**Architecture:** Preserve the existing `Lead`, fingerprint, SQLite, canonical research, sales handoff, routing, and Airtable boundaries while adding one explicit canonical opportunity/provenance contract that all participating boundaries validate. The existing identity primitive remains the compatibility mechanism unless the implementation audit demonstrates that its current timestamp-sensitive derivation cannot satisfy the approved identity contract; any required change must be deterministic, backwards-compatible for stored records, and must never silently merge distinct opportunities. Provenance is normalized and validated at the evidence boundary, then carried unchanged through research sections, merges, package projection/digest, Airtable synchronization, routing, and revenue execution.

**Tech Stack:** Python 3.10, dataclasses, SQLite, JSON, existing LeadDB, existing research and routing modules, Airtable synchronization, pytest, GitHub Actions.

## Global Constraints

- Work only on `main` in `DocSentinelX12/Thorio-Lead-Engine`.
- Do not modify, merge, rebase, or otherwise touch `feature/gpu-fabric-foundation`.
- Preserve every configured source, research section, Airtable delivery path, production gate, closer/follow-up component, durable queue/backlog, and Thorio/Shiftr/Paxus routing path.
- Do not impose an arbitrary backlog cap or discard durable work.
- Do not introduce human approval into canonical identity or upstream autonomous processing.
- Never fabricate URLs, source IDs, contacts, evidence, timestamps, verification states, or opportunity identities.
- Distinguish observed evidence from verified evidence. Observation alone must never become verification.
- A single real commercial opportunity has one canonical identity. New research must not create a new opportunity identity.
- Different opportunities must not collapse merely because they share a company or contact.
- `opportunity_id` and `fingerprint` must remain mutually consistent.
- Evidence and nested research must be isolated to their containing opportunity and route.
- Provenance must survive merges, serialization, Airtable synchronization, package projection, handoff, routing, and revenue execution.
- Malformed or cross-opportunity evidence must fail closed with deterministic diagnostics rather than being guessed or silently reassigned.
- Stronger verified research must survive weaker updates. Distinct evidence observations must survive merging unless they are exact duplicates by their canonical evidence key.
- Airtable is a durable research/observability sink, not the authority for whether an opportunity exists.
- Package digests must represent the canonical opportunity package and must detect stale or mismatched stored research.
- Existing downstream consumers of `opportunity_id`, fingerprint, and route-specific identifiers remain compatible.
- No fake tests, placeholders, guessed URLs, or superficial implementations.
- Use TDD for implementation and run the repository's actual pytest workflow before claiming completion.

---

### Task 1: Canonical opportunity identity contract

**Files:**
- Modify: `lead_engine/lead_identity.py`
- Modify: `lead_engine/models.py`
- Modify: `lead_engine/dedupe.py`
- Create or modify: `lead_engine/opportunity_provenance.py` if the identity/provenance contract cannot remain single-purpose in `lead_identity.py`
- Test: `lead_engine/test_lead_identity.py` and/or a focused new canonical-opportunity test module

**Interfaces:**
- Consumes: existing `Lead` fields, `lead_identity()`, `Lead.compute_fingerprint()`, stored fingerprint/opportunity_id values, existing dedupe records.
- Produces: deterministic canonical opportunity identity helpers and validation used by discovery and downstream package boundaries.
- Recommended interface: a small immutable identity/provenance contract returning `opportunity_id`, `fingerprint`, identity version, and derivation metadata, plus a validator that raises a deterministic identity error when the two IDs or identity inputs conflict.

- [ ] **Step 1: Add the focused failing tests**
  - Prove repeated canonicalization of identical identity inputs returns exactly the same opportunity ID and fingerprint.
  - Prove changing research fields does not change identity.
  - Prove two opportunities with the same company/person but different opportunity-defining source/source-record/URL context do not collapse.
  - Prove `opportunity_id == fingerprint` for the compatibility representation.
  - Prove an incoming payload whose opportunity ID and fingerprint disagree is rejected.
  - Prove existing valid fingerprints can still be consumed without an identity migration that invents new IDs.

- [ ] **Step 2: Verify the relevant failure**
  - Run: `python -m pytest lead_engine/test_lead_identity.py` (or the focused new test module if the existing file does not exist).
  - Expected: the new canonical identity assertions fail because the explicit contract and validation are not yet implemented.

- [ ] **Step 3: Implement the minimum behavior**
  - Audit the current timestamp-inclusive identity derivation before changing its inputs.
  - Keep the existing fingerprint field and `opportunity_id` compatibility relationship intact.
  - Introduce an explicit canonical identity version and derivation metadata only where the current model has no equivalent field.
  - Ensure canonicalization consumes only identity-defining inputs, never mutable research, routing, verification, or revenue state.
  - If the existing timestamp-inclusive fingerprint is demonstrably incompatible with stable opportunity identity, introduce a deterministic compatibility-aware derivation and validation path rather than silently recalculating all stored IDs.
  - Make `Lead.to_dict()` and `Lead.compute_fingerprint()` converge on the same canonical contract.
  - Make dedupe use canonical identity validation before comparing records, without changing the existing qualified exact-need behavior.

- [ ] **Step 4: Verify the focused pass**
  - Run: `python -m pytest lead_engine/test_lead_identity.py` and the focused dedupe tests.
  - Expected: all identity and compatibility assertions pass.

- [ ] **Step 5: Run the affected integration check**
  - Run: `python -m pytest lead_engine/test_lead_pipeline.py lead_engine/test_lead_lifecycle.py`.
  - Expected: existing lifecycle and pipeline identity behavior remains green.

- [ ] **Step 6: Commit the passing deliverable**
  - Commit message: `feat: establish canonical opportunity identity contract`

---

### Task 2: Provenance normalization and opportunity isolation

**Files:**
- Create: `lead_engine/opportunity_provenance.py` if Task 1 did not create it
- Modify: `lead_engine/research_package.py`
- Modify: `lead_engine/agent_workers.py` only where existing evidence enters canonical research
- Modify: `lead_engine/advanced_agent_logic.py` only where evidence events are normalized
- Test: focused provenance/research package tests

**Interfaces:**
- Consumes: existing evidence events, specialist findings, public research findings, source/source_id/url metadata, route-specific evidence.
- Produces: canonical provenance records containing opportunity identity, source/source lane, source record ID, URL, evidence text, observed timestamp, research section, verification status, route when applicable, and collector/research operation metadata.

- [ ] **Step 1: Add the focused failing tests**
  - A valid evidence event is normalized without losing source, URL, timestamp, section, or route provenance.
  - Missing identity or provenance-critical values are rejected where the approved contract requires them.
  - An evidence event carrying another opportunity's fingerprint/opportunity ID is rejected.
  - Observed evidence remains `observed_evidence` and cannot become `verified` during normalization.
  - Route-specific evidence remains associated with its route.
  - Equivalent evidence is deduplicated only by the canonical evidence key while distinct timestamps or sources remain distinct.

- [ ] **Step 2: Verify the relevant failure**
  - Run the focused provenance/research tests.
  - Expected: the tests fail because evidence currently lacks centralized identity/provenance validation.

- [ ] **Step 3: Implement the minimum behavior**
  - Centralize normalization and validation instead of duplicating field rules across workers.
  - Preserve existing provenance fields such as `collector_agent`, `source_lane`, and `collected_at`.
  - Add canonical identity and evidence provenance fields without deleting legacy fields consumed downstream.
  - Reject cross-opportunity evidence instead of reassigning it.
  - Preserve explicit verification state and never infer verification from URL presence, evidence text, or collection alone.
  - Ensure canonical research section construction carries the normalized provenance records into every verifiable section and the evidence-event collection.
  - Keep route evidence independently scoped and do not flatten route-specific evidence into another route.

- [ ] **Step 4: Verify the focused pass**
  - Run the focused provenance and research package tests.
  - Expected: normalization, rejection, verification-state, deduplication, and route-isolation tests pass.

- [ ] **Step 5: Run the affected integration check**
  - Run: `python -m pytest lead_engine/test_agent_workers.py lead_engine/test_agent_orchestrator.py`.
  - Expected: existing discovery and research-worker contracts remain green.

- [ ] **Step 6: Commit the passing deliverable**
  - Commit message: `feat: enforce canonical evidence provenance boundaries`

---

### Task 3: Safe canonical research merging and package integrity

**Files:**
- Modify: `lead_engine/research_package.py`
- Modify: `lead_engine/sales_handoff.py`
- Modify: `lead_engine/database.py` only if identity-preserving update validation requires a storage-boundary check
- Test: `lead_engine/test_research_package.py` or the repository's existing research-package test location, plus focused sales-handoff tests

**Interfaces:**
- Consumes: canonical identity, normalized provenance, existing and newly generated research sections, closer package, routing state.
- Produces: merged canonical research package, stable package projection/digest, and fail-closed handoff verification.

- [ ] **Step 1: Add the focused failing tests**
  - A verified existing section survives a weaker incoming section.
  - New distinct evidence is retained alongside existing evidence.
  - Exact duplicate evidence is not duplicated.
  - A cross-opportunity evidence item cannot enter a section during merge.
  - Route-specific evidence remains route-specific after merge.
  - Package projection contains canonical identity and all approved research/provenance sections.
  - Digest is stable for semantically identical canonical packages and changes when canonical research or provenance changes.
  - Handoff verification rejects a stored package with the wrong opportunity identity even when its digest field is otherwise well-formed.

- [ ] **Step 2: Verify the relevant failure**
  - Run the focused research-package and sales-handoff tests.
  - Expected: new identity/provenance isolation assertions fail against the current merge/projection behavior.

- [ ] **Step 3: Implement the minimum behavior**
  - Validate both generated and existing package identity before merging.
  - Merge evidence through the centralized canonical evidence key.
  - Preserve verified sections and stronger verification metadata.
  - Preserve all distinct observations and their provenance.
  - Include canonical identity, identity version/derivation metadata, discovery provenance, evidence events, all five verifiable sections, gaps/unknowns, route-specific evidence, routing, and closer package in the canonical projection without removing existing package keys.
  - Keep digest calculation deterministic and based on canonicalized data.
  - Make handoff verification validate identity consistency before trusting stored package digests.

- [ ] **Step 4: Verify the focused pass**
  - Run the focused research and sales-handoff tests.
  - Expected: all merge, digest, identity, provenance, and stale-package assertions pass.

- [ ] **Step 5: Run the affected integration check**
  - Run: `python -m pytest lead_engine/test_revenue_execution.py lead_engine/test_outreach_engine.py lead_engine/test_route_handoffs.py`.
  - Expected: revenue execution, outreach, and route handoff contracts still consume the same opportunity identity.

- [ ] **Step 6: Commit the passing deliverable**
  - Commit message: `feat: preserve canonical research and handoff integrity`

---

### Task 4: Airtable identity and persistence boundary

**Files:**
- Modify: `lead_engine/research_sync.py`
- Modify: `lead_engine/sales_handoff.py` if stored-record verification needs the canonical identity fields
- Modify: `lead_engine/database.py` only if durable handoff state needs canonical identity/version persistence
- Test: focused research-sync and handoff tests

**Interfaces:**
- Consumes: canonical lead identity, complete canonical research package, package digest.
- Produces: Airtable payloads containing canonical identity and complete research/provenance, plus deterministic rejection of stale or mismatched records.

- [ ] **Step 1: Add the focused failing tests**
  - Research synchronization rejects missing canonical identity.
  - Research synchronization rejects mismatched `opportunity_id` and fingerprint.
  - Airtable payload contains canonical identity and provenance without fabricating data.
  - An existing Airtable record for another opportunity cannot be updated under the current opportunity's key.
  - A stale raw research package fails handoff verification.
  - A transient Airtable failure does not alter the local canonical identity.

- [ ] **Step 2: Verify the relevant failure**
  - Run the focused research-sync tests.
  - Expected: identity-specific Airtable assertions fail before the boundary is hardened.

- [ ] **Step 3: Implement the minimum behavior**
  - Use the canonical fingerprint/opportunity ID as the stable research key while preserving existing Airtable field names.
  - Persist identity version and provenance in the raw canonical package where the existing schema cannot add dedicated fields without breaking compatibility.
  - Validate the returned record against the exact opportunity and expected package digest.
  - Keep Airtable asynchronous and non-authoritative for identity existence.
  - Do not mutate or regenerate identity in response to Airtable failures.

- [ ] **Step 4: Verify the focused pass**
  - Run the focused research-sync and sales-handoff tests.
  - Expected: identity, stale-record, mismatch, and failure-isolation tests pass.

- [ ] **Step 5: Run the affected integration check**
  - Run the repository's Airtable-related tests that do not require live credentials.
  - Expected: existing research synchronization and handoff tests remain green.

- [ ] **Step 6: Commit the passing deliverable**
  - Commit message: `feat: harden Airtable canonical opportunity persistence`

---

### Task 5: End-to-end canonical identity compatibility and production verification

**Files:**
- Modify only files proven necessary by Tasks 1 through 4
- Test: existing downstream test modules plus focused canonical-opportunity integration tests
- Workflow: `lead_engine/python-app.yml`

**Interfaces:**
- Consumes: complete canonical identity/provenance foundation.
- Produces: verified end-to-end compatibility across discovery, research, routing, queueing, Airtable persistence, handoff, outreach, and revenue execution.

- [ ] **Step 1: Add the focused end-to-end failing tests**
  - Start with a discovered opportunity and assert identity remains unchanged through research enrichment, route scoring, package creation, Airtable payload construction, and revenue execution payload generation.
  - Assert a second distinct opportunity at the same company/contact remains distinct.
  - Assert evidence from one opportunity cannot enter another opportunity's research package.
  - Assert no canonicalization path requires human approval.
  - Assert no existing source, research section, route, or durable queue item is discarded by canonicalization.

- [ ] **Step 2: Verify the relevant failure**
  - Run the focused end-to-end tests before the final integration fixes.
  - Expected: any remaining compatibility gap is exposed with the exact boundary that violates the canonical contract.

- [ ] **Step 3: Implement the minimum compatibility fixes**
  - Fix only verified boundary mismatches.
  - Do not broaden scope into unrelated lead-generation, sales psychology, follow-up, or source changes.
  - Preserve all existing downstream IDs and route-specific lifecycle state.

- [ ] **Step 4: Verify the focused pass**
  - Run all canonical identity/provenance tests.
  - Expected: the full focused suite passes with no skipped identity assertions.

- [ ] **Step 5: Run the full repository verification**
  - Run: `python -m pytest`.
  - Expected: all repository tests pass.
  - Then push the completed implementation on `main` so `lead_engine/python-app.yml` runs the same pytest command in GitHub Actions.
  - Inspect the actual workflow result and any failure logs before making a completion claim.

- [ ] **Step 6: Inspect the final diff and branch isolation**
  - Compare `main` against its pre-implementation commit.
  - Confirm only intended canonical identity/provenance files, tests, and plan/spec documentation changed.
  - Confirm `feature/gpu-fabric-foundation` remains untouched and unchanged.
  - Search changed files for placeholders, fake URLs, fabricated evidence, TODO/TBD text, and em dash/en dash characters.
  - Confirm all existing source registrations and research section names remain present.

- [ ] **Step 7: Commit the passing deliverable**
  - Commit message: `feat: complete canonical opportunity provenance foundation`

---

## Unresolved Product Decisions

None. The approved design specification settles the externally observable behavior. The implementation audit may determine that the current timestamp-inclusive fingerprint needs a compatibility-aware derivation change; that is an engineering determination governed by the approved identity contract, not a new product decision.
