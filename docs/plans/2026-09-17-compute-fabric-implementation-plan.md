# Thorio Lead Engine: Distributed Compute Fabric Implementation Plan

Status: implementation plan for user review and approval
Date: 2026-09-17
Repository: DocSentinelX12/Thorio-Lead-Engine
Target branch: feature/gpu-fabric-foundation
Canonical design: docs/specs/2026-09-17-compute-fabric-design.md

## 1. Implementation rules

This plan implements the approved compute-fabric design without changing Thorio business authority.

Permanent constraints:
1. Never use pull requests.
2. Work only in DocSentinelX12/Thorio-Lead-Engine.
3. Develop on the approved isolated branch until explicit promotion approval.
4. Inspect the complete dependency chain before every code change.
5. Make the smallest surgical change supported by evidence.
6. Do not change tests merely to obtain green results.
7. Do not introduce fake, simulated, placeholder, or temporary production capacity.
8. The existing authoritative Thorio queue and backlog remain authoritative.
9. Batch size is a processing limit, never a completion limit.
10. Compute execution tables remain transport, lease, and execution state only.
11. Compute must not become authoritative for lead state, evidence, qualification, Partnership Path, Airtable truth, referral attribution, commission, revenue, or Partnership placement.
12. Missing hardware or capability evidence remains explicitly missing.
13. Legitimate provider access only. No quota, authentication, CAPTCHA, or policy circumvention.
14. Android is the operator surface, not a required compute node.
15. Do not claim completion or production readiness without fresh verification evidence.
16. Any protected existing subsystem that must change requires a separate evidence-backed change explanation and explicit approval before modification.

## 2. Current repository baseline verified for planning

The approved branch currently contains the physical resource foundation:
- lead_engine/compute_resources.py
- lead_engine/test_compute_resources.py
- docs/COMPUTE_FABRIC_ARCHITECTURE.md
- docs/specs/2026-09-17-compute-fabric-design.md

The current execution layer remains worker-slot based:
- lead_engine/compute_pool.py uses LOGICAL_SLOTS_PER_WORKER = 1.
- Worker registration currently records CPU, memory, architecture, and string capabilities.
- lead_engine/compute_coordinator.py owns a SQLite-backed execution task table and worker lease flow.
- lead_engine/compute_worker.py registers workers, claims remote execution tasks, runs supported stateless work, and reports completion/release.
- lead_engine/compute_bridge.py publishes selected local agent tasks to the remote coordinator and reconciles completed results back into the local authoritative queue.
- lead_engine/agent_queue.py remains the durable specialist queue.
- lead_engine/scheduler.py owns the continuous source/agent scheduling loop and already has a remote-compute bridge connection.
- The remote bridge currently excludes outreach_closer and follow_up from REMOTE_SAFE_AGENTS. This is an existing protected boundary. It must be inspected before any change intended to support the approved autonomous closer workflow.

The new physical resource model is not yet wired into production scheduling. This is a deliberate safe state and must not be described as GPU-aware scheduling.

## 3. Delivery decomposition

The implementation is divided into independently verifiable subprojects.

### Subproject A: Physical resource inventory and provider-neutral registration

Goal:
Turn the existing resource dataclasses into a durable, evidence-backed inventory that can represent many providers, domains, nodes, CPUs, GPUs, topology, health, lifetime, and ephemeral resources.

Proposed files:
- lead_engine/compute_resources.py
- lead_engine/compute_inventory.py (new)
- lead_engine/compute_provider.py (new)
- lead_engine/test_compute_inventory.py (new)
- lead_engine/test_compute_provider.py (new)

Interfaces:
- Provider adapter discovers resources and returns normalized NodeResource/GpuResource/CpuResource data.
- Inventory persists resource identity and observed capability evidence.
- Inventory exposes resource snapshots to scheduling without owning business work.

Behavior:
- Preserve GPU identity independently from worker process identity.
- Persist provider, domain, node, GPU, CPU, lifetime, health, availability, capability, and topology evidence.
- Represent missing optional evidence as missing.
- Admit resources only after capability and health probing.
- Preserve identity across worker process replacement where provider identity permits.
- Track ephemeral expected lifetime and provider disappearance.
- Keep resources independently addressable so one failed GPU does not automatically quarantine unrelated healthy GPUs on the same node.
- Never infer topology performance from topology existence.

