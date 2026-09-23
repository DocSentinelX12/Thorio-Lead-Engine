# GPU Physical Fabric Intelligence Design

**Date:** 2026-09-23  
**Branch:** `feature/gpu-fabric-foundation`

## 1. Purpose

Extend the existing GPU fabric from placement intelligence into a provider-neutral physical fabric intelligence layer that discovers hardware locality, constructs concrete inter-node communication paths, verifies those paths, records measured capabilities, and continuously feeds verified evidence back into the existing placement and execution architecture.

The initial 12 computers are the physical foundation only. They are not an architectural, scheduler, schema, workflow, provider, or topology ceiling.

This design builds on the existing inventory, topology, placement, allocation, coordinator, worker, verification, recovery, reconciliation, and telemetry systems. It does not create a parallel scheduler, allocation system, worker system, or execution fabric.

## 2. Physical Fabric Pipeline

The authoritative flow is:

`Workload → Placement Intelligence → Physical Fabric Discovery → GPU ↔ PCIe ↔ NUMA ↔ NIC ↔ RDMA Locality → Concrete Fabric Path Construction → Inter-Node Fabric Verification → Measured Fabric Capabilities → ComputeAllocation → Existing Coordinator/Workers → Execution Measurements → Fabric Intelligence Feedback`

The physical fabric layer is an evidence-producing substrate. Discovery, verification, and measurement are distinct states and must not be collapsed.

## 3. Hardware Discovery Model

The canonical physical model supports independently addressable:

- providers
- domains
- nodes
- GPUs
- PCI devices and PCIe hierarchy
- NUMA domains
- NICs
- RDMA devices
- RDMA ports
- fabric endpoints
- network/fabric domains

Each physical identity carries stable identifiers where available, provider/domain context, discovery timestamps, observed attributes, evidence provenance, and explicit state.

Missing information remains unknown. The system must never fabricate PCIe, NUMA, NIC, RDMA, topology, bandwidth, latency, health, or other physical facts.

Discovery adapters remain provider/framework neutral. Provider-specific APIs or runtime tools may supply facts, but the canonical fabric model does not embed provider-specific scheduling assumptions.

## 4. Locality Graph

Physical locality is represented as typed, evidence-backed relationships:

`GPU → PCIe device/hierarchy → NUMA domain → NIC → RDMA device → RDMA port → fabric endpoint`

The inter-node graph extends this relationship:

`source GPU → source endpoint → fabric/network domain → destination endpoint → destination GPU`

The system distinguishes direct locality, same-NUMA locality, cross-NUMA locality, unknown locality, and other evidence-supported relationships.

Co-existence on one node is not proof of locality. Device numbering or list position is never treated as proof of GPU-to-NIC association.

## 5. Concrete Fabric Path Model

A concrete path is a first-class evidence object containing, where established:

- path identity
- source GPU and node
- source PCI/locality evidence
- source NUMA domain
- source NIC
- source RDMA device and port
- fabric/network identity
- destination RDMA device and port
- destination NIC
- destination NUMA domain
- destination node and GPU
- discovery evidence
- locality evidence
- connectivity evidence
- verification evidence
- measurement evidence
- current state
- failure domains
- timestamps

A path may be discovered without being verified.

Path states are:

`DISCOVERED → CONSTRUCTED → VERIFIED → MEASURED`

Degradation, failure, recovery, and reverification are additional state transitions supported by evidence and do not erase history.

## 6. Discovery and Identity Reconciliation

Discovery is repeatable and idempotent.

Stable hardware/provider identifiers are preferred over transient runtime identifiers. When a stronger identifier exists, a transient interface index or list position cannot silently become the permanent identity.

Repeated discovery converges on existing physical identities instead of creating duplicates.

Discovery may run concurrently across independent nodes and domains. Concurrency is driven by actual work and available execution resources, not by a hard-coded node count.

## 7. Locality and Path Construction

Path construction is hierarchical rather than an unrestricted Cartesian product.

The construction flow is:

`GPU → eligible local communication endpoints → reachable remote endpoints → verified fabric domains → eligible remote GPUs → complete concrete paths`

Hard incompatibilities are eliminated before later stages. The algorithm must not impose arbitrary limits on nodes, GPUs, NICs, RDMA devices, paths, providers, domains, or observations.

Multiple physically valid paths are retained. The model must support redundant NICs, RDMA endpoints, fabric domains, and routes without silently discarding alternatives.

Hierarchical construction provides tractability without becoming an architectural ceiling.

## 8. Active Verification Contract

Discovery is not proof of communication.

Verification progressively establishes the evidence required by the workload:

1. endpoint existence
2. local endpoint accessibility
3. remote endpoint reachability
4. inter-node communication
5. RDMA communication where required
6. GPU-associated communication where required
7. workload-relevant communication where required

The verifier records the exact stage proven. A successful generic network probe is not automatically accepted as proof of a specific GPU-to-GPU execution path.

A verification record contains path identity, source/destination endpoint identities, verification stage, timestamp, operation, result, failure evidence when applicable, correlated hardware identities, runtime/environment identity, and measurements when applicable.

## 9. Capability and Measurement Model

Existence, verification, and measurement are separate evidence classes.

Measured capability may include:

- link availability and negotiated characteristics
- RDMA reachability
- latency
- bandwidth
- collective performance
- error/retry behavior
- route stability
- degradation
- workload-specific communication performance

Measurements are observations, not permanent truths. Historical observations retain their identity and timestamp. Current capability state can change as new observations arrive.

There is no arbitrary history expiration, sample-count ceiling, or observation-count ceiling.

## 10. Failure Isolation and Recovery

Failure classification uses the narrowest evidence-supported domain, including:

