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

## Change discipline

Foundation changes are additive and independently testable. Existing queue, backlog, research, qualification, routing, Airtable, and revenue tests are regression gates before production participation.