Focused tests:
- Multiple GPUs on one node are independently addressable.
- Same model GPUs with different UUIDs remain distinct.
- Missing UUID is not fabricated.
- Provider disappearance does not delete durable resource history.
- Ephemeral expiration changes scheduling eligibility without deleting identity.
- One GPU failure leaves unrelated healthy GPU inventory intact.
- Quarantined resources are not admitted to new allocations.
- Provider-specific capability data is retained as evidence.

Acceptance:
Inventory can report a concrete resource graph without creating or modifying any Thorio lead/backlog state.

### Subproject B: Capability matching and global resource scheduler

Goal:
Replace the current one-logical-slot scheduling assumption for compute-fabric workloads with concrete CPU/GPU resource allocation while preserving existing queue authority.

Proposed files:
- lead_engine/compute_scheduler.py (new)
- lead_engine/compute_requirements.py (new only if separation from existing compute_resources.py is justified during inspection)
- lead_engine/compute_pool.py
- lead_engine/compute_coordinator.py
- lead_engine/test_compute_scheduler.py
- existing capability-dispatch/remote-contract tests as regression gates

Interfaces:
- Scheduler consumes ComputeRequirements plus inventory snapshot.
- Scheduler returns a concrete allocation containing provider/domain/node/resource IDs and capability evidence.
- Coordinator leases execution allocations using attempt/generation context.
- Existing authoritative agent_queue remains the source of business work.

Behavior:
- Match CPU-only, single-GPU, GPU-required, multi-GPU, multi-node GPU, hybrid CPU/GPU, and I/O-bound workloads.
- Enforce concrete GPU count.
- Enforce VRAM, compute capability, CUDA, driver, NCCL, topology, network, CPU, RAM, storage, and lifetime requirements when specified by the workload contract.
- Multi-GPU same-node work requires distinct compatible physical GPUs.
- Multi-node work requires resources on multiple nodes and verified distributed communication capability.
- Prefer NVIDIA resources for NVIDIA/CUDA workloads without making the provider abstraction NVIDIA-exclusive.
- Never schedule quarantined or expired resources.
- Account for resource reservations and active leases.
- Support resource-aware priority/fairness/efficiency while never bypassing business authorization.
- Preserve the existing logical worker path as a compatibility path until the new physical allocation path is independently verified.
- Batch size remains unrelated to resource capacity and backlog completion.

Focused tests:
- Four-GPU request cannot be satisfied by one GPU with four times the VRAM.
- Four-GPU request allocates four concrete compatible GPUs.
- Multi-node request spans actual nodes.
- CUDA/driver mismatch is rejected.
- NCCL is required only when the workload contract requires it.
- Topology-domain requirements are enforced.
- Quarantined resources are excluded.
- Ephemeral resources with insufficient lifetime are excluded for non-checkpointable work.
- A failed allocation leaves the authoritative queue unchanged.
- Concurrent allocation cannot double-book a physical resource.
- Scheduler restart/reconciliation does not manufacture completion.

Acceptance:
A scheduler test can prove physical GPU-aware placement independently of Thorio business state.

### Subproject C: Durable execution, leases, checkpointing, and reconciliation

Goal:
Make distributed execution failure-safe across workers, GPUs, nodes, providers, scheduler restarts, and network partitions.

Proposed files:
- lead_engine/compute_coordinator.py
- lead_engine/compute_worker.py
- lead_engine/compute_execution.py (new if the current coordinator/worker responsibilities cannot remain cohesive after inspection)
- lead_engine/compute_reconciliation.py (new)
- focused execution/recovery tests

Interfaces:
- Business work ID remains separate from execution attempt ID.
- Execution attempt references lease ID, generation, provider, domain, node, physical resources, workload, checkpoints, artifacts, result, verification, and authoritative acceptance.
- Coordinator exposes only execution transport/lease operations.
- Reconciliation reads authoritative Thorio state plus execution/resource state and reports mismatches.

