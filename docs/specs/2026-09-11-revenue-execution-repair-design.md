# Revenue Execution Repair Design

**Date:** 2026-09-11  
**Repository:** `DocSentinelX12/Thorio-Lead-Engine`  
**Status:** Approved design, implementation pending

## 1. Purpose

Repair the existing Thorio Lead Engine so a genuinely sales-qualified opportunity cannot terminate at persistence, synchronization, or routing. The existing discovery, research, qualification, verification, deduplication, routing, durable queue, lease, concurrency, and Airtable infrastructure remains the foundation. The repair adds the missing canonical revenue-execution lifecycle and proves it end to end.

The target is not to contact every discovered lead. The target is to ensure that every opportunity that is genuinely qualified and sales-eligible receives a durable handoff to the privileged high-ticket sales closer, is either contacted and advanced through conversation or explicitly reaches a durable terminal outcome, and can recover after crashes, provider failures, Action-run boundaries, Airtable outages, or connection loss.

## 2. Non-goals and constraints

- Do not replace the working engine with a separate sales system.
- Do not rewrite functioning source collection, durable queue, lease, concurrency, Airtable synchronization, or Phase 6 dedup infrastructure unless tests prove incompatibility.
- Preserve the 64 source collection workers and 128 specialist execution workers and their bounded execution model.
- Preserve the Phase 6 dedup invariant: only the same company + same person + exact same underlying business need/opportunity is a duplicate. Similar needs at different companies are not duplicates.
- Do not require human approval for autonomous sales execution. Safety, authorization, eligibility, and compliance checks remain mandatory.
- Only the dedicated professional high-ticket sales closer capability may perform outbound sales execution.
- Do not bypass MFA, CAPTCHA, platform restrictions, provider safeguards, or ordinary authorization requirements.

## 3. Canonical revenue lifecycle

```text
DISCOVER
  -> RESEARCH
  -> QUALIFY
  -> VERIFY
  -> IDENTIFY EXACT OPPORTUNITY
  -> DEDUPLICATE
  -> SALES ELIGIBILITY
  -> PERSIST CHECKPOINT
  -> SELECT BEST REVENUE PATH
  -> PRIVILEGED HIGH-TICKET CLOSER
  -> SEND OUTREACH
  -> OBSERVE RESPONSE
  -> CONVERSATION
  -> OBJECTIONS / FOLLOW-UP
  -> CONVERT / REFER / CLOSE / STOP
```

The durable lifecycle states are:

`discovered`, `researching`, `researched`, `qualifying`, `qualified`, `opportunity_identified`, `dedup_checked`, `sales_eligible`, `sales_queued`, `sales_active`, `outreach_sent`, `awaiting_response`, `conversation_active`, `follow_up_due`, `converted`, `referred`, `closed_lost`, `disqualified`, `stopped`.

Every state transition must be durable and attributable to the responsible worker/action. A qualified opportunity cannot disappear merely because a worker exits, a production run ends, an Airtable request fails, or a sync batch limit is reached.

## 4. Qualification and sales eligibility

Qualification answers: **Is there a legitimate business opportunity?**

Sales eligibility answers: **Is there enough verified evidence, contact/routing information, authorization, and compliance state for a privileged closer to act?**

These are separate gates.

`contact_communicated` must not be required to qualify a lead. It is a downstream communication outcome and currently creates a circular dependency when used as a prerequisite for communication itself.

A nonqualifying lead may terminate, but the engine must persist the reason. A qualified lead that is temporarily not sales-eligible must remain durable and retryable or have an explicit terminal reason. It must not silently disappear.

## 5. Production handoff into sales

The active production chain must explicitly hand off every sales-eligible opportunity to the sales queue. Manual/test injection is insufficient.

Required production path:

`qualification/verification/opportunity/dedup -> sales eligibility -> durable persistence checkpoint -> sales queue -> privileged closer`

Airtable synchronization is a persistence/visibility checkpoint, not a terminal business stage. Successful Airtable sync must never be reported as equivalent to outreach, and Airtable failure must not orphan the opportunity.

## 6. Revenue path selection

A lead can have multiple eligible destinations. When that occurs:

1. Rank the eligible paths by expected/current revenue value and fit.
2. Select the best current revenue path as the active path.
3. Preserve every other eligible path as a durable alternative.
4. Pursue the active path first.
5. Allow the privileged closer to dynamically switch to a preserved path when live conversation evidence clearly demonstrates that it is a better fit.
6. Preserve the original path, switch evidence, route history, and remaining eligible alternatives.
7. A preserved alternative is never treated as a duplicate.

Example:

`eligible_routes = [shiftr, paxus, thorio]`  
`active_route = shiftr`  
`preserved_routes = [paxus, thorio]`

A later evidence-backed switch to Paxus changes the active route while retaining the original Shiftr route and the reason for switching.

