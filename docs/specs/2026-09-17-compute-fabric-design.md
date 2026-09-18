# Thorio Lead Engine: Distributed Compute Fabric Design Specification

Status: approved design specification
Date: 2026-09-17
Repository: DocSentinelX12/Thorio-Lead-Engine
Branch: feature/gpu-fabric-foundation

## Purpose

This specification consolidates the seventeen approved design sections for extending the Thorio Lead Engine into a provider-neutral, NVIDIA-premier distributed compute fabric.

The objective is to add substantial distributed CPU/GPU execution capacity while preserving the existing Thorio application, business authority, durable backlog, research and evidence truth, qualification, routing, Airtable, referral, commission, revenue, and Partnership boundaries.

This document is the canonical design record for the approved architecture. Implementation must follow this specification unless a later explicit design change is approved.

## Permanent engineering rules

1. Never use pull requests for this project. Changes are developed on the approved isolated branch and integrated only through an explicitly approved direct branch workflow.
2. Inspect the complete dependency chain before changing code.
3. Make the smallest surgical change that addresses a verified root cause.
4. Never chase green tests. A test result is evidence, not the design authority.
5. Never modify tests merely to obtain green CI.
6. Never claim fixed, complete, or production-ready without fresh verification evidence.
7. Existing production behavior is protected by default.
8. No destructive migration, fake resource, placeholder production path, temporary bypass, or simulated capacity presented as real.
9. Batch size is a processing limit, never a completion cap.
10. Authorized business work remains durable until authoritative completion.
11. Compute is an execution substrate, never a second source of business truth.
12. Missing hardware or evidence is represented as missing, never fabricated.
13. Legitimate provider use only. No quota, CAPTCHA, authentication, account, or policy circumvention.
14. Android is the operator control surface, not a required compute node.
15. The user personally enters the workflow after a genuine revenue-positive action to place the verified handoff into Partnerships.
16. High-ticket specialist closers are intended to conduct the full authorized outreach conversation, follow-up, and objection handling autonomously through the revenue-positive action.
17. Any existing subsystem change requires inspection and an explicit explanation of current behavior, dependencies, incompatibility, smallest required change, risks, and verification before modification.

## 1. Supercomputer fabric

The architecture is a hierarchical distributed compute fabric, not a flat worker pool.

The conceptual hierarchy is:

    THORIO CONTROL PLANE
             |
       GLOBAL SCHEDULER
             |
     RESOURCE ORCHESTRATOR
       /       |       \
   DOMAIN A  DOMAIN B  DOMAIN C
      |         |         |
   many nodes many nodes many nodes
      |         |         |
   many GPUs  many GPUs  many GPUs
       \        |        /
        DISTRIBUTED EXECUTION
                |
        VERIFIED RESULTS
                |
       THORIO AUTHORITATIVE STATE

There is no fixed architectural ceiling on nodes, GPUs, workers, or cells. Actual limits come from available resources, provider policy, scheduler/storage/network capacity, and workload constraints.

A node is a container and topology domain. Individual GPUs are independently addressable scheduling resources.

The compute fabric remains beneath the Thorio application and does not replace its business authority.

Android is the control surface only. Phone disconnection must not stop compute or durable work.

## 2. Compute providers and legitimate free compute

A dedicated Compute Provider Layer normalizes heterogeneous resources into the common Thorio resource contract.

Supported provider categories include:

- NVIDIA and NVIDIA-backed resources
- legitimate cloud/free-credit resources
- legitimate free GPU environments such as ephemeral notebook environments
- donated or community resources
- user-controlled/local machines
- other legitimate providers

NVIDIA is the premier compute path, particularly for CUDA and distributed GPU workloads.

Provider adapters normalize:

- identity
- capability
- availability
- lifetime
- health
- topology evidence
- authentication state
- provider-specific constraints

Ephemeral resources are first-class resources with explicit lifetime and reliability characteristics. They are not treated as permanent infrastructure.

The system must not require the user to manually hunt for and configure resources as normal operation. Where a provider requires user eligibility or authorization, that requirement is surfaced rather than circumvented.

The architecture assumes software and orchestration should use free/open-source components where practical. It does not promise unlimited free physical compute because provider availability, quotas, eligibility, and hardware are externally controlled.

