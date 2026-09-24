# GPU Fabric / 12-Supercomputer Build Master Plan

> **For agentic workers:** This is the authoritative construction specification for `feature/gpu-fabric-foundation`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a continuously operating, provider-neutral software control plane that discovers, provisions, verifies, coordinates, executes, monitors, and recovers an externally sourced fleet of GPU compute infrastructure, using the initial 12-supercomputer-class construction target as the physical foundation without imposing a permanent fleet-size ceiling.

**Architecture:** The system builds the compute fabric itself through legitimate external compute infrastructure. It does not depend on user-owned hardware, user-supplied machines, or a phone as a compute component. External capacity may come from NVIDIA and other legitimate providers, cloud GPU infrastructure, compute marketplaces, distributed compute providers, and eligible free/no-cost capacity where legitimately available. **Paid capacity is permanently out of scope.** Provider acquisition is an infrastructure boundary, while physical discovery, authenticated enrollment, topology, placement, execution, durability, recovery, and feedback remain under the existing compute-fabric architecture.

The existing durable Thorio control plane remains authoritative for business work. The compute fabric remains an execution substrate beneath it. No second scheduler, queue, allocator, worker system, telemetry authority, or business-truth system is introduced.

**Tech Stack:** Existing Python 3.10 compute fabric, SQLite-backed inventory/coordinator, NVIDIA GPU tooling/CUDA/NCCL where applicable, provider APIs and legitimate external compute infrastructure, GitHub Actions validation, pytest/pytest-timeout.

## Locked scope and interpretation

The phrase "hardware we build" means the physical compute infrastructure that this system is designed to discover, provision/acquire, enroll, verify, operate, and expand through external infrastructure. It does **not** mean hardware the user must purchase, own, install, or provide.

The user's phone is **not part of the compute architecture**. It is only an external human interaction device and is never modeled as a compute node, worker, control-plane component, GPU resource, network endpoint, or infrastructure dependency.

The initial 12-supercomputer-class fleet is a construction and validation target. It is not a product, scheduler, provider, database, topology, GPU, workflow, or algorithmic ceiling. The architecture must remain extensible beyond twelve physical compute domains and must not introduce arbitrary limits on nodes, GPUs, NICs, RDMA devices, providers, paths, workloads, or queued work.

## External compute acquisition boundary

External compute is the intended physical source of execution capacity.

The acquisition layer MUST:

- discover legitimate external GPU-capable infrastructure through supported provider interfaces and APIs;
- support NVIDIA infrastructure while retaining the provider abstraction needed for additional legitimate providers;
- use only eligible free/no-cost capacity when legitimately available and permitted;
- represent provider quotas, availability, lifetime, and other external constraints as observed provider facts rather than pretending capacity is unlimited;
- never advertise capacity merely because a provider API or configuration claims it exists;
- pass acquired workers through authenticated enrollment and physical discovery before they become trusted GPU inventory;
- preserve work durably when suitable external capacity is unavailable instead of deleting, fabricating completion, or creating a second business result;
- allow the fleet to grow beyond the initial twelve domains without a fixed maximum.

Acquisition does not become a second scheduler or queue. Once external capacity is acquired, the existing inventory, placement, allocation, coordinator, worker, execution, telemetry, and recovery authorities remain in force.

## Locked build sequence

The following sequence is authoritative. A later stage cannot promote an unverified assumption from an earlier stage into physical truth.

1. **External compute acquisition and physical hardware truth**
   - Discover and provision legitimate external compute.
   - Enroll workers through authenticated identity.
   - Run actual NVIDIA/runtime discovery where applicable.
   - Capture stable GPU identity, model, UUID, VRAM, compute capability, driver, CUDA, PCI/NUMA, NIC/RDMA/topology, health, and evidence timestamps.
   - Never infer physical GPU presence from configuration alone.
   - Gate: a worker cannot advertise trusted GPU capacity without physical/runtime evidence.

2. **Actual GPU execution runtime**
   - Bind execution to the exact allocated physical GPU identity.
   - Verify CUDA/runtime compatibility and authorized device visibility.
   - Record execution evidence against the execution attempt.
   - Release resources on success, failure, cancellation, and process termination.
   - Gate: successful GPU execution must prove that computation actually ran against the allocated GPU.

3. **Correct multi-GPU and multi-node semantics**
   - Represent concrete GPU/node/provider/domain membership.
   - Distinguish same-node and multi-node requirements.
   - Support atomic multi-resource reservation and release.
   - Prevent partial reservation of distributed allocations.
   - Gate: distributed allocation is all-or-nothing.

4. **Verified topology intelligence**
   - Discover and persist evidence-backed PCIe, NUMA, NVLink/NVSwitch, NIC, RDMA, and inter-node relationships.
   - Distinguish topology existence from verified communication capability.
   - Prevent stale or inferred topology from becoming current truth.
   - Gate: topology-aware scheduling uses current physical evidence.

5. **Real NCCL/distributed execution**
   - Use verified multi-GPU allocation and verified communication prerequisites.
   - Bind communicator membership to execution attempt/generation.
   - Verify communication before declaring distributed health.
   - Capture communication evidence and tear down cleanly.
   - Gate: installed NCCL does not equal verified distributed GPU communication.

6. **Long-running leases, checkpoints, and artifacts**
   - Support renewable execution leases, checkpoint references, immutable artifact references, and resumable attempts.
   - Ensure lease renewal cannot create simultaneous authoritative attempts.
   - Resume only from compatible checkpoint/generation state.
   - Keep large payloads out of the coordinator when artifact references suffice.
   - Gate: interrupted long-running work cannot silently become two authoritative executions.

