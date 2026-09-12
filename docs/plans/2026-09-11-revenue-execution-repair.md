# Revenue Execution Repair Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the existing Thorio Lead Engine so every genuinely sales-eligible opportunity reaches a privileged high-ticket closer and can be autonomously contacted, followed up, routed, and converted without being lost at persistence or batch boundaries.

**Architecture:** Repair the existing specialist lifecycle instead of creating a separate sales system. The current discovery, research, qualification, verification, deduplication, routing, durable queue, lease, concurrency, and Airtable infrastructure remains authoritative where it already works. Add a canonical sales eligibility checkpoint, durable sales queue handoff, executable closer capability boundary, controlled outbound transport interface, and durable conversation/follow-up state.

**Tech Stack:** Python, existing LeadDB/SQLite queue and state persistence, existing specialist agent registry/orchestrator, existing Airtable synchronization, existing Playwright/account-auth foundation, pytest, GitHub Actions.

## Global Constraints

- Preserve the working 64 source collection workers and 128 specialist execution workers.
- Preserve bounded specialist drain rounds, adaptive specialist capacities, atomic queue claiming, leases/heartbeats, durable queue state, persistent production state, Airtable synchronization, and durable 50-record batch behavior.
- Preserve Phase 6 deduplication: only same company + same person + exact same underlying business need/opportunity is a duplicate.
- Required lifecycle: Discover -> Research -> Qualify -> Verify -> Identify Exact Opportunity -> Deduplicate -> Sales Eligibility -> Persist Checkpoint -> Select Best Revenue Path -> Privileged Closer -> Send Outreach -> Observe Response -> Conversation -> Objections/Follow-up -> Convert/Refer/Close/Stop.
- Qualification and sales eligibility are separate. `contact_communicated` must not be a qualification prerequisite.
- A qualified opportunity must not silently disappear. Nonqualifying or permanently blocked leads require durable terminal reasons.
- Multiple eligible routes are preserved. Best revenue path is pursued first. A privileged closer may dynamically switch when conversation evidence clearly supports a better route. Original route and switch evidence remain durable.
- Only the dedicated professional high-ticket sales closer capability may initiate outbound sales, continue sales conversations, handle objections, schedule/execute follow-ups, switch revenue paths, and advance conversion.
- General workers must not be able to invoke outbound transport. Enforcement must occur at the transport boundary, not only through a role-name check.
- Closers do not receive raw provider credentials. Existing account-auth safeguards remain, including ordinary authorized login and no MFA/CAPTCHA/platform-control bypass.
- Airtable is a persistence/visibility checkpoint, not a terminal business stage. Airtable sync success is never equivalent to outreach success.
- Outbound actions require durable idempotency identities and provider-result reconciliation so crash-after-send cannot cause duplicate delivery.
- Production proof must report discovered, researched, qualified, sales eligible, sales queued, sales active, outreach sent, responses received, conversations active, follow-ups executed, route switches, converted, referred, closed lost, disqualified, and orphaned qualified opportunities. `orphaned qualified opportunities == 0` is mandatory.

---

### Task 1: Establish the canonical sales eligibility and production handoff

**Files:**
- Modify: `lead_engine/active_processing.py`
- Modify: `lead_engine/agent_workers.py`
- Modify: `lead_engine/agent_registry.py` only where the registry metadata must distinguish privileged revenue execution from general processing
- Modify: `lead_engine/lead_queue_utils.py` if its outreach-readiness predicate is still used by the production handoff
- Test: `lead_engine/test_agent_workers.py`
- Test: `lead_engine/test_agent_orchestrator.py`
- Test: `lead_engine/test_lead_queue_utils.py`
- Test: add a focused sales lifecycle test under `lead_engine/test_revenue_execution.py`

**Interfaces:**
- Consumes: existing `enqueue(db, agent, payload, priority=..., dedupe_key=...)`, existing `routing()`, existing Airtable integrity result, existing qualification results, existing verified research payload.
- Produces: a durable sales-eligibility record and a production `outreach_closer` task with a stable dedupe key, without manual task injection.

- [ ] **Step 1: Add the focused failing tests**