## 7. Privileged closer boundary

The closer is a privileged revenue execution capability, not merely another general specialist role.

Only the dedicated professional high-ticket sales closer may:

- initiate outbound communication;
- send sales messages;
- continue a sales conversation;
- classify and respond to objections;
- schedule and execute follow-ups;
- switch revenue paths based on conversation evidence;
- advance an opportunity toward conversion;
- mark a conversion/referral/closed-lost terminal outcome.

Research, qualification, verification, routing, persistence, auditing, and monitoring workers must not be able to invoke outbound transport.

The boundary must be executable and enforced at the outbound transport interface. A role-name check alone is insufficient. The transport must reject unauthorized execution contexts.

The closer must never receive raw provider credentials. It requests an authorized transport action through a controlled revenue-execution interface.

## 8. Outbound transport

The existing outreach engine is a decision and cadence layer, not a transport implementation. The repaired architecture must separate decisioning from transport:

`privileged closer -> revenue execution interface -> authorized transport adapter -> channel/provider -> delivery result`

Transport adapters own credentials, authentication, channel-specific rules, rate limits, provider identifiers, and provider responses. Existing account-auth safeguards remain in force.

Every outbound action must have a durable idempotency identity. If a worker crashes after a provider accepts a message but before the local completion record is written, retry logic must reconcile the durable action/provider result rather than sending a duplicate.

## 9. Durable conversation model

The engine must persist, at minimum:

- opportunity identifier;
- conversation identifier;
- active revenue path;
- preserved eligible paths;
- outbound and inbound message records;
- timestamps;
- provider/channel delivery identifiers and results;
- response classification;
- objection/conversation state;
- next action;
- next follow-up time;
- route-switch evidence;
- conversion/referral/closed-lost outcome;
- retry state and failure reason where applicable.

Crash/restart must resume from durable conversation state. An Action run ending must not terminate an active conversation.

## 10. Follow-up and response handling

A positive response, objection, no response, or other supported inbound event must transition the durable conversation to the appropriate next state. Follow-up work must be scheduled from durable state, not from in-memory process lifetime.

Transient provider or processing failures remain retryable. Worker crashes or expired leases make work reclaimable. Terminal business outcomes are explicit and durable.

## 11. Queue and batch durability

A sync or processing limit is a batch limit only. For example, syncing 50 records from a backlog of 6,637 must leave the remaining 6,587 records durably queued for later processing. No run-end cleanup may interpret the batch limit as completion.

The same invariant applies to sales queue work, follow-ups, and conversation events.

## 12. Existing infrastructure to preserve

The implementation must preserve and build on:

- source collection workers and source health logic;
- the 64 source worker configuration;
- the 128 specialist worker configuration;
- bounded specialist drain rounds;
- adaptive specialist role capacities;
- atomic queue claiming;
- leases/heartbeats and durable queue state;
- persistent production state;
- durable 50-record sync behavior;
- Airtable synchronization and integrity checks;
- Phase 6 exact deduplication behavior;
- multi-route preservation already supported by the engine;
- existing account authentication safeguards.

## 13. Known blockers that this design must repair

### 13.1 No production qualified-to-closer handoff

`outreach_closer` exists in the registry, but the active production chain does not enqueue it after qualification. Existing tests manually inject closer work, which does not prove production behavior.

### 13.2 Closer prepares instead of sending

The current closer records an outreach decision/draft and returns `prepare_outreach`. It does not execute outbound transport. The missing transport layer must be implemented behind the privileged boundary.

### 13.3 Human approval gate conflicts with autonomous mode

Current delivery readiness requires `delivery_status == approved`. Autonomous B requires machine-verifiable sales eligibility rather than an accidental human-approval dependency. Existing safety and compliance gates remain; the sales eligibility state becomes the authoritative autonomous gate.

### 13.4 Weak workforce boundary

Closer/follow-up currently exist among general processing roles. They need an executable privileged capability boundary at the transport layer.

### 13.5 Airtable is incorrectly treated as terminal persistence

Airtable integrity currently terminates the automated qualification chain. It must become a checkpoint while the durable opportunity continues into sales execution.

### 13.6 Qualification/communication circular dependency

Communication is currently used as a qualification prerequisite in places while communication itself is downstream. This must be split into qualification and sales eligibility.

### 13.7 Research verification deadlock

Company research can observe a decision maker but does not clearly provide a normal production handoff to verified status. The research/verification path must have a deterministic production transition or an explicit durable reason for remaining blocked.

### 13.8 Qualification B is not independent

Qualification B currently repeats the same qualification logic instead of independently challenging the evidence. The repair should make the second validation meaningful without introducing unnecessary architecture.

### 13.9 Legacy lifecycle conflicts with active autonomous chain

