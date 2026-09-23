# GPU Placement Intelligence Design

**Date:** 2026-09-23  
**Branch:** `feature/gpu-fabric-foundation`

## 1. Purpose

Extend the existing GPU fabric from verified individual-resource selection into intelligence-first distributed placement. The initial 12 computers are the physical foundation, not an architectural ceiling.

The design builds on the existing scheduler, inventory, topology, allocation, coordinator, worker, verification, recovery, and telemetry systems. It does not create a parallel execution or allocation system.

## 2. Placement Architecture

The placement pipeline is:

`Workload requirements → Eligible physical GPUs → Capability compatibility → Verified GPU/NIC/RDMA paths → Topology grouping → NUMA/locality analysis → Multi-GPU/multi-node candidate construction → Workload-specific historical performance → Observed route health → Deterministic complete placement → Durable allocation → Existing execution fabric`

The placement result is the unit of intelligence. The existing `ComputeAllocation` remains the authoritative durable resource boundary consumed by execution.

The architecture must remain provider-neutral and dynamically extensible. No fixed 12-node, 12-GPU, provider, NIC, RDMA, or cluster-size assumption is permitted.

## 3. Complete Placement Construction

The scheduler must evaluate complete GPU sets rather than treating individual GPU ranking as sufficient.

Every candidate must satisfy:

1. Each GPU individually satisfies workload requirements.
2. The candidate's topology domain and node combination are verified.
3. Every required GPU-to-NIC relationship is verified.
4. Every required NIC-to-RDMA/device relationship is verified.
5. Required inter-node communication paths are physically verified.
6. NUMA and locality constraints are preserved.
7. The complete communication fabric is compatible with the workload.

A set of individually strong GPUs must be rejected if its complete interconnect is invalid or unverifiable.

Only physically valid candidates proceed to workload-specific performance and route-health intelligence.

## 4. Placement Evidence and Deterministic Evaluation

Every placement decision must be explainable through explicit evidence rather than an opaque score.

Evidence includes:

- selected GPU, node, NIC, and RDMA identifiers where verified
- physical topology evidence
- GPU-to-NIC and NIC-to-RDMA locality
- NUMA relationships
- intra-node and inter-node paths
- capability compatibility
- workload signature
- workload-specific historical performance
- route-health observations
- candidate rejection reasons
- deterministic decision trace

Evaluation order:

1. Resource eligibility
2. Capability compatibility
3. Complete physical/topology validity
4. Complete communication-path validity
5. NUMA/locality compatibility
6. Workload-specific observed performance
7. Observed route health
8. Stable deterministic resource ordering

Performance evidence can never rescue an invalid or unverifiable physical placement.

Unknown evidence remains unknown. The system must not fabricate latency, bandwidth, health, or other values to fill gaps.

## 5. Placement Data Model and Execution Boundary

Placement becomes a first-class durable concept containing:

- placement identity
- workload requirements/signature
- selected resources
- selected nodes
- verified NIC/RDMA endpoints
- physical path evidence
- topology and NUMA evidence
- workload-performance evidence
- route-health evidence
- candidate/rejection evidence
- decision trace
- timestamps
- placement schema/version information

The system must not create a second allocation or execution system.

The boundary remains:

`Requirements → Placement Intelligence → Verified Placement → Existing ComputeAllocation → Existing Coordinator/Worker Execution`

Placement evidence explains why an allocation was constructed. `ComputeAllocation` remains authoritative for reservation and execution.

Placement identity must separate stable identity inputs from volatile observation data so timestamps do not unnecessarily destabilize placement identity.

## 6. Continuous Learning and Feedback

The intelligence loop is:

`Placement → Execution → Verification → Observed Evidence → Historical Intelligence → Next Placement`

Only observed execution results may improve workload-performance or route-health intelligence.

Execution evidence should retain:

- actual participating GPUs and nodes
- actual NIC/RDMA paths when identifiable
- workload identity
- communication pattern
- elapsed collective performance
- success/failure
- generation/attempt identity
- observation time

Evidence classes are explicitly distinguished:

- **Observed:** directly measured during execution.
- **Verified physical:** established from inventory/topology/device evidence.
- **Unknown:** information not currently established.

The system must not turn unknown data into assumptions.

Historical observations retain timestamps and sample counts. The design does not impose arbitrary expiration, sample-count, or history-size ceilings.

Verification compares intended placement with actual placement and behavior. Discrepancies become evidence rather than being silently discarded.

## 7. Failure, Replacement, and Recovery

