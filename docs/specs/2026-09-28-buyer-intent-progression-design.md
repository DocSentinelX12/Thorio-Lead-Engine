# Buyer Intent Progression Intelligence Design

## Purpose

Add a stateful, evidence-linked buyer intent progression layer to the existing closer intelligence architecture. The layer must reason about changes in the buyer's commercially observable state over time without converting inference, sentiment, role, company context, or generic engagement into unsupported buying intent.

## Existing architecture

The current closer already builds an evidence-grounded commercial psychology profile, conversation memory, buying-signal intelligence, underlying-concern state, next-best action and question, research re-entry decisions, and persuasion-quality checks. The new layer will sit between buying-signal intelligence and commercial strategy selection rather than replacing those components.

## Progression states

The active progression state may be one of:

- `unknown`
- `engaged`
- `problem_acknowledged`
- `impact_acknowledged`
- `evaluation`
- `decision_process`
- `commercial_commitment`
- `conversion`

The conversation may also enter explicit non-linear states:

- `objection`
- `timing_delay`
- `no_need`
- `existing_solution`
- `rejected`
- `re_engagement`

Non-linear states represent the current conversation condition and must not erase the historical progression record.

## Evidence rules

Every progression transition must contain:

- prior state
- candidate/current state
- transition type
- evidence reference
- evidence text or normalized event reference
- event index when available
- required evidence for the next progression step

A transition is valid only when supported by explicit conversation evidence or an existing verified research fact whose semantics permit that state. Company size, job title, funding, hiring volume, industry, silence, generic positive language, and inferred urgency cannot establish buyer intent.

Examples:

- `Interesting` => `engaged`, never `evaluation`.
- `Tell me more` => `engaged` or interest signal, never commitment.
- `We are comparing proposals` => `evaluation`.
- `Our CTO and VP Engineering need to approve this` => `decision_process` evidence, not proof that approval will occur.
- `Send the agreement and kickoff options` => `commercial_commitment` candidate, provided the exact event is preserved as evidence.
- A later objection changes the active conversation state without deleting the earlier evaluation evidence.

## Progression engine behavior

The engine will evaluate the full conversation history, not only the latest message. Newer explicit evidence may supersede an older active signal while preserving historical transitions.

The engine will distinguish:

- current state
- historical progression
- current buyer signals
- unresolved qualification dimensions
- next required evidence

Qualification dimensions remain independent:

- active need
- desired outcome
- business impact
- timing
- decision process
- authority/participants
- budget/economic criteria
- existing solution
- objection state

Missing dimensions remain unknown. The engine selects one highest-value missing dimension for the next action instead of dumping multiple qualification questions into the outreach.

## State transition policy

The progression engine must fail closed when evidence is insufficient. It must not advance a prospect simply because a previous state exists.

Progression can move backward in the active conversation when new evidence establishes an objection, timing delay, no need, rejection, or another non-linear condition. Historical progression remains available for context and auditing.

Terminal commercial states remain terminal unless an explicit re-engagement event is recorded. Opt-out remains immediately terminal for outreach behavior.

## Integration

The production flow becomes:

`conversation_events`

-> `buying_signal_intelligence`

-> `buyer_intent_progression`

-> `conversation_memory`

-> `underlying_concern_intelligence`

-> `commercial_strategy`

-> `next_best_action`

-> `next_best_question`

-> `final outreach/objection response`

-> `truthfulness and commercial quality gates`

The progression layer must influence the selected next-best action and question. It must not be a disconnected classifier.

## Next-best-action rules

The action engine will select the smallest useful next move based on the current state and missing evidence. Examples:

- `engaged` with no problem acknowledgment -> establish whether a real need exists.
- `problem_acknowledged` without impact -> discover the material consequence.
- `impact_acknowledged` without timing -> establish the real timing condition.
- `evaluation` without decision process -> map evaluation participants and process.
- `decision_process` without economic criteria -> establish the applicable commercial criteria without inventing a budget.
- `commercial_commitment` -> clarify the concrete commitment and execution step rather than restarting discovery.
- objection -> resolve or diagnose the objection before advancing.

No action may claim that an unknown condition is already true.

## Research re-entry

If progression requires evidence that the conversation cannot establish and verified research can legitimately provide it, the strategy may request research re-entry. Research re-entry must not be used to manufacture buyer intent. Research can establish company facts and documented context; buyer intent still requires buyer evidence unless a clearly documented external event is explicitly modeled as a separate research signal.

## Testing

Regression tests will cover:

1. Generic engagement does not advance to evaluation.
2. Explicit problem acknowledgment advances only to the problem state.
3. Explicit impact acknowledgment advances only when the impact is actually stated.
4. Evaluation language creates evaluation evidence.
5. Decision participants create decision-process evidence without assuming approval.
6. Concrete commercial action creates a commitment candidate with evidence.
7. Objections interrupt active progression without deleting history.
8. Timing delays interrupt progression without manufacturing urgency.
9. Rejection and opt-out are handled as terminal active states.
10. Re-engagement requires explicit evidence.
11. Contradictory later evidence supersedes stale active signals while preserving history.
12. The next-best question corresponds to the highest-value missing qualification dimension.
13. The selected question reaches the final outreach body.
14. Unsupported progression is rejected by the quality gate.
15. Existing truthfulness, concern-state, research-reentry, objection-response, and revenue-path tests remain intact.

## Scope boundaries

This design does not replace the existing sales closer, research system, Airtable delivery, revenue routing, follow-up system, or truthfulness gates. It adds a bounded reasoning layer and integrates it into the existing strategy path.

## Success criteria

The implementation is complete only when the progression engine is used by production strategy generation, its evidence lineage is preserved, its next-best action reaches actual outreach, and the full relevant test suite passes without weakening existing gates or replacing verified evidence with inference.