The legacy `LeadPipeline` still describes human qualification and Airtable approval as central stages. The implementation must identify the authoritative canonical lifecycle and prevent stale legacy assumptions from terminating or blocking autonomous revenue execution.

### 13.10 Delivery score and qualification are conflated

A lead can be genuinely qualified while failing a separate delivery score threshold. Sales eligibility must explicitly distinguish business qualification from prioritization/eligibility rather than silently discarding qualified opportunities.

## 14. Failure recovery

Every asynchronous revenue action must be safe under:

- worker crash;
- lease expiry;
- scheduler/process restart;
- Action run termination;
- transient provider failure;
- duplicate/replayed inbound event;
- Airtable outage;
- connection loss;
- provider timeout after possible acceptance;
- batch/run limits.

Outbound operations require idempotency and reconciliation. Queue state must remain durable. Failed work must be classified as retryable or terminal, never silently dropped.

## 15. Security and authorization

- Only the dedicated closer capability can execute outbound sales transport.
- The transport layer enforces the capability boundary independently of caller intent.
- Raw credentials remain outside closer logic.
- Provider authentication, rate limits, MFA, CAPTCHA, and platform safeguards are respected.
- No mechanism may be added to bypass platform controls.
- Audit records must identify the authorized execution context and action result.

## 16. Production proof requirements

Green CI alone is insufficient. The repaired system must prove the actual revenue lifecycle.

### Unit tests

Cover qualification/eligibility, exact dedup, route preservation, route ranking, route switching evidence, closer authorization, transport authorization, idempotency, durable conversation state, retries, and follow-ups.

### Integration tests

Prove without manual injection:

`discovery -> research -> qualification -> opportunity -> dedup -> eligibility -> sales queue -> closer`

### Transport tests

Use controlled/mock transports to prove successful send, provider failure, authorization rejection, and crash-after-send without duplicate delivery.

### Conversation tests

Prove positive response, objection handling, follow-up scheduling/execution, route switching, conversion/referral, no-response, and closed-lost behavior.

### Failure tests

Exercise worker crash, lease recovery, queue restart, transport failure, duplicate inbound event, Airtable outage, scheduler/run termination, and sync batch boundaries.

### Production proof metrics

The production verification must report at least:

- discovered;
- researched;
- qualified;
- sales eligible;
- sales queued;
- sales active;
- outreach sent;
- responses received;
- conversations active;
- follow-ups executed;
- route switches;
- converted;
- referred;
- closed lost;
- disqualified;
- orphaned qualified opportunities.

Required invariant: **orphaned qualified opportunities == 0**.

Airtable sync success must be reported separately from outreach and conversion success.

## 17. Implementation phases

Implementation should proceed surgically in these phases, with tests at each boundary:

### Phase A: Canonical revenue lifecycle

Establish authoritative durable states and transitions without removing working infrastructure.

### Phase B: Repair qualification/research gates

Remove circular communication prerequisites, repair decision-maker verification handoffs, clarify qualification versus sales eligibility, and make the second qualification pass meaningfully independent where needed.

### Phase C: Qualified-to-sales queue

Create the production handoff from sales eligibility through durable persistence into the sales queue. Make Airtable a checkpoint rather than terminal stage.

### Phase D: Privileged closer boundary

Create the executable high-ticket closer capability and enforce it at the revenue execution interface and transport boundary.

### Phase E: Outbound transport

Implement controlled channel adapters around the existing account-auth model. Persist idempotent outbound actions and provider results.

### Phase F: Response/conversation ingestion

Persist inbound events, classify responses, and resume the correct durable conversation.

### Phase G: Follow-up/conversation automation

Execute scheduled follow-ups from durable state, handle objections, preserve route alternatives, and support evidence-backed route switching.

### Phase H: Production proof

Run the full proof suite and a controlled production lifecycle verification that demonstrates qualified opportunities reach the closer and that every resulting conversation has a durable outcome.

## 18. Acceptance criteria

The repair is complete only when all of the following are true:

1. Every sales-eligible opportunity has a durable closer handoff.
2. No general worker can invoke outbound sales transport.
3. Every outbound message has a durable opportunity, conversation, authorized execution context, idempotency identity, and delivery result.
4. Active conversations always have a durable next state.
5. Multiple eligible revenue paths are preserved.
6. The best revenue path is pursued first.
7. A privileged closer can dynamically switch paths when conversation evidence justifies it.
8. Original route history and switch evidence remain durable.
9. Qualified opportunities cannot disappear because of batch limits, run termination, worker crashes, Airtable outages, or provider failures.
10. Nonqualifying or permanently blocked leads have explicit durable terminal reasons.
11. Production verification proves actual outreach and conversation lifecycle, not merely synchronization.
12. `orphaned qualified opportunities == 0`.
13. Existing source, queue, concurrency, lease, persistence, Airtable, and Phase 6 dedup behavior remains intact unless a test-backed incompatibility requires a surgical change.
