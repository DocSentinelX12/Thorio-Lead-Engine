# Research Intelligence and Evidence Graph Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an evidence-backed intelligence graph that preserves rich company, opportunity, decision-maker, commercial, route, uncertainty, and provenance context through every downstream handoff.

**Architecture:** Extend the existing canonical research package rather than creating a parallel research pipeline. The new intelligence object is opportunity-scoped, provenance-bound, deterministic, and carried through Lead persistence, sales handoff, and Airtable research synchronization.

**Tech Stack:** Python 3.10, pytest, existing LeadDB, canonical provenance, research package, sales handoff, and Airtable synchronization.

## Global Constraints

- Preserve all existing research sections and source lanes.
- Preserve canonical opportunity identity and evidence provenance.
- Never fabricate evidence, facts, contacts, URLs, timestamps, verification, or qualification.
- Observed evidence must never silently become verified.
- Conflicting evidence must remain visible.
- Stale evidence must remain durable.
- Research gaps and unknowns must remain explicit.
- Airtable remains persistence and observability, not authority for opportunity existence.
- Downstream handoffs must retain the complete intelligence object.
- Existing routing, qualification, closer, follow-up, and production gates remain intact.
- No arbitrary backlog or evidence cap.
- No human approval is introduced into upstream research processing.

---

### Task 1: Evidence graph and claim intelligence

**Files:**
- Create: `lead_engine/research_intelligence.py`
- Modify: `lead_engine/research_package.py`
- Test: `lead_engine/test_research_intelligence.py`

**Interfaces:**
- Consumes: canonical Lead identity, existing research sections, company research, decision-maker research, route research, research gaps, and evidence provenance.
- Produces: `build_research_intelligence()`, `validate_research_intelligence()`, and `merge_research_intelligence()`.

- [x] Define deterministic evidence-node collection.
- [x] Define structured company, need, decision-maker, commercial, and stakeholder profiles.
- [x] Define traceable claims and claim statuses.
- [x] Preserve conflicting claims.
- [x] Mark stale evidence without deleting it.
- [x] Reject cross-opportunity evidence.
- [x] Validate every claim reference against the evidence graph.

### Task 2: Durable Lead and research-worker integration

**Files:**
- Modify: `lead_engine/models.py`
- Modify: `lead_engine/agent_workers.py`
- Test: `lead_engine/test_agent_workers.py`

**Interfaces:**
- Consumes: canonical company-research handoff.
- Produces: persisted `research_intelligence` attached to the durable Lead.

- [x] Materialize intelligence after canonical research sections are merged.
- [x] Rebuild intelligence after final research readiness state is computed.
- [x] Persist intelligence with the Lead.
- [ ] Verify the complete worker handoff with an integration test.

### Task 3: Sales and Airtable handoff integration

**Files:**
- Modify: `lead_engine/sales_handoff.py`
- Modify: `lead_engine/research_sync.py`
- Test: `lead_engine/test_sales_handoff.py`
- Test: `lead_engine/test_research_sync.py`

**Interfaces:**
- Consumes: Lead `research_intelligence`.
- Produces: digest-bound sales package and Airtable Research record field.

- [x] Include intelligence in package projection and digest.
- [x] Include intelligence in the Research Airtable field map.
- [x] Preserve intelligence in Raw Research Package.
- [ ] Verify complete handoff integration with the production test suite.

### Task 4: Production verification

**Files:**
- No production code changes unless verification exposes a real defect.

**Checks:**
- Focused research intelligence tests.
- Full `pytest -vv -ra --tb=short --timeout=600`.
- Existing production proof workflow.
- Main branch workflow evidence.
- Verify no regressions in routing, qualification, closer, follow-up, Airtable synchronization, or canonical identity.

- [ ] Run focused tests and fix only evidence-backed failures.
- [ ] Run full test suite.
- [ ] Run production verification.
- [ ] Inspect changed files and final commit chain.
- [ ] Confirm the GPU branch remains untouched.