The existing coordinator/reconciliation/recovery infrastructure remains authoritative.

Failure flow:

`Selected Placement → Allocation/Execution → Failure or Degradation → Concrete Failure Evidence → Identify Affected Failure Domain → Re-evaluate Valid Resources → Complete Replacement Placement → Existing Recovery/Coordinator`

The system must identify the narrowest evidence-supported failure domain. It must not automatically declare every resource involved in a failed execution unusable.

Possible domains include:

- GPU
- node
- GPU-to-NIC path
- NIC/RDMA endpoint
- inter-node route
- workload-specific communication path
- execution attempt
- unresolved/unknown failure

When recovery requires replacement:

1. Preserve the original placement and failure evidence.
2. Exclude only resources or paths concretely established as unusable.
3. Re-run complete placement construction.
4. Require the replacement to satisfy the same physical, capability, topology, and communication validation.
5. Apply applicable workload and route intelligence.
6. Produce a new placement identity and decision trace.
7. Hand the replacement to the existing recovery/coordinator machinery.

A transient or unexplained failure must not permanently poison a resource.

## 8. Scaling Beyond the Initial 12 Computers

The 12 computers are the initial physical foundation only.

The scheduler operates on discovered and verified resources rather than fixed topology counts.

Resource expansion follows:

`Provider(s) → Discovered Compute Resources → Verified GPU/NIC/RDMA Inventory → Topology Domains → Candidate Placement Construction → Workload Intelligence → Selected Placement`

No fixed maximum is imposed on:

- nodes
- GPUs
- providers
- NICs
- RDMA endpoints
- topology domains
- observations

Candidate construction may use hierarchical topology domains and compatible resource groups to remain tractable as the fabric grows, without imposing an artificial architectural ceiling.

Adding a verified machine is an inventory/topology event, not a scheduler redesign.

Provider adapters supply verified facts. Placement intelligence reasons over those facts without provider-specific scheduling assumptions.

## 9. Testing and Production Verification

Testing must prove both correctness and the reason for placement decisions.

### Unit intelligence coverage

Tests cover:

- workload signature construction
- candidate generation
- topology grouping
- NUMA/locality
- GPU/NIC/RDMA validation
- workload-performance lookup
- route-health lookup
- deterministic ordering
- tie-breaking
- unknown evidence handling

### Complete-placement coverage

Tests must include:

- individually capable GPUs with invalid interconnects
- valid candidates with different topology quality
- multiple valid sets with different observed workload performance
- known versus unknown route health
- heterogeneous GPU capabilities
- multi-node placement
- NUMA-sensitive placement
- insufficient valid paths
- incomplete physical evidence
- deterministic equivalent candidates

Tests should verify rejection and ordering reasons, not only the final selected candidate.

### Feedback coverage

Tests verify:

`placement → execution evidence → persisted observation → future placement`

and verify that failures do not incorrectly poison unrelated resources.

### Recovery coverage

Tests verify preservation of:

- original placement identity
- failure evidence
- surviving resources
- replacement placement identity
- complete physical validation

### Production gate

The existing **GPU Fabric Validation** workflow remains the production gate. No unnecessary parallel workflow is introduced.

The gate must preserve existing fabric behavior while proving that placement intelligence cannot bypass physical validation, workload evidence is preserved, route evidence is preserved, recovery remains compatible, and the existing execution boundary receives a valid allocation.

## 10. Non-Goals and Architectural Guardrails

This design does not authorize:

- a second execution fabric
- a second allocation system
- arbitrary compute or resource limits
- guessed physical topology
- fabricated performance data
- synthetic health scores presented as observations
- hidden fallback that treats unknown resources as verified
- unrelated refactoring
- replacing existing coordinator, worker, recovery, or reconciliation architecture

All changes must remain surgical and build on verified existing infrastructure.

## 11. Success Criteria

The implementation is successful when the existing fabric can construct a complete, deterministic, auditable distributed GPU placement that:

1. Uses only eligible and verified resources.
2. Validates the complete physical communication fabric.
3. Preserves topology and locality.
4. Uses observed workload-specific performance and route-health evidence after hard validity gates.
5. Produces an explicit decision trace.
6. Persists placement evidence without creating a parallel execution system.
7. Feeds verified execution outcomes back into future placement intelligence.
8. Handles failure through the existing recovery architecture.
9. Can absorb additional verified compute beyond the initial 12 computers without architectural redesign.
10. Passes the existing GPU Fabric Validation production gate.