Test a fully qualified, verified lead with a valid opportunity and contact data flowing through verification -> routing -> Airtable checkpoint -> sales eligibility -> `outreach_closer`. Assert the closer task exists without manually enqueueing it. Test that a qualified lead is not rejected merely because `contact_communicated` is false. Test that a nonqualifying lead receives a durable terminal reason and does not enter the sales queue. Test that an eligible lead with multiple routes preserves all routes while selecting one active route.

- [ ] **Step 2: Verify the relevant failure**

Run: `pytest -q lead_engine/test_agent_workers.py lead_engine/test_agent_orchestrator.py lead_engine/test_lead_queue_utils.py lead_engine/test_revenue_execution.py`

Expected: the new production-handoff assertions fail because the current chain ends at Airtable/audit and current queue readiness requires human approval semantics.

- [ ] **Step 3: Implement the minimum behavior**

Add one canonical sales-eligibility decision at the end of the verified routing/persistence path. It must evaluate existing qualification, verified opportunity/contact evidence, supported destination, and compliance state without requiring `contact_communicated`. Persist the resulting lifecycle state and enqueue `outreach_closer` using a fingerprint-based dedupe key. Preserve all eligible routes and route evidence. Make Airtable integrity a checkpoint and retain retryability when Airtable is unavailable.

Do not remove working Airtable synchronization or replace the durable queue. Do not let a 50-record sync boundary clear unsynced sales work.

- [ ] **Step 4: Verify the focused pass**

Run the same focused pytest command. Expected: production-path handoff tests pass, including multi-route preservation and nonqualifying terminal behavior.

- [ ] **Step 5: Run the affected integration check**

Run: `pytest -q lead_engine/test_agent_workers.py lead_engine/test_agent_orchestrator.py lead_engine/test_scheduler_sync_order.py lead_engine/test_scheduler_bounded_agent_limit.py lead_engine/test_lead_queue_utils.py`

Expected: existing queue/concurrency/scheduler behavior remains green while the sales handoff is now exercised by the active production chain.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add lead_engine/active_processing.py lead_engine/agent_workers.py lead_engine/agent_registry.py lead_engine/lead_queue_utils.py lead_engine/test_agent_workers.py lead_engine/test_agent_orchestrator.py lead_engine/test_lead_queue_utils.py lead_engine/test_revenue_execution.py
git commit -m "feat: hand qualified opportunities to sales queue"
```

---

### Task 2: Enforce the privileged closer and add idempotent outbound execution

**Files:**
- Modify: `lead_engine/agent_workers.py`
- Modify: `lead_engine/agent_registry.py`
- Modify: `lead_engine/outreach_engine.py`
- Create: `lead_engine/revenue_execution.py`
- Modify: `lead_engine/agent_queue.py` only if durable action/retry metadata requires an existing queue extension
- Modify: `lead_engine/account_auth.py` only where transport adapters need the existing secure session interface
- Test: `lead_engine/test_agent_workers.py`
- Test: add/update `lead_engine/test_revenue_execution.py`
- Test: add `lead_engine/test_revenue_transport.py`

**Interfaces:**
- Consumes: `build_outreach_decision(lead)`, durable sales-eligible lead state, existing account-auth session material, closer worker context.
- Produces: `RevenueExecutionInterface` with an authorized send operation and durable outbound action record containing opportunity, conversation, execution capability, idempotency key, channel, and provider result.

- [ ] **Step 1: Add the focused failing tests**

Test that a general worker cannot invoke the outbound interface. Test that a dedicated closer can invoke it. Test that a successful send records a durable action and delivery result. Test that the same idempotency key cannot send twice. Test a simulated crash after provider acceptance and before local completion, then retry and assert no second provider send occurs. Test missing/expired authentication as a retryable transport condition rather than a silent success.

- [ ] **Step 2: Verify the relevant failure**

Run: `pytest -q lead_engine/test_revenue_execution.py lead_engine/test_revenue_transport.py lead_engine/test_agent_workers.py`

Expected: transport tests fail because the current closer only prepares drafts and no privileged outbound transport interface exists.

- [ ] **Step 3: Implement the minimum behavior**

Create a narrow revenue execution interface between the closer and channel adapters. The interface must verify the caller's privileged closer capability, reject general workers, use an idempotency identity derived from the durable opportunity/conversation/action, and persist action state before/after transport so recovery can reconcile provider acceptance. Keep raw credentials inside the transport/account-auth boundary.

Use controlled transport implementations in tests. The production interface must be ready for authorized account adapters without bypassing platform security. Update the closer so a sales-eligible opportunity progresses from decision/draft into an actual authorized send result instead of stopping at `prepare_outreach`.

- [ ] **Step 4: Verify the focused pass**

Run the same focused pytest command. Expected: unauthorized callers are rejected, closer sends succeed through the controlled transport, and replay/crash tests produce exactly one outbound delivery.

- [ ] **Step 5: Run the affected integration check**

Run: `pytest -q lead_engine/test_agent_workers.py lead_engine/test_workforce_contracts.py lead_engine/test_agent_orchestrator.py lead_engine/test_revenue_execution.py lead_engine/test_revenue_transport.py`

Expected: the closer is still registered and schedulable, but only the privileged execution boundary can send.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add lead_engine/agent_workers.py lead_engine/agent_registry.py lead_engine/outreach_engine.py lead_engine/revenue_execution.py lead_engine/agent_queue.py lead_engine/account_auth.py lead_engine/test_agent_workers.py lead_engine/test_workforce_contracts.py lead_engine/test_revenue_execution.py lead_engine/test_revenue_transport.py
git commit -m "feat: enforce privileged revenue execution"
```