Behavior:
- Lease acquisition is atomic for the concrete resource set.
- Heartbeats renew active execution leases.
- Expired leases become recoverable without marking business work complete.
- Worker/node/GPU/provider failure releases or quarantines execution resources while preserving durable work.
- Stale execution records are reconciled.
- Duplicate completion submissions are idempotent at the execution boundary.
- Results are not authoritative until accepted through the existing business-state path.
- Large inputs/outputs use artifact references rather than control-plane payload copying.
- Checkpointing is used for workloads whose contract permits resume.
- Repeated failures can quarantine an execution/work item without deleting evidence or durable work.
- Failure diagnostics survive process/provider failure.

Focused tests:
- Worker dies after lease acquisition and work becomes recoverable.
- GPU failure during execution does not complete the business work.
- Scheduler restart recovers stale leases.
- Network partition causes retry/reconciliation, not duplicate authoritative completion.
- Duplicate completion is harmless.
- Result without authoritative acceptance is detectable.
- Authoritative work without execution state is detectable.
- Active execution on a disappeared worker is detectable.
- Expired lease while worker claims running is detectable.
- Checkpoint resume does not lose the business work ID.
- Artifact references remain stable across retries.

Acceptance:
Failure injection demonstrates no durable business-work loss and no false completion.

### Subproject D: NVIDIA execution adapter and distributed execution verification

Goal:
Provide the premier NVIDIA path for CUDA, multi-GPU, and multi-node execution using real capability evidence.

Proposed files:
- lead_engine/providers/nvidia.py (new)
- lead_engine/providers/__init__.py (new if package does not already exist)
- lead_engine/nvidia_runtime.py (new)
- focused NVIDIA capability/runtime tests
- provider contract tests

Interfaces:
- NVIDIA provider adapter reports actual GPU, CUDA, driver, compute capability, VRAM, NCCL, PCIe/NVLink/NVSwitch/NUMA, and network evidence available on the host.
- Runtime verifier proves that requested CUDA and distributed communication capabilities actually execute where required.

Behavior:
- No capability is assumed from GPU model alone.
- CUDA compatibility is checked against actual runtime/driver evidence.
- NCCL is used for workloads that require distributed GPU communication.
- Multi-GPU tests use concrete GPU IDs.
- Multi-node tests verify actual inter-node distributed communication when the environment provides it.
- Topology discovery is stored separately from communication test results.
- NVIDIA-specific optimizations remain behind provider/runtime adapters.

Focused tests:
- Real capability probe parses available NVIDIA runtime evidence.
- Missing NVIDIA runtime is reported as unavailable rather than simulated.
- CUDA mismatch prevents placement.
- Multi-GPU allocation maps to distinct GPU identities.
- Required NCCL capability is verified.
- Topology metadata is captured without being treated as throughput proof.
- Multi-node communication verification is distinct from topology discovery.

Acceptance:
The code can prove what NVIDIA capabilities are actually present and refuse unsupported workloads.

### Subproject E: Legitimate free-compute provider adapters

Goal:
Allow legitimate free or user-authorized compute resources to enter the same fabric without hardcoding the system to one provider.

Proposed files:
- provider adapter modules under lead_engine/providers/
- provider registry/selection module
- provider contract tests
- provider lifecycle tests

Behavior:
- Normalize providers into the common resource contract.
- Record eligibility, authentication state, lifetime, quotas/limits where observable, and provider restrictions.
- Treat notebook/free-credit resources as ephemeral.
- Automatically use eligible configured providers when their documented access path permits.
- Surface required user authorization instead of circumventing it.
- Never scrape around quotas or bypass provider controls.
- Provider adapters cannot write Thorio business truth directly.

Focused tests:
- Provider identity maps correctly to normalized resources.
- Provider disappearance triggers resource withdrawal and recovery.
- Expiring free resources are not selected for incompatible long-running work.
- Authentication failure produces action-required/provider-unavailable state.
- Provider policy restrictions prevent unsupported scheduling.

Acceptance:
Multiple legitimate provider types can feed one scheduler without changing business authority.

### Subproject F: Surgical integration with the existing scheduler and production workflows

Goal:
Connect the physical fabric to the current continuous engine with the smallest possible change.