- GPU/NIC/RDMA path
- GPU
- node
- RDMA endpoint
- inter-node route
- workload-specific path
- execution attempt
- unresolved

A lower-level failure does not automatically poison a broader resource.

Unexplained evidence remains unresolved.

Recovery preserves the original placement, physical path, and failure evidence. Replacement logic excludes only resources or paths concretely established as unusable, reconstructs complete valid candidates, requires the same physical verification gates, produces a new placement identity, and returns control to the existing coordinator/recovery machinery.

A recovered endpoint is not trusted merely because it became reachable again. Relevant evidence must be re-established.

## 11. Persistence and Concurrency

Current physical state and historical evidence are distinct.

Current state answers what is known now. Historical evidence preserves discovery, verification, measurement, failure, recovery, and reverification observations.

Existing `ComputeInventory` persistence patterns should be extended where appropriate rather than creating an unrelated storage authority.

All retryable discovery and verification operations must be idempotent. Stable identities and operation/evidence identities prevent stale observations from silently duplicating or destroying newer information.

Concurrent discovery and verification may proceed independently while respecting actual infrastructure and control-plane constraints.

## 12. Placement and Execution Integration

Physical Fabric Intelligence is the authoritative source for physical topology and path evidence.

Placement Intelligence consumes that evidence and does not independently reconstruct PCIe, NUMA, NIC, or RDMA topology.

The execution boundary remains:

`Physical Fabric Intelligence → Placement Intelligence → ComputeAllocation → Existing Coordinator → Existing Worker → Execution`

`ComputeAllocation` remains authoritative for reservations. A verified path does not reserve hardware.

Execution attempts retain placement and physical path identities where identifiable. Execution measurements feed back into fabric capability, workload-performance, and route-health intelligence through the existing telemetry architecture.

No second scheduler, allocator, coordinator, worker system, queue, or execution fabric is introduced.

## 13. Production Verification

The existing **GPU Fabric Validation** workflow remains the production gate. No unnecessary parallel validation workflow is introduced.

Verification is dependency ordered:

`Environment/install → discovery contracts → topology/locality → path construction → verification contracts → persistence/reconciliation → placement integration → execution integration → full GPU Fabric Validation`

Tests must distinguish:

- model-level validation
- synthetic evidence validation
- runtime discovery capability
- actual hardware verification

Synthetic fixtures must never be presented as production hardware evidence.

Production acceptance requires proof that:

1. hardware discovery populates the canonical model;
2. physical relationships are evidence-backed;
3. discovered paths cannot be treated as verified automatically;
4. concrete paths retain multiple valid alternatives;
5. verification evidence persists;
6. measurements persist;
7. failures remain correctly scoped;
8. recovery requires reverification;
9. placement consumes physical evidence;
10. ComputeAllocation remains authoritative;
11. existing execution consumes the resulting placement;
12. execution feedback reaches fabric intelligence;
13. repeated discovery converges without duplication;
14. no fixed topology ceiling exists;
15. the production validation workflow passes;
16. `main` remains untouched.

## 14. Phased Implementation

The implementation proceeds through independently gated phases:

### Phase 1: Canonical physical inventory
Build stable physical identities, discovery interfaces, evidence records, reconciliation, persistence, and explicit unknown handling.

### Phase 2: GPU-to-NIC locality intelligence
Build evidence-backed PCIe/NUMA/NIC/RDMA relationships and validate locality without assumptions.

### Phase 3: Concrete fabric paths
Construct complete source-to-destination physical paths using hierarchical candidate construction and preserve multiple valid paths.

### Phase 4: Active verification
Progress discovered paths through construction and verification with workload-specific verification depth.

### Phase 5: Measurements
Record real capability and workload observations, preserving history and current state separately.

### Phase 6: Placement integration
Feed verified physical evidence into the existing placement evaluator without duplicating topology logic.

### Phase 7: Execution feedback
Carry placement/path identity through existing allocation, coordinator, worker, and execution telemetry.

### Phase 8: Continuous recovery
Classify failures narrowly, preserve evidence, reconstruct valid paths and placements, reverify, and resume through existing recovery.

Each phase follows:

`Design → tests first → minimum implementation → focused verification → production integration → full GPU Fabric Validation → next phase`

## 15. Architectural Guardrails

This implementation must not:

- modify the main branch;
- create a second execution system;
- create a second allocation system;
- create a second scheduler;
- impose a 12-node or fixed hardware ceiling;
- discard excess discovered resources or paths;
- fabricate missing physical evidence;
- treat discovery as verification;
- treat verification as measurement;
- destroy historical evidence when current state changes;
- broadly quarantine resources without evidence;
- introduce unrelated refactoring;
- weaken or bypass existing placement, allocation, coordinator, worker, recovery, reconciliation, or telemetry boundaries.

The 12 computers are the initial physical foundation only.

## 16. Success Criteria

The completed layer will provide a continuous, auditable physical fabric intelligence system that can:

1. discover real physical compute and communication resources;
2. correlate GPU, PCIe, NUMA, NIC, and RDMA locality using evidence;
3. construct complete concrete inter-node paths;
4. distinguish discovered, constructed, verified, and measured states;
5. preserve redundant physical paths;
6. perform active communication verification;
7. retain historical measurements and current capability state;
8. isolate failures to the narrowest proven domain;
9. recover through the existing architecture with reverification;
10. provide physical evidence to deterministic placement intelligence;
11. trace execution back to concrete placement and fabric paths;
12. learn from observed execution outcomes;
13. continuously incorporate additional providers, nodes, GPUs, NICs, RDMA endpoints, topology domains, paths, and observations without architectural redesign or arbitrary ceilings.