## 3. Global scheduler and workload orchestration

There is one global scheduling brain over the distributed fabric.

The existing authoritative Thorio queue remains authoritative. Existing execution/transport tables remain execution layers and must not become a second authoritative queue.

Every workload expresses applicable requirements including:

- CPU
- RAM
- GPU count
- GPU VRAM
- compute capability
- CUDA
- driver
- NCCL
- topology
- network
- storage
- workload class
- checkpointing
- timeout
- retry behavior
- priority and scheduling constraints

The scheduler supports:

- CPU-only
- single-GPU
- multi-GPU
- multi-node GPU
- hybrid CPU/GPU
- I/O-heavy work

Multi-GPU allocation is concrete physical GPU allocation. GPU count never means aggregate VRAM.

Multi-node workloads use actual resources on multiple nodes and must satisfy their distributed communication requirements.

The scheduler may consider priority, fairness, efficiency, deadlines, resource lifetime, topology, and workload fit, but it cannot bypass Thorio business authorization.

The scheduler supports preemption and recovery where workload/checkpoint semantics permit it.

Reconciliation compares authoritative Thorio work, scheduler state, execution attempts, leases, resources, results, and authoritative acceptance.

Batch size remains a processing control only.

## 4. NVIDIA high-performance execution fabric

NVIDIA is the premier path for high-performance execution.

The resource and scheduling layers must represent and use, where actually available and required:

- CUDA
- CUDA runtime/library compatibility
- GPU VRAM
- compute capability
- driver compatibility
- NCCL
- PCIe
- NVLink
- NVSwitch
- high-speed network paths
- topology domains

The workload model supports:

- single-GPU CUDA execution
- multi-GPU execution
- multi-node GPU execution
- hybrid CPU/GPU execution

Topology discovery is evidence for placement, not proof of performance. Actual distributed communication capability must be verified when required.

Large immutable inputs and outputs should use artifact references rather than copying large payloads through the control plane.

Long-running workloads may use checkpoints and resume.

More GPUs do not automatically imply linear throughput. Communication, topology, workload shape, storage, and network limits remain scheduling concerns.

## 5. Durable distributed execution and failure handling

Business work identity is separate from execution attempt identity.

Execution uses:

- leases
- generations/attempts
- heartbeats
- expiration
- retry policy
- idempotency
- checkpointing where appropriate
- artifact references
- reconciliation

A worker failure, GPU outage, node loss, provider disappearance, scheduler restart, network partition, or lease expiration must not imply business-work completion or deletion.

The execution table is a transport/lease mechanism only. The existing authoritative Thorio queue/state layer remains authoritative.

Exactly-once external side effects cannot be assumed. Existing authoritative idempotency and reconciliation boundaries must protect against duplicates.

Repeated failures may quarantine work as poison/blocked while preserving the work and evidence needed for diagnosis and recovery.

Android should report meaningful failure/recovery state without requiring the user to interpret infrastructure logs.

## 6. Continuous autonomous operation

The operating loop is:

    Observe
      -> Reconcile
      -> Schedule
      -> Execute
      -> Verify
      -> Recover
      -> Repeat

There is no artificial finish line.

The system continuously monitors:

- authoritative backlog
- active executions
- leases
- heartbeats
- resources
- providers
- source collection
- research
- evidence
- qualification
- deduplication/opportunity resolution
- Partnership Path
- specialist workloads
- Airtable synchronization
- failures/retries
- user-required actions

Provider disappearance, stale execution state, expired leases, and synchronization failures are normal recovery conditions.

Automatic recovery is attempted before requesting user action.

## 7. Surgical integration with the existing Thorio engine

The existing Thorio engine remains authoritative.

The compute fabric is additive and sits underneath it.

Protected systems include:

- agent_queue
- durable backlog/completion semantics
- source collection
- research
- evidence
- qualification
- need/intent analysis
- late-stage deduplication
- opportunity resolution
- Partnership Path
- specialist routing
- Airtable synchronization
- referral attribution
- commission/revenue state
- existing authentication
- existing production workflows

No protected subsystem is rewritten merely because a new architecture could be cleaner.

New capability should connect through adapters and existing interfaces wherever possible.

Before changing an existing component, the implementation must document its current behavior, dependencies, authority, exact incompatibility, smallest change, risk, and verification.