Files to inspect before modification:
- lead_engine/scheduler.py
- lead_engine/compute_bridge.py
- lead_engine/agent_queue.py
- lead_engine/compute_pool.py
- .github/workflows/python.app.yml
- existing source collection and specialist drain modules
- Airtable synchronization and completion paths

Integration behavior:
- Existing source collection completion semantics remain unchanged.
- Existing backlog durability remains unchanged.
- Remote compute is an execution path, not a replacement queue.
- Scheduler reconciliation includes physical resources without changing business completion semantics.
- Source I/O scaling remains a separate capacity concern from GPU scheduling.
- Existing production workflow safeguards remain intact.
- Batch size remains 50 only where currently configured and remains a processing limit.
- Production workflow does not require the Android phone to stay connected.

Mandatory boundary:
The current remote bridge excludes outreach_closer and follow_up. Because the approved design now requires closer specialists to conduct full authorized outreach and follow-up autonomously, the actual closer implementation must be inspected end to end before changing this boundary. The inspection must cover:
- closer routing
- authorization
- outbound transport
- authentication
- sent-state reconciliation
- response ingestion
- conversation state
- follow-up state
- revenue-positive detection
- Partnership handoff creation

If a change is required, implementation stops at the boundary and presents the exact current behavior, dependency chain, incompatibility, smallest change, side effects, and verification plan for explicit approval. No protected closer subsystem is changed merely to connect compute.

Focused tests:
- Existing production queue regression suite remains intact.
- Source configured/success/failed/skipped semantics remain unchanged.
- Remote result persistence preserves existing specialist evidence semantics.
- No compute failure deletes an authoritative task.
- No remote result bypasses existing acceptance paths.
- Existing Airtable/referral/revenue tests remain regression gates.

Acceptance:
The fabric can be introduced without changing protected business semantics.

### Subproject G: Specialist package, autonomous closer workflow, and final human handoff

Goal:
Support the approved full specialist sales workflow while preserving the final human boundary.

Prerequisite:
Completion of Subproject F inspection and explicit approval for any protected subsystem change.

Behavior:
- Complete Specialist Package is a hard readiness gate.
- Specialist receives opportunity identity, company context, decision makers, verified contact information, evidence/provenance, need/intent, Partnership Path, sales intelligence, conversation history, objections, follow-up state, authorization, and commercial information required by its contract.
- Specialist may perform authorized outreach, conversation handling, follow-up, objection handling, and continued follow-up autonomously.
- External action state remains distinct: prepared, queued, attempted, transport accepted, actually sent, response received, conversation active, revenue-positive.
- A sent/opened/replied message is never treated as revenue-positive by itself.
- Revenue-positive state requires actual authoritative evidence.
- After verified revenue-positive action, the system produces a complete Partnership Handoff Package.
- Partnership placement remains manual and final by the user.
- The compute layer cannot create revenue or commission truth independently.

Focused tests:
- Incomplete specialist package cannot enter ready state.
- Specialist cannot claim revenue-positive from message delivery alone.
- Sent-state reconciliation distinguishes transport acceptance from actual send.
- Follow-up requires valid closer authorization.
- Conversation state survives worker reassignment.
- Revenue-positive evidence reaches the user handoff.
- No automatic Partnership placement occurs.

Acceptance:
The complete authorized closer path can run without per-message user approval and stops for the user only at verified revenue-positive handoff.

### Subproject H: Android-first operational visibility

Goal:
Expose actual fabric, pipeline, closer, Airtable, and revenue-positive state through the existing control surface without making Android a compute dependency.

Proposed files:
- existing control/dashboard modules identified during inspection
- new status aggregation module only if required
- focused dashboard/status contract tests

Behavior:
- User view reports business-first health and meaningful action-required states.
- Advanced diagnostics expose providers, nodes, GPUs, leases, retries, quarantine, reconciliation, and synchronization.
- Engineering evidence exposes execution attempt and resource identity chains.
- Dashboard status is evidence-derived and cannot manufacture green.
- Phone disconnect does not stop execution.

Focused tests:
- Dashboard status matches underlying evidence.
- Provider/GPU failure appears as recovery/action-required state rather than false healthy.
- Backlog and execution counts distinguish processing capacity from completion.
- Revenue-positive handoff is visible only after authoritative evidence.