---

### Task 3: Make conversations and follow-ups durable and autonomous

**Files:**
- Modify: `lead_engine/outreach_engine.py`
- Modify: `lead_engine/agent_workers.py`
- Create: `lead_engine/revenue_conversation.py`
- Modify: `lead_engine/agent_queue.py` if durable follow-up scheduling/retry metadata requires it
- Modify: `lead_engine/scheduler.py` only where durable due follow-up execution must be included in the existing bounded cycle
- Test: `lead_engine/test_agent_workers.py`
- Test: add `lead_engine/test_revenue_conversation.py`
- Test: add/update `lead_engine/test_scheduler_bounded_agent_limit.py`

**Interfaces:**
- Consumes: outbound delivery results, inbound provider events, current conversation state, `apply_outcome()`, objection classification/response logic, preserved route list.
- Produces: durable conversation events, next-state transitions, follow-up tasks, conversion/referral/closed-lost terminal outcomes, and evidence-backed route switches.

- [ ] **Step 1: Add the focused failing tests**

Test successful response -> conversation active. Test objection -> closer-generated response and durable next state. Test no response -> durable follow-up due state. Test follow-up execution after scheduler restart. Test positive conversion -> `converted` or `referred`. Test opt-out/decline -> terminal state with no future follow-up. Test a conversation that starts on Shiftr and later switches to Paxus when supplied evidence makes Paxus clearly better, while retaining Shiftr as historical route. Test duplicate inbound event does not duplicate conversation transition.

- [ ] **Step 2: Verify the relevant failure**

Run: `pytest -q lead_engine/test_revenue_conversation.py lead_engine/test_agent_workers.py lead_engine/test_scheduler_bounded_agent_limit.py`

Expected: current outreach state can record outcomes but cannot durably ingest/provider-identify conversations or autonomously execute a real follow-up action.

- [ ] **Step 3: Implement the minimum behavior**

Add a durable conversation model keyed to opportunity and conversation identity. Persist inbound/outbound events, response classification, active route, preserved alternatives, next action, next follow-up timestamp, and route-switch evidence. Make follow-up work queue-backed and reclaimable. Reuse existing cadence/objection logic rather than duplicating it. Route switching is only permitted to the privileged closer and requires explicit conversation evidence. All inbound events must be idempotent.

Integrate due follow-up processing into the existing scheduler/orchestrator without creating an unbounded new worker pool or bypassing the existing 128 specialist ceiling.

- [ ] **Step 4: Verify the focused pass**

Run the focused conversation/scheduler pytest command. Expected: response, objection, follow-up, conversion, opt-out, route switch, restart, and duplicate-event tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `pytest -q lead_engine/test_agent_workers.py lead_engine/test_agent_orchestrator.py lead_engine/test_scheduler_bounded_agent_limit.py lead_engine/test_scheduler_sync_order.py lead_engine/test_revenue_execution.py lead_engine/test_revenue_conversation.py`