## 8. Self-monitoring, verification, and Android control

The system must distinguish:

- healthy
- monitoring/recovering
- action required
- complete
- partial
- failed
- retrying
- blocked
- awaiting resource
- awaiting dependency
- verified
- rejected

The Android control surface presents business-first status:

- overall health
- durable backlog
- research
- evidence
- qualification
- opportunities
- specialist activity
- compute health/capacity
- Airtable synchronization
- revenue-positive actions
- required user actions

Raw infrastructure diagnostics remain available at deeper diagnostic levels but are not required for normal operation.

The dashboard cannot manufacture green status. Every displayed state must be backed by actual system evidence.

## 9. End-to-end data and execution integrity

The complete business flow is:

    Discovery
      -> Durable Backlog
      -> Research
      -> Evidence Collection
      -> Full Qualification
      -> Need/Intent Analysis
      -> Deduplication + Opportunity Resolution
      -> Partnership Path
      -> Complete Specialist Package
      -> Specialist High-Ticket Closer
      -> Outreach
      -> Conversation
      -> Follow-Up
      -> Objection Handling
      -> Genuine Revenue-Positive Action
      -> User
      -> Partnership Placement

Every stage must receive the information required by its contract and preserve provenance.

Provenance follows:

    Claim -> Evidence -> Source -> Verification State -> Timestamp

Execution results must be attributable to business work, execution attempt, resource, lease/generation, result, verification, and authoritative acceptance.

No silent partial success is allowed.

A complete specialist package is a hard gate.

A revenue-positive action cannot be fabricated.

Partnership placement is never automatic.

## 10. Security, isolation, and trust boundaries

Compute workers are treated as untrusted execution environments.

Sensitive credentials remain outside ordinary compute workloads.

Provider-specific isolation occurs through adapters.

Compute cannot independently create or alter:

- canonical lead state
- evidence truth
- qualification authority
- Partnership Path authority
- Airtable truth
- referral attribution
- commission state
- revenue state
- Partnership placement
- unauthorized outreach authority

Provider policy boundaries are absolute.

Worker or provider failure must not take authoritative business state down.

## 11. Scaling without architectural ceilings

The scheduler considers actual:

- GPU model
- VRAM
- CUDA
- driver
- compute capability
- CPU
- RAM
- storage
- network
- PCIe
- NVLink
- NVSwitch
- NUMA
- NCCL
- topology
- reliability
- provider lifetime
- workload requirements

The fabric is dynamically extensible.

There is no six-cell, six-GPU, or similar artificial ceiling.

Ephemeral resources are first-class.

Scaling increases execution capacity and throughput. It does not redefine business completion.

## 12. Verification, observability, and auditability

Verification is layered:

1. Unit
2. Contract
3. Integration
4. Pipeline
5. Production

A passing unit or integration test is never treated as proof of end-to-end production correctness.

Every execution has an audit chain:

    Business Work ID
      -> Execution Attempt
      -> Lease ID + Generation
      -> Provider
      -> Domain
      -> Node
      -> Physical Resource(s)
      -> Workload
      -> Checkpoint/Artifacts
      -> Result
      -> Verification
      -> Authoritative Acceptance

The system must distinguish:

- test passed
- component healthy
- integration verified
- execution succeeded
- result verified
- authoritative state updated
- downstream stage received the result
- entire business workflow completed

Failure evidence must survive failure.

Cross-layer reconciliation detects impossible states without becoming a new source of business truth.

Examples that must be detectable include:

- authoritative work exists with no execution state
- scheduler thinks work is active but worker disappeared
- lease expired while execution still reports running
- result exists without authoritative acceptance
- authoritative state says complete while execution says incomplete
- resource reports available while quarantined
- synchronization reports success without corresponding evidence

## 13. Provider and resource lifecycle

Resource lifecycle:

    DISCOVERED
      -> PROBING
      -> HEALTHY
      -> AVAILABLE
      -> RESERVED
      -> LEASED
      -> EXECUTING
      -> RELEASED
      -> AVAILABLE

Failure path:

    HEALTHY/AVAILABLE/EXECUTING
      -> DEGRADED
      -> QUARANTINED
      -> RE-PROBE/RECOVER
      -> AVAILABLE

