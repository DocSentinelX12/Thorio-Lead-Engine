# Thorio Compute Fabric Architecture Contract

Status: approved foundation contract
Branch: feature/gpu-fabric-foundation

## Authority boundaries

The compute fabric is an execution substrate. It MUST NOT become authoritative for:
- canonical lead state
- evidence truth or verification truth
- qualification/readiness gates
- durable backlog completion
- routing or sales authorization
- Airtable truth
- revenue/commission state

Compute capacity, task execution, and hardware health are separate from business truth.

## Durable work invariant

A workload remains durably queued until a valid completion is persisted by the authoritative Thorio queue/state layer. A worker lease, batch limit, GPU outage, node loss, or scheduler restart MUST NOT imply completion or deletion.

There MUST NOT be a second independent queue whose state can become authoritative for Thorio work.

## Resource identity

Physical compute resources are independently addressable. A node is a container/topology domain, not the atomic GPU scheduling unit.

GPU identity consists of stable hardware evidence where available:
- node_id
- gpu_id
- gpu_uuid
- model
- vram_bytes
- compute_capability
- driver_version
- cuda_version
- pci_bus_id
- numa_node
- topology domain identifiers
- health and availability state

Missing optional hardware evidence is represented explicitly, never fabricated.

## Physical worker enrollment

Physical GPU workers enroll through the existing authenticated coordinator/worker path. Each worker performs local NVIDIA discovery and publishes the observed GPU identities together with explicit PCI, NUMA, NIC, RDMA device, RDMA port, and GPU-to-NIC locality evidence when available.

Worker enrollment preserves:
- stable worker and physical domain identity
- exact GPU UUID and PCI identity
- observed physical-fabric component identities
- provenance for physical relationships
- unknown optional hardware fields without inference
- durable current state and historical physical observations through the existing inventory

The worker's configured compute domain is carried with its physical inventory. This allows the initial supercomputer domains to be represented as real provider/domain scopes without introducing a twelve-domain limit. Every additional authenticated worker contributes its own observed hardware evidence through the same path.

The coordinator republishes the worker's physical discovery into the existing ComputeInventory. ComputeScheduler, ComputeAllocation, and the existing coordinator/worker execution path remain the only placement, reservation, and execution authorities. No second worker registry or physical telemetry store is introduced.

## Scheduling

Work requests express requirements. The scheduler selects concrete resources satisfying all required constraints.

The resource model MUST support:
- CPU-only
- single-GPU
- multi-GPU
- multi-node GPU
- hybrid CPU/GPU

GPU count MUST NOT be interpreted as aggregate VRAM. A request for N GPUs means N concrete GPU resources.

## Topology

Topology evidence and actual communication capability are distinct facts. Discovery of NVLink/PCIe/NUMA/network relationships does not itself prove distributed communication performance.

NCCL is optional for workloads that do not require distributed GPU communication.

## Health

Resources transition through explicit states. A failed or uncertain resource can be quarantined and excluded from new production leases while retaining diagnostic evidence.

Health state is not business truth.

## Leases

A resource allocation is leased with an identity and generation/attempt context. Expiration permits recovery. Completion is accepted only through the valid task lease and authoritative completion path.

## Compatibility

The fabric is provider-neutral and workload-framework-neutral. GPU model, CUDA, driver, runtime, and framework are capabilities/constraints, not scheduler assumptions.

## Cells

Cells are logical scheduling/topology domains and are dynamically extensible. Six cells is not a hard limit.

## Artifacts and checkpoints

Large immutable inputs/outputs should be represented by artifact references. Long-running workloads may checkpoint and resume. Artifact and checkpoint systems must not become a second source of lead truth.

## Capacity

Capacity reporting distinguishes:
TOTAL, HEALTHY, AVAILABLE, RESERVED, LEASED, DEGRADED, and QUARANTINED resources.

Source I/O scaling remains a separate fabric. GPU availability MUST NOT be required for ordinary source collection.

## Fleet-scale resource intelligence

Fleet capacity is derived read-time from the durable resource inventory and active allocation bindings. The fleet view is hierarchical by provider, domain, node, and resource type and distinguishes:
- TOTAL
- HEALTHY
- AVAILABLE
- RESERVED
- LEASED
- DEGRADED
- QUARANTINED

GPU capacity additionally exposes exact known VRAM totals, unknown VRAM counts, capability families, available GPUs by node, and maximum observed available GPUs per node. Missing capability evidence remains unknown and is never converted into estimated capacity.

A bound allocation is represented as LEASED in the fleet view only while its exact durable allocation remains bound. A reserved but unbound allocation remains RESERVED. Quarantined and degraded resource state remains visible rather than being hidden behind allocation state.

The fleet view also exposes authenticated, unexpired eligible-resource counts and the latest observed inventory timestamp. Expired resources remain historical inventory but do not contribute to eligible capacity. This is a read-only intelligence surface. It does not reserve, release, quarantine, rebind, or otherwise mutate resources, and it does not create a second scheduler or queue.

## Continuous self-optimization

Observed execution results and current fleet capacity form a closed feedback loop into subsequent placement construction. Each placement is recomputed against current eligible inventory and the exact observed workload/path evidence already retained by the fabric.

