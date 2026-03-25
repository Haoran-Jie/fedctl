# HeteroFL Implementation Notes

This note defines the clean split between `fedctl` and the experiment app for the
first HeteroFL implementation.

## What `fedctl` provides

For each clientapp task, `fedctl` now injects stable runtime metadata via env vars:

- `FEDCTL_EXPERIMENT`
- `FEDCTL_INSTANCE_IDX`
- `FEDCTL_DEVICE_TYPE` if the supernode placement is typed

These are injected in:

- `src/fedctl/deploy/render.py`

This is enough for the app to map hardware class to HeteroFL capacity tier without
parsing job names or relying on Nomad internals.

## What the experiment app should implement

The app should own the HeteroFL algorithmic logic:

1. A fixed mapping from device type to model rate
2. A HeteroFL strategy which slices the global model per client
3. Index-aware or mask-aware aggregation back into the global model

For the first implementation, keep this static and minimal:

- `rpi4 -> model_rate = 0.5`
- `rpi5 -> model_rate = 1.0`

Do not start with dynamic reassignment by round.

## Recommended first app-side interface

The experiment app should expose a config block like:

```yaml
heterofl:
  enabled: true
  global_model_rate: 1.0
  fixed_model_rates:
    rpi4: 0.5
    rpi5: 1.0
```

At client startup:

1. Read `FEDCTL_DEVICE_TYPE`
2. Resolve the client's `model_rate`
3. Report that rate through logs and, if useful, metrics

At server strategy setup:

1. Compute parameter-index mappings for each active `model_rate`
2. During `configure_fit`, send the sliced parameter subset for the selected client
3. During `aggregate_fit`, merge updates back into the global model with matching
   indices

## Recommended first milestone

Prove one end-to-end fixed-rate HeteroFL run with:

- dataset: `Fashion-MNIST`
- partition: IID
- methods:
  - `fedavg-full`
  - `fedavg-small`
  - `heterofl`
- placements:
  - `rpi4=2`
  - `rpi5=2`
- rounds: 3 to 5

Success criteria:

- `rpi4` clients receive the small subnetwork
- `rpi5` clients receive the full subnetwork
- the server aggregates without shape or masking errors
- logs make the assigned `model_rate` explicit

## Why this split

The historical Flower HeteroFL baseline is useful as an algorithm reference, but it
bundles model-rate assignment, simulation-oriented client management, and
model-specific slicing logic into one older codebase. For this project:

- `fedctl` should remain the deployment and orchestration layer
- the experiment app should own the HeteroFL strategy and aggregation logic

That separation is cleaner, easier to test, and easier to evolve later when porting
to newer Flower APIs.