A resource has evidence-based identity and capabilities.

A worker process is not the same as a physical GPU.

If one GPU fails, other healthy GPUs on the node remain independently usable where safe.

Temporary resources carry expected lifetime information.

Provider disappearance stops new allocation, recovers active work, preserves durable state, and reschedules eligible work.

NVIDIA-specific capability evidence includes CUDA, VRAM, compute capability, driver, NCCL where required, and topology.

A multi-GPU request for four GPUs requires four compatible physical GPUs.

A multi-node request requires actual resources on multiple nodes.

No provider may be admitted based on fabricated or assumed capabilities.

## 14. Workload contracts and full pipeline connection

Each compute-enabled workload receives a structured contract containing, as applicable:

- business work ID
- workload ID
- execution attempt
- workload class
- priority
- required capabilities
- CPU/RAM/GPU requirements
- CUDA/driver/NCCL requirements
- topology/network/storage requirements
- timeout
- checkpoint policy
- retry policy
- input artifact references
- output contract
- authorization boundary
- verification requirements

Compute can accelerate authorized computational stages, including source processing, research, evidence processing, qualification support, need/intent analysis, late-stage deduplication, opportunity resolution, Partnership Path support, specialist package preparation, and specialist reasoning.

Compute cannot become the business decision-maker.

### Specialist closer contract

The specialist package should contain, as applicable:

- unique opportunity identity
- source/discovery information
- company identity and context
- relevant decision makers and verified contact information
- evidence and provenance
- need/intent
- Partnership Path and qualifying conditions
- sales intelligence
- conversation history
- objections
- follow-up state
- authorization
- relevant commercial information

The specialist is intended to operate autonomously through:

    Complete Package
      -> Outreach
      -> Conversation
      -> Response Analysis
      -> Follow-Up
      -> Objection Handling
      -> Continued Follow-Up
      -> Genuine Revenue-Positive Action

The specialist cannot declare revenue-positive merely because a message was sent, opened, replied to, or a prospect expressed vague interest.

### Existing closer boundary

The current implementation of:

- closer routing
- outreach_closer
- follow_up
- outbound transport
- authentication
- authorization
- sent-state reconciliation
- response ingestion
- conversation state
- revenue-positive detection

must be inspected before any change is made.

The new compute fabric does not automatically remove or rewrite existing sensitive-workload exclusions.

If a real architectural change is required to support the approved specialist autonomy, implementation stops at that boundary and the exact change is documented and approved before modifying the protected subsystem.

## 15. Android-first control plane

Android is the primary operator interface.

The phone is not part of the compute cluster and is not required for continuous operation.

The control plane has three visibility levels:

### User
Business and operational status.

### Advanced diagnostics
Failures, retries, blocked work, providers, resources, synchronization, and reconciliation.

### Engineering evidence
Execution attempts, leases, resource identities, provider IDs, capability probes, topology, checkpoints, artifacts, and logs.

The system automatically recovers before requesting user intervention.

Closer visibility includes:

- active opportunities
- specialist
- conversation state
- follow-up
- objections
- stalled conversations
- escalations
- verified revenue-positive actions
- handoffs awaiting the user

The user does not approve ordinary closer messages.

The final human boundary is:

    Verified Revenue-Positive Action
      -> Complete Partnership Handoff Package
      -> User
      -> Partnership Placement

The control plane never becomes a second business authority.

## 16. Production rollout and safety boundaries

Production main is the baseline.

The new fabric is additive.

No destructive migration is permitted.

No fake or temporary production implementation is permitted.

No artificial green checks are permitted.

No tests are changed merely to make CI green.

Failure handling follows:

    Failure
      -> Inspect
      -> Trace Dependency Chain
      -> Determine Expected Behavior
      -> Compare Actual vs Expected
      -> Identify Root Cause
      -> Determine Smallest Valid Change
      -> Inspect Affected Connections
      -> Implement
      -> Targeted Verification
      -> Regression Verification
      -> End-to-End Verification

The existing backlog remains authoritative throughout rollout.

The batch size remains a processing limit.

Source collection completion semantics remain unchanged.

Specialist integration receives a separate gate because it includes external side effects.

Provider rollout is based on verified capability, security, execution, and recovery, not merely hardware existence.

