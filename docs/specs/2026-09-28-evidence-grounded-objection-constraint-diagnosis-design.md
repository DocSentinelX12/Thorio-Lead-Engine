# Evidence-Grounded Objection and Constraint Diagnosis Intelligence Design

## Purpose

Build the next commercial-intelligence layer on the existing buyer intent progression and advancement architecture. The layer will diagnose the meaning behind explicit buyer objections and commercial interruptions without converting hypotheses into facts.

## Current repository evidence

The current `main` commit is `333ed263def4097a47a82e748d255759a3b4300f`.

Existing architecture already provides:
- Evidence-linked buyer intent progression in `lead_engine/buyer_intent_progression.py`.
- Advancement control in `lead_engine/buyer_intent_advancement.py`.
- Commercial psychology and underlying concern intelligence in `lead_engine/sales_closer_intelligence.py`.
- Historical concern state evolution and confirmation guards.
- Explicit distinction between `no_need` and terminal `rejected`.
- Evidence-bounded discovery after `no_need`, while terminal rejection disables persuasion.

## Design

### 1. Diagnostic evidence model

Create a focused diagnostic layer that consumes the existing conversation history, current progression state, existing objection category, existing concern hypotheses, and verified research context.

For every diagnosable interruption, produce:
- observed buyer statement
- interruption type
- diagnostic hypothesis or hypotheses
- supporting evidence references
- confidence status expressed as evidence state, not a numeric persuasion score
- confirmed versus unconfirmed distinction
- missing evidence
- single highest-value diagnostic question
- verified evidence that may be relevant
- permitted persuasion mode
- resolution criteria
- terminal-stop criteria

A hypothesis must never be emitted as a buyer-confirmed fact.

### 2. Diagnostic categories

The first implementation covers:
- no_need
- existing_solution
- timing_delay
- objection
- commercial/economic concern
- decision-process concern
- trust/proof concern
- information/fit concern

The existing opt-out and terminal rejection behavior remains authoritative and is not reopened by this layer.

### 3. No-need reasoning

A stated no-need condition remains an interruption and does not permit normal intent advancement.

The diagnostic layer distinguishes the statement from its underlying reason. It may discover whether the buyer means:
- genuinely no current need
- existing capability already satisfies the requirement
- insufficient perceived value
- timing or resource constraint
- misunderstanding of the offering
- another explicitly stated reason

The system must not assume which explanation is true.

### 4. Evidence policy

Verified research can be surfaced only when it directly addresses a diagnosed and evidence-supported concern.

The closer may challenge an objection respectfully with relevant verified facts, but may not:
- manufacture urgency
- invent scarcity
- claim an unverified ROI
- claim authority, budget, timing, pain, or commitment without evidence
- disparage an existing team or provider
- continue persuasion after an explicit opt-out or terminal rejection.

### 5. State evolution

A diagnostic hypothesis starts unconfirmed.

Later explicit conversation evidence may:
- confirm it
- reject it
- resolve it
- supersede it
- replace it with a new concern.

Ordinary polite replies do not confirm a concern.

Historical evidence remains preserved.

### 6. Integration boundary

The new diagnostic result feeds the existing advancement and closer strategy layers. It does not replace buyer intent progression, buyer signal intelligence, or existing concern evolution.

The advancement layer continues to decide whether normal progression is permitted.

The diagnostic layer supplies the closer with a more precise explanation of what must be learned or addressed next.

### 7. Testing

Tests will cover:
- each supported interruption category
- no-need versus terminal rejection
- hypothesis versus confirmed concern
- contradictory later evidence
- resolution and supersession
- evidence-reference preservation
- absence of fabricated assumptions
- diagnostic question selection
- verified-research gating
- integration with buyer intent advancement and commercial strategy.

Full-suite CI must pass before completion is claimed.

## Constraints

- Work directly on `main`.
- Do not create a branch or worktree.
- Do not delete existing production code.
- Preserve all existing architecture and behavior unless the approved enhancement requires additive integration.
- No fake URLs, placeholders, guessed evidence, or fabricated buyer facts.
- No em dashes or en dashes in generated code or documentation.
- Use small, focused changes and verify each layer before proceeding.