Self-optimization is bounded by existing authority:
- hard physical, capability, lease, and communication validation cannot be overridden
- observed workload performance, route health, predictive degradation, multidimensional workload evidence, and measured path evidence remain stronger authorities than capacity preservation
- fleet optimization may preserve future placement flexibility only after those stronger authorities have been applied
- ComputeAllocation remains the authoritative reservation boundary
- no synthetic performance, probability, future capacity, or failure estimate is created
- the optimization surface is read-only and does not mutate resource state, queue state, or business state

The optimization loop is restart-safe because it derives from durable inventory, allocation, route, placement, and execution evidence rather than an in-memory learning model. New observations automatically participate in the next placement evaluation without a separate retraining job or fixed optimization horizon.

## Massive-scale stress and production proof

The fabric control plane is validated separately at fleet scale using the real durable inventory, fleet aggregation, resource-state transitions, provider/domain boundaries, and restart/reobservation paths. The scale proof models twelve independent supercomputer domains with 64 nodes and 8 GPUs per node, exercising 6,144 GPUs and 6,912 total inventory resources without imposing that number as a product limit.

The proof verifies exact cardinality after repeated observation, persistence after database reopen, exact capacity changes after resource-state transitions, known VRAM accounting, and strict provider/domain isolation. It does not claim that CI possesses physical GPUs. Physical execution remains dependent on authenticated provider discovery and the existing physical verification gates.

The GitHub validation workflow runs this scale proof as its own gate in addition to the existing GPU fabric regressions. The scale fixture is intentionally finite for CI execution, while the production architecture has no corresponding hard fleet-size ceiling.

## Autonomous closed loop

The compute fabric closes the control loop across durable work, physical observation, recovery, placement, execution, and verified feedback:

`durable queue -> recovery/reconciliation -> provider observation -> eligible inventory -> complete placement -> ComputeAllocation -> execution -> verified execution evidence -> durable path/workload feedback -> next placement`

The loop is continuously driven by `ComputeFabricController.run_forever()`. Its per-cycle allocation value is a batch size only, not a backlog ceiling. A stopped worker, expired lease, provider disappearance, or failed distributed attempt does not imply completion. Recovery returns unfinished work to the authoritative queue and the next placement is constructed from current eligible inventory.

Execution verification is the feedback boundary. Only accepted verification contributes observed execution metrics, path performance, and workload/path performance. The autonomous cycle reads those durable observations on subsequent scheduling decisions. It does not manufacture latency, capacity, failure probabilities, or future outcomes.

The closed-loop evidence surface reports the current phase and next cycle action from explicit durable counts, including recovery, execution, available feedback, capacity waiting, and idle states. It is advisory orchestration evidence only. `ComputeScheduler` remains the placement authority, `ComputeAllocation` remains the reservation authority, physical validation remains authoritative, and the existing durable task/coordinator layer remains the work-state authority.

The loop is restart-safe because its decisions are reconstructed from durable inventory, allocations, execution attempts, execution metrics, route evidence, workload evidence, and task state. No in-memory learning model, second queue, fixed optimization horizon, or fixed fleet-size limit is introduced.

## Change discipline

Foundation changes are additive and independently testable. Existing queue, backlog, research, qualification, routing, Airtable, and revenue tests are regression gates before production participation.


## GPU placement intelligence

Complete placement is the unit of distributed scheduling intelligence.

The placement pipeline is:

\`requirements -> eligible GPUs -> capability compatibility -> verified physical evidence -> topology/locality -> complete candidate construction -> observed workload performance -> observed route health -> deterministic placement -> ComputeAllocation -> existing coordinator/worker execution\`

A placement records:
- stable placement identity
- workload requirements and performance signature
- selected GPUs and nodes
- verified GPU/NIC/RDMA evidence where required and available
- topology and NUMA evidence
- observed workload-performance evidence
- observed route-health evidence
- candidate acceptance/rejection evidence
- deterministic decision trace

Hard physical and capability constraints are evaluated before performance or route preferences. Unknown evidence remains unknown and is never converted into a synthetic score.

\`ComputeAllocation\` remains the authoritative reservation boundary. Placement evidence explains why that allocation was selected and does not create a second reservation or execution system.

Execution verification feeds only observed results back into workload-performance and route-health history. Recovery retains the original placement and failure evidence and re-enters the same complete placement construction path for replacement resources.

The initial 12 computers are the physical foundation only. Placement construction has no fixed node, GPU, provider, NIC, RDMA, topology-domain, or observation ceiling. Hierarchical candidate construction is used to remain tractable as verified inventory grows.

## Placement persistence and execution identity

Durable placement records are historical evidence. Allocation release does not erase placement history.

Execution attempts retain the placement identity that produced their allocation, and durable execution metrics retain that identity alongside workload and physical-path evidence. This keeps the placement-to-execution-to-verification feedback loop auditable without creating a parallel execution state machine.

## Recovery evidence domains

Recovery evidence records the narrowest domain that can be established directly from supplied evidence, including:
- GPU
- GPU/NIC/RDMA path
- node
- RDMA endpoint
- inter-node route
- workload path
- execution attempt
- unresolved

An unresolved failure is retained as unresolved. The system does not permanently quarantine unrelated resources from an unexplained execution failure.
