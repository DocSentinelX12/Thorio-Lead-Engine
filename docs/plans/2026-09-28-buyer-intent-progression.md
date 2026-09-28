# Buyer Intent Progression Intelligence Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an evidence-linked buyer intent progression engine that tracks commercial state changes across conversation history and directly controls the closer's next-best action and question.

**Architecture:** Add a bounded buyer_intent_progression module that consumes the existing buyer-signal classifier and full conversation history, preserves every valid transition with evidence, and exposes the active state plus unresolved qualification dimensions. Integrate it into build_commercial_strategy() so progression, rather than a disconnected classifier, controls the active discovery action and question while existing objection, concern, research, and truthfulness gates remain authoritative.

**Tech Stack:** Python, existing lead_engine modules, pytest, GitHub Actions.

## Global Constraints
- Preserve verified research, evidence lineage, canonical opportunity identity, objection state, concern evolution, research re-entry, outreach, revenue routing, and existing truthfulness gates.
- Never convert inference, title, company context, silence, generic positive language, or unsupported urgency into buyer intent.
- Preserve historical progression when the active conversation state changes.
- Require explicit evidence for every progression transition.
- Keep active qualification dimensions independent: need, outcome, impact, timing, decision process, authority/participants, budget/economic criteria, existing solution, and objection state.
- Select one highest-value missing qualification dimension at a time.
- Terminal outreach states remain terminal unless explicit re-engagement evidence exists. Opt-out remains immediately terminal.
- No fake data, placeholders, weakened tests, source reduction, or fabricated commercial claims.

---

### Task 1: Add the stateful progression engine

**Files:**
- Create: lead_engine/buyer_intent_progression.py
- Test: lead_engine/test_buyer_intent_progression.py

**Interfaces:**
- Consumes: conversation_events and classify_buyer_signal(lead).
- Produces: build_buyer_intent_progression(lead) -> dict[str, Any] with current_state, history, transition, missing_qualification, next_best_action, next_best_question, and evidence lineage.

- [ ] Step 1: Add focused failing tests
- Assert generic engagement remains engaged.
- Assert explicit problem and impact statements advance only to their supported states.
- Assert evaluation language advances to evaluation.
- Assert decision participants produce decision_process evidence without assuming approval.
- Assert explicit commercial action creates commercial_commitment.
- Assert objections, timing delays, rejection, and opt-out alter the active state without deleting history.
- Assert contradictory later evidence supersedes stale active state.
- Assert re-engagement requires explicit new evidence.

- [ ] Step 2: Verify the focused failure
Run: python -m pytest lead_engine/test_buyer_intent_progression.py -q
Expected: import/function failures proving the new engine is absent.

- [ ] Step 3: Implement the minimum behavior
- Walk conversation events chronologically.
- Classify each event using explicit text and existing buyer-signal intelligence.
- Record only transitions supported by explicit evidence.
- Preserve prior states and event references in history.
- Treat objection/timing/no-need/existing-solution/rejection/re-engagement as active conditions without erasing progression history.
- Derive missing qualification from buyer-stated evidence only.
- Select one next discovery dimension according to current state.

- [ ] Step 4: Verify the focused pass
Run: python -m pytest lead_engine/test_buyer_intent_progression.py -q
Expected: all progression tests pass.

- [ ] Step 5: Run affected integration check
Run: python -m pytest lead_engine/test_closer_conversation_intelligence.py lead_engine/test_outreach_engine.py -q
Expected: existing closer and outreach tests remain green.

- [ ] Step 6: Commit the passing deliverable
git add lead_engine/buyer_intent_progression.py lead_engine/test_buyer_intent_progression.py && git commit -m "feat: add buyer intent progression engine"

### Task 2: Integrate progression into commercial strategy

**Files:**
- Modify: lead_engine/sales_closer_intelligence.py
- Modify: lead_engine/outreach_engine.py only if the existing strategy handoff requires a direct field adjustment
- Test: lead_engine/test_closer_conversation_intelligence.py
- Test: lead_engine/test_outreach_engine.py

**Interfaces:**
- Consumes: build_buyer_intent_progression(lead).
- Produces: commercial_strategy[buyer_intent_progression] and progression-driven conversation_intelligence.

- [ ] Step 1: Add focused failing integration tests
- Assert strategy exposes progression state and evidence history.
- Assert progression selects the missing qualification dimension.
- Assert the selected progression question reaches final outreach.
- Assert an objection remains governed by existing confirmed-concern logic rather than being overwritten by progression.
- Assert terminal states still stop outreach.
- Assert research re-entry remains available when buyer evidence is insufficient.

- [ ] Step 2: Verify the relevant failures
Run: python -m pytest lead_engine/test_closer_conversation_intelligence.py lead_engine/test_outreach_engine.py -q
Expected: progression fields are absent or existing action/question assertions fail.

- [ ] Step 3: Implement the minimum integration
- Import the progression engine into sales_closer_intelligence.py.
- Build progression immediately after buyer-signal intelligence.
- Let progression supply the base next-best action/question.
- Preserve confirmed-concern overrides, explicit opt-out handling, and terminal states.
- Return progression data in the commercial strategy for downstream persistence and auditing.
- Do not duplicate classification logic in outreach_engine.py.

- [ ] Step 4: Verify the focused pass
Run: python -m pytest lead_engine/test_closer_conversation_intelligence.py lead_engine/test_outreach_engine.py -q
Expected: all affected tests pass.

- [ ] Step 5: Run the broader closer suite
Run: python -m pytest lead_engine/test_closer_conversation_intelligence.py lead_engine/test_outreach_engine.py lead_engine/test_buyer_intent_progression.py -q
Expected: all progression and closer integration tests pass.

- [ ] Step 6: Commit the passing deliverable
git add lead_engine/sales_closer_intelligence.py lead_engine/test_closer_conversation_intelligence.py lead_engine/test_outreach_engine.py && git commit -m "feat: integrate buyer intent progression into closer strategy"

### Task 3: Verify production-path behavior

**Files:**
- Modify only if Task 2 exposes a concrete production-path defect.
- Test: affected existing production-path tests.

**Interfaces:**
- Consumes: the integrated commercial strategy.
- Produces: final outreach whose selected question/action matches the progression state.

- [ ] Step 1: Add only regression tests for observed production-path gaps
- Verify the final body contains the progression-selected question.
- Verify an explicit commitment does not get downgraded into generic discovery.
- Verify an objection does not get overwritten by positive historical progression.
- Verify later rejection/opt-out remains terminal.
- Verify no unsupported urgency or outcome claim appears.

- [ ] Step 2: Run the focused production-path tests
Run: python -m pytest lead_engine/test_outreach_engine.py -q
Expected: all tests pass.

- [ ] Step 3: Run the complete relevant suite
Run: python -m pytest lead_engine/test_buyer_intent_progression.py lead_engine/test_closer_conversation_intelligence.py lead_engine/test_outreach_engine.py -q
Expected: all tests pass with no weakened assertions.

- [ ] Step 4: Commit only if Task 3 changed code
git add <exact changed files> && git commit -m "test: verify buyer intent progression production path"

## Verification and completion criteria
The implementation is complete only after the progression engine is production-connected, evidence-linked history is preserved, the selected action/question reaches actual outreach, existing concern and truthfulness gates remain authoritative, and fresh CI passes on the resulting commits.

## Unresolved externally observable product decisions
None. The approved specification defines the progression states, evidence rules, non-linear states, next-best-action behavior, integration boundary, and testing requirements.