Expected: existing scheduler ordering and bounded execution remain intact while due revenue work resumes durably.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add lead_engine/outreach_engine.py lead_engine/agent_workers.py lead_engine/revenue_conversation.py lead_engine/agent_queue.py lead_engine/scheduler.py lead_engine/test_agent_workers.py lead_engine/test_revenue_conversation.py lead_engine/test_scheduler_bounded_agent_limit.py lead_engine/test_scheduler_sync_order.py
git commit -m "feat: persist autonomous sales conversations"
```

---

### Task 4: Prove the complete production revenue lifecycle and remove stale blockers

**Files:**
- Modify: `lead_engine/work_queue.py` where its documented/implemented no-autonomous-outreach assumption conflicts with the canonical lifecycle
- Modify: `lead_engine/lead_queue_utils.py` only where stale approval-only readiness blocks sales eligibility
- Modify: legacy `lead_engine/lead_pipeline_utils.py` or related legacy lifecycle code only where it can terminate/block the canonical autonomous path
- Modify: `lead_engine/cli.py` and/or production verification workflow where production metrics currently stop at sync
- Create: `lead_engine/test_revenue_production_proof.py`
- Modify: existing production verification tests as needed

**Interfaces:**
- Consumes: all canonical lifecycle states, queue task results, transport records, conversation records, Airtable checkpoint state.
- Produces: end-to-end production proof metrics and invariant checks, including zero orphaned qualified opportunities.

- [ ] **Step 1: Add the focused failing tests**

Build a controlled full lifecycle fixture that starts with a discoverable lead and runs through research, qualification, verification, exact opportunity identification, deduplication, sales eligibility, persistence, route selection, closer send, response, follow-up, and conversion/referral. Assert no manual closer injection is used. Add failure fixtures for worker crash, lease expiry, Action/run boundary, Airtable outage, provider timeout after acceptance, and 50-record batch boundary. Assert all recover without orphaning the opportunity.

- [ ] **Step 2: Verify the relevant failure**

Run: `pytest -q lead_engine/test_revenue_production_proof.py`

Expected: the current production proof fails because it verifies source/engine/Airtable synchronization but not actual sales execution and conversation outcomes.

- [ ] **Step 3: Implement the minimum behavior**

Update production verification to report every required revenue-stage metric separately. Remove or revise stale documentation/logic that explicitly says outreach is never automatic or treats Airtable as the terminal qualification stage. Preserve legacy utilities only when they remain compatible with the canonical lifecycle. Add explicit orphan detection that finds every qualified/sales-eligible opportunity lacking a durable sales queue, active conversation, or terminal reason.

Run full-suite production verification after the targeted proof is green.

- [ ] **Step 4: Verify the focused pass**

Run: `pytest -q lead_engine/test_revenue_production_proof.py`

Expected: the complete controlled lifecycle passes and `orphaned qualified opportunities == 0`.

- [ ] **Step 5: Run the full regression suite**

Run: `pytest -q`

Expected: all existing tests plus the new revenue lifecycle tests pass. No source, queue, concurrency, deduplication, Airtable, or durable-sync regression appears.

- [ ] **Step 6: Run the production proof workflow**

Run the repository's existing production verification workflow against the fixed commit. The final report must show the revenue metrics listed in the approved design, with actual outbound send count and downstream conversation outcomes separated from Airtable sync count.

Expected: production execution demonstrates that sales-eligible opportunities are handed to the closer, outbound actions are authorized and durable, follow-ups resume after run boundaries, and no qualified opportunity is orphaned.

- [ ] **Step 7: Commit the passing deliverable**

```bash
git add lead_engine/work_queue.py lead_engine/lead_queue_utils.py lead_engine/lead_pipeline_utils.py lead_engine/cli.py lead_engine/test_revenue_production_proof.py
# Include only additional files actually changed by the proof fixes.
git commit -m "test: prove end to end revenue execution"
```

## Open decisions

No product decision remains open for the core lifecycle. The user has already selected autonomous sending/conversation, privileged high-ticket closers only, best-revenue-path-first routing with preserved alternatives, and evidence-backed dynamic route switching.

The implementation must keep the transport layer behind an interface so channel/provider-specific adapters can use the repository's existing authorized account infrastructure. The specific provider/channel adapter used by a production deployment is an engineering integration seam, not permission to bypass platform controls or invent unsupported authentication behavior.