7. **Hardware, node, and provider failure intelligence**
   - Distinguish GPU, CUDA context, driver, worker process, node, network, and provider failures.
   - Quarantine the narrowest evidence-supported scope.
   - Preserve unaffected resources.
   - Requeue recoverable work with generation/attempt identity.
   - Resume from compatible checkpoints when available.
   - Gate: compute failure cannot corrupt authoritative business state.

8. **12-supercomputer fleet control plane**
   - Authenticate node enrollment, credential rotation/revocation, heartbeat, capability attestation, drain/maintenance, quarantine/re-admission, replacement, and version reporting.
   - Represent the initial twelve domains as physical infrastructure discovered through the same extensible path used for later expansion.
   - Gate: the scheduler distinguishes trusted physical workers from arbitrary capability claims.

9. **Evidence-based intelligent scheduling**
   - Reason over verified GPU model, VRAM, compute capability, CUDA, driver, topology, NVLink/NVSwitch, NCCL, CPU/RAM, network, storage, provider lifetime, health, fragmentation, priority, checkpointability, locality, and communication cost where those facts are actually observed.
   - Keep decisions deterministic and explainable at first production promotion.
   - Gate: every placement decision is explainable from recorded evidence.

10. **Real workload integration without business-authority transfer**
    - Convert an authorized compute task into an execution attempt, physical allocation, result/artifact, and authoritative acceptance path.
    - Compute failure must not mutate lead truth, research truth, qualification, routing, Airtable, revenue, partner attribution, closer, follow-up, or durable business completion state.
    - Gate: compute remains an execution substrate only.

11. **Fleet observability and operations**
    - Expose node/GPU/VRAM/utilization/health/allocation/task/checkpoint/artifact/provider/topology/NCCL/quarantine/recovery/scheduler evidence.
    - Every healthy state must be evidence-backed.
    - Gate: operators can identify why a resource or workload is unavailable from durable evidence.

12. **Full physical validation and merge preparation**
    - Validate real single-GPU execution, multi-GPU execution, multi-node execution, NCCL, topology placement, GPU/node/network failures, checkpoint/restart, lease renewal, artifact recovery, concurrent fleet scheduling, twelve-domain simulation, and physical external-provider validation wherever legitimately available.
    - Run the complete existing regression and business-integrity gates.
    - Perform a read-only branch-versus-main reconciliation rehearsal only after all preceding gates pass.
    - Do not merge until physical truth, runtime truth, distributed truth, durability, recovery, security, fleet operations, workload integration, and full regression gates pass.

## Non-negotiable constraints

- Work on `feature/gpu-fabric-foundation` until final integration.
- Keep `main` untouched during construction.
- Preserve the existing 21-layer intelligence architecture.
- Preserve the existing 128-specialist execution architecture.
- Preserve the existing 40-source research system.
- Preserve Thorio, Shiftr, and Paxus routing, research verification, Airtable delivery, closer/follow-up, revenue/attribution, and durable backlog authorities.
- Never represent allocation as execution without actual execution evidence.
- Never represent configuration as physical hardware truth.
- Never fabricate GPU, topology, performance, health, capacity, provider, or communication evidence.
- Never create a second scheduler, queue, allocator, worker system, telemetry store, or business-truth authority.
- Never impose a fixed twelve-node, GPU-count, provider-count, path-count, NIC-count, RDMA-count, workload-count, or backlog ceiling.
- A cycle/batch size is not a backlog ceiling.
- Preserve unfinished work durably when capacity disappears.
- Retries must retain task, generation, attempt, allocation, and business-authority boundaries so compute retries cannot silently create duplicate business results.
- Provider constraints are external facts. "No ceiling" means no arbitrary architectural ceiling, not a claim that external providers have unlimited free capacity. No paid fallback exists.
- Every production claim requires fresh test or workflow evidence.
- Use surgical changes and inspect existing capability before adding anything.

## Authority chain

`external provider capacity -> authenticated worker enrollment -> physical/runtime evidence -> durable inventory -> topology/path verification -> complete placement -> ComputeAllocation -> execution -> verified execution evidence -> durable telemetry -> recovery/reconciliation -> next placement`

Business truth remains outside this chain and is accepted only through the existing authoritative Thorio business pipeline.

## Verification rule

Every stage follows:

`audit existing capability -> identify the smallest genuinely missing behavior -> add focused failing evidence -> implement the smallest production change -> run focused verification -> run affected regression -> run GPU Fabric Validation -> inspect exact failures before changing anything -> preserve main untouched`

No stage is considered complete because simulated code merely looks correct. A physical execution claim requires physical/runtime evidence from legitimate external compute.

## Product decisions now locked

1. **Provider strategy:** provider-neutral architecture, NVIDIA-capable first, extensible to other legitimate providers.
2. **External compute:** the system acquires/provisions external infrastructure. User-owned hardware is not a prerequisite.
3. **Cost policy:** **zero paid spend, permanently.** The system must use only legitimately available free/no-cost external compute and free/no-cost infrastructure. No paid provider, paid API, paid compute reservation, paid authorization, paid subscription, paid fallback, or payment-dependent capability may be introduced anywhere in this architecture.
4. **Distributed transport:** NCCL is the verified NVIDIA distributed-communication foundation where applicable.
5. **12-node target:** twelve supercomputer-class compute domains are the initial physical construction/proof target, not a permanent limit.
6. **Fleet growth:** no arbitrary fleet-size ceiling.
7. **Human device:** phone is outside the compute system and is never modeled as infrastructure.

## Explicitly not required from the user

The user does not need to buy, build, install, host, attach, or physically supply GPUs, servers, NICs, RDMA equipment, storage, or networking hardware for this architecture to be valid. The system's job is to find and use legitimate external infrastructure and establish physical truth on that infrastructure.

---
