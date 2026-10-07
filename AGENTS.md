# Lead Engine Operating Rules

1. This repository is independent of Thorio and Sasquatch Story Studio. Never modify or depend on either.
2. Never commit credentials, tokens, cookies, passwords, or secrets.
3. Never automatically buy, upgrade, or enable paid services.
4. Never bypass authentication, CAPTCHAs, paywalls, robots restrictions, rate limits, or access controls.
5. Persist a lead before processing it further.
6. Never delete an uncertain duplicate automatically. Preserve it for human review.
7. Airtable is a sync destination; the local durable queue must remain authoritative until sync is confirmed.
8. Human verification is required before a lead is considered qualified.
9. Run all tests before declaring a change complete.

## Thorio compute-fabric non-negotiables

These rules are mandatory for every agent working on the compute fabric. Do not reinterpret, relax, or replace them.

1. The goal is an almost-24/7 automated free compute fabric for an independent individual: real runners, real GPUs, real CUDA, real NCCL where supported, automatic acquisition/recovery, and capability-aware distributed execution.
2. HARD $0 RULE: use only resources that are genuinely free to the user. No credit card, payment, paid fallback, paid upgrade, wallet, token purchase, subscription, or "free credits that eventually become billing."
3. HARD EXCLUSIONS: do not propose, integrate, or spend investigation time on Lightning, Google Colab, Modal, Saturn, Jupyter, grants, startup programs, institutional eligibility, nonprofit eligibility, registration-dependent research allocations, or similar programs that violate the $0 individual-access rule.
4. The user is an individual. Do not assume a corporation, startup, institution, lab, grant, research affiliation, or other special eligibility.
5. Kaggle GPU execution is already integrated and working. Do not present Kaggle as a new provider. Hugging Face ZeroGPU is also already integrated as API GPU execution, not a physical worker. NVIDIA integration already exists and must not be duplicated as a new provider.
6. The objective is to combine many eligible free sources and build missing adapters, runner bootstrap, networking, scheduling, routing, recovery, and execution layers where necessary. A source does not need to ship with a Thorio adapter already; an eligible building block can be integrated if it materially advances the fabric.
7. Prefer genuinely free individual-accessible GPU providers, volunteer/community GPU networks, P2P compute networks, free donated-GPU inference services, and open-source runner/networking projects. Verify their current access model before treating them as eligible.
8. For every candidate, verify the actual cost, individual eligibility, card/payment requirements, GPU reality, CUDA support, arbitrary-process capability, network topology, persistence/session limits, API/runner access, and recovery feasibility. Do not infer these from marketing language.
9. Never claim that GPU availability implies CUDA, NCCL, network reachability, multi-node capability, or physical identity. Prove each capability independently.
10. Never simulate physical GPU, CUDA, NCCL, multi-node networking, runner identity, or provider acquisition evidence. If a physical requirement cannot be proven, report it as unproven and fail closed where the production gate requires proof.
11. Preserve capability-specific routing. Do not send a workload to a provider that lacks a required capability merely because that provider has a GPU.
12. Preserve the lifecycle: discover -> authenticate -> verify -> acquire -> execute -> tolerate loss -> recover -> reacquire. Scarce resources must be cleaned up on failure.
13. Do not weaken, bypass, remove, or artificially lower production or physical-evidence gates to make CI pass.
14. Work directly on `main` unless the user explicitly instructs otherwise. Do not create a new branch for this work.
15. Make surgical changes after inspecting the actual current repository. Do not replace whole files unnecessarily, invent filenames, guess existing interfaces, create duplicate providers, or generate speculative workflows.
16. Keep the workflow surface small and understandable. Do not create multiple overlapping workflows when one existing workflow can be extended safely.
17. Test the smallest affected surface first, then run the relevant production/validation gates. Before saying a fix is complete, verify the actual repository state and the relevant CI result. If a run is pending, say pending.
18. When research finds an excluded or paid resource, do not present it as a candidate for the fabric. Move on to eligible free resources or determine what open-source building block can be built instead.
19. The user wants a large, composable fabric, not a single-provider solution. Continue looking for additional legitimate $0 sources and open-source networking/runner components when a capability gap remains.
20. Do not ask the user to supply technical values that the system can discover automatically. Prefer provider-neutral discovery, capability detection, and automatic routing.