Acceptance:
Normal operation requires no terminal, CUDA, Kubernetes, SSH, or infrastructure administration by the user.

## 4. Cross-cutting verification matrix

Every subproject must pass the applicable layers:

### Unit
Dataclass validation, matching, state transitions, provider normalization, lease rules.

### Contract
Provider/resource/workload/result schemas, execution identity, authorization, evidence provenance.

### Integration
Inventory to scheduler, scheduler to coordinator, coordinator to worker, worker to result verification, bridge to authoritative queue.

### Pipeline
Discovery through backlog, research, evidence, qualification, need/intent, late dedupe, opportunity resolution, Partnership Path, complete closer package, specialist execution, external action state, revenue-positive evidence, user handoff.

### Production
Fresh GitHub Actions evidence from actual production workflows, not inferred local success. Existing production workflows remain regression gates.

## 5. Failure-injection acceptance suite

Before production promotion, exercise at minimum:
- worker process loss
- GPU loss
- node loss
- provider disappearance
- coordinator restart
- scheduler restart
- network partition
- lease expiration
- duplicate completion
- duplicate publication/reconciliation
- checkpoint resume
- artifact availability failure
- provider authentication failure
- quarantined resource admission attempt
- source collection partial failure
- Airtable synchronization failure
- stale specialist execution state
- revenue-positive evidence missing or invalid

For every case verify:
1. Authoritative work remains durable.
2. No false completion is written.
3. Lease/resource state becomes recoverable.
4. Diagnostics survive the failure.
5. Eligible work can resume or be reassigned.
6. The next stage does not receive an unverified result.

## 6. Production rollout sequence

1. Complete inventory/provider contracts without changing existing scheduling.
2. Verify inventory independently.
3. Add physical capability matching and scheduler in an isolated execution path.
4. Verify single-GPU allocation.
5. Verify multi-GPU allocation.
6. Verify multi-node allocation where real resources exist.
7. Verify CUDA/driver/NCCL/topology evidence.
8. Verify failure recovery and reconciliation.
9. Connect the fabric to existing scheduler interfaces without changing backlog authority.
10. Run full regression suite.
11. Run production workflow verification.
12. Inspect closer boundary before any closer integration change.
13. If closer changes are required, stop and obtain explicit approval for those protected changes.
14. Verify complete specialist package and external-action state machine.
15. Verify revenue-positive evidence and manual Partnership handoff.
16. Verify Android evidence-derived status.
17. Run the complete end-to-end acceptance path.
18. Only after fresh evidence and explicit promotion approval may the branch be promoted to main.

No PR is created at any step.

## 7. Observable decisions already fixed by the approved design

The following are not open decisions:
- hierarchical fabric
- NVIDIA as premier path
- provider-neutral architecture
- legitimate free compute only
- no artificial node/GPU ceiling
- physical GPU identity
- multi-GPU and multi-node support
- durable leases and recovery
- artifact references/checkpointing where appropriate
- existing Thorio queue remains authoritative
- late deduplication
- specialist autonomy through revenue-positive action
- user handoff after verified revenue-positive action
- manual Partnership placement
- Android-first operation
- no pull requests
- no fake green or test manipulation

## 8. Decision seams that must remain evidence-driven

These are implementation seams, not unresolved product choices:
- Exact provider API/admission mechanism varies by provider and must use the provider's documented, authorized interface.
- Exact database/storage representation for the resource inventory will be chosen after inspecting existing persistence capabilities to avoid unnecessary migration.
- Exact GPU runtime probe commands depend on the host/provider image and must report unavailable rather than fabricate evidence.
- Exact artifact backend will reuse an existing durable artifact mechanism if one is already present; otherwise the smallest additive mechanism will be selected without moving business truth into artifacts.
- Exact dashboard integration path depends on the current control surface and will be selected after inspection.
- Exact closer transport integration depends on the current protected closer implementation. No change is authorized merely by this plan.

## 9. Implementation gate

This plan is ready for user review.

Code implementation must not begin until this implementation plan is explicitly approved.

After plan approval, work proceeds subproject by subproject, with each independently verified before the next integration layer is changed. Any protected subsystem requiring a behavior change is a separate approval gate.