If a new integration fails, stop the new path, preserve authoritative work, recover leases, return work to a safe existing execution path where applicable, and preserve diagnostics.

No pull request workflow is used.

Production promotion requires evidence across unit, contract, integration, failure recovery, durability, regression, resource capability, security, authoritative state preservation, downstream delivery, and end-to-end behavior.

## 17. Final end-to-end acceptance criteria

### Architecture

The final system must demonstrate:

- hierarchical distributed compute
- multiple providers
- multiple domains
- multiple nodes
- independently addressable GPUs
- CPU resources
- GPU resources
- provider metadata
- topology metadata
- NVIDIA/CUDA capability awareness
- multi-GPU scheduling
- multi-node GPU scheduling where required
- hybrid CPU/GPU execution
- I/O-aware workloads
- ephemeral resource awareness
- health and quarantine
- durable leases
- execution attempts
- checkpoint/recovery where required
- artifact references
- no artificial resource ceiling

### Existing Thorio

The final system must preserve all protected existing behavior, including durable backlog, source completeness, research, evidence, qualification, late-stage deduplication, Partnership Path, specialist routing, Airtable, referral attribution, commission/revenue state, authentication, and production safeguards.

### Backlog

The system must prove that work remains durable through failed execution and that a batch smaller than the backlog does not delete or complete remaining work.

### Source collection

The system must distinguish configured, successful, failed, skipped, retrying, and completed sources. For example, 41 configured with 37 successful and 4 failed is not successful collection completion.

### Research/evidence

Claims retain evidence, source, verification state, and timestamp.

### Qualification

The system distinguishes researched, evidenced, qualified, unqualified, insufficient evidence, blocked, and awaiting research.

### Deduplication

Deduplication occurs after research, evidence, qualification, and need/intent. Similarity alone cannot reject a materially different opportunity.

### Specialist package

The complete package contract must be satisfied before the specialist receives a ready opportunity.

### Specialist autonomy

The system must support the full authorized outreach, conversation, follow-up, objection handling, and revenue-positive workflow.

### External actions

The system distinguishes prepared, queued, attempted, transport accepted, actually sent, response received, conversation active, and revenue-positive.

### Revenue

Revenue-positive state requires actual authoritative evidence.

### Human handoff

A verified revenue-positive action produces a complete Partnership Handoff Package for the user. Partnership placement is manual and final.

### Failure recovery

Resource, scheduler, network, GPU, node, and provider failures must preserve business work and support safe retry/resume/reassignment.

### Multi-GPU and multi-node

Concrete physical resource count, capability, VRAM, topology, network, and distributed communication requirements must be verified.

### Security

Compute cannot independently modify protected business authority or sensitive revenue state.

### Android

The user can understand system health, work progress, specialist activity, compute, Airtable, revenue-positive handoffs, and genuine action-required states from Android without technical infrastructure administration.

### Continuous operation

The system continuously observes, reconciles, schedules, executes, verifies, recovers, and repeats.

### Final production test

The definitive end-to-end test is:

    Discovery
      -> Durable Backlog
      -> Research
      -> Evidence
      -> Qualification
      -> Need/Intent
      -> Deduplication
      -> Opportunity Resolution
      -> Partnership Path
      -> Complete Closer Package
      -> Specialist
      -> Outreach
      -> Conversation
      -> Follow-Up
      -> Objection Handling
      -> Revenue-Positive Action
      -> Partnership Handoff
      -> User

At every transition, verification must establish:

- correct information arrived
- state was actually accepted
- provenance was preserved
- nothing required was lost
- nothing was falsely completed
- the next stage actually received the required result

## Final acceptance rule

The design is accepted only when the compute fabric scales execution without taking ownership of Thorio business truth, existing production behavior remains intact, durable work cannot disappear, resources can fail and recover, NVIDIA/CUDA distributed execution works where required, legitimate free resources can participate, specialist closers can operate through the full authorized sales conversation, verified revenue-positive actions reach the user, and every critical connection has actual verification evidence.

## Implementation gate

This document is a design specification, not authorization to begin arbitrary implementation.

After this specification is committed and self-reviewed, the next formal step is an implementation plan covering interfaces, files, tests, rollout sequence, dependencies, and open decisions. Implementation begins only after the specification and plan have been reviewed and approved.

