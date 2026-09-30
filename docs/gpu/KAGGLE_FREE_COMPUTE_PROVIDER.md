# Kaggle free GPU provider

The GPU fabric now has a concrete zero-cost external provider adapter at
`lead_engine/kaggle_free_compute.py`.

## Provider contract

The adapter uses Kaggle's authenticated Kernels CLI to:

1. Read the current weekly GPU quota.
2. Refuse acquisition when the observed free GPU quota is exhausted or below the configured minimum.
3. Refuse acquisition when the managed kernel is already running or queued.
4. Create a private GPU script kernel with internet enabled.
5. Bound the requested run time by both the observed remaining quota and the adapter maximum.
6. Start the worker from the exact configured Thorio repository reference.
7. Pass coordinator credentials through Kaggle Secrets at worker runtime.
8. Attach the durable acquisition ID to the worker's physical discovery evidence.
9. Let the existing coordinator registration path verify the actual GPU UUID and physical evidence before trusted inventory promotion.
10. Delete the provider kernel when the acquisition is released.

Kaggle GPU notebook capacity is free and quota-controlled. The adapter does
not implement, call, or fall back to any paid capacity path.

## Required Kaggle account setup

Install and authenticate a current Kaggle CLI on the machine running the
Thorio coordinator.

The coordinator host needs:

- Kaggle API authentication for the account represented by
  `THORIO_KAGGLE_USERNAME`
- `kaggle` available on PATH
- GPU quota greater than zero
- permission to create and run private GPU kernels

The managed Kaggle worker needs two Kaggle Secrets:

- `THORIO_COMPUTE_COORDINATOR_URL`
- `THORIO_COMPUTE_AUTH_TOKEN`

The secret values are never written into the repository, acquisition evidence,
or durable enrollment records.

## Coordinator configuration

Set:

```text
THORIO_KAGGLE_ENABLED=1
THORIO_KAGGLE_USERNAME=<kaggle account>
THORIO_KAGGLE_KERNEL_SLUG=thorio-free-gpu-worker
THORIO_KAGGLE_ACCELERATOR=NvidiaTeslaT4
THORIO_KAGGLE_REPOSITORY_URL=https://github.com/DocSentinelX12/Thorio-Lead-Engine.git
THORIO_KAGGLE_REPOSITORY_REF=feature/gpu-fabric-foundation
```

Optional bounds:

```text
THORIO_KAGGLE_MINIMUM_REMAINING_HOURS=1
THORIO_KAGGLE_MAXIMUM_RUNTIME_HOURS=6
THORIO_KAGGLE_COMMAND_TIMEOUT_SECONDS=120
```

The coordinator remains free-only regardless of configuration. There is no
paid provider fallback.

## Acquisition flow

An authenticated control-plane request to:

```text
POST /fabric/acquisition/hunt
```

runs the existing durable acquisition manager's discovery and acquisition
sweep.

After the Kaggle kernel starts, the worker:

1. retrieves the two coordinator secrets from Kaggle Secrets;
2. clones the exact configured Thorio repository reference;
3. installs the repository requirements;
4. sets `THORIO_COMPUTE_ACQUISITION_ID`;
5. sets `THORIO_COMPUTE_DOMAIN`;
6. starts `lead_engine.compute_worker`.

The existing worker performs NVIDIA discovery before registration. The
coordinator's existing registration path rejects the worker unless the
acquisition identity matches and the observed GPU discovery is healthy with
stable GPU UUID evidence.

## Important physical validation boundary

A successful Kaggle API acquisition is not itself proof of a trusted GPU.

The authoritative promotion path remains:

`Kaggle acquisition -> authenticated worker registration -> NVIDIA runtime
discovery -> GPU UUID evidence -> physical fabric evidence -> trusted inventory`

Therefore a provider API success can never make a configured GPU become
trusted capacity by itself.
