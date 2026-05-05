# FedCover Spec

## Goal

FedCover is a proposed asynchronous model-heterogeneous FL method for `fedctl`.
It targets the gap between two existing method families:

- model-heterogeneous methods such as HeteroFL and FedRolex reduce weak-client
  compute by sending smaller dense submodels;
- asynchronous methods such as FedBuff and FedStaleWeight reduce wall-clock
  delay by accepting stale client updates.

The missing case is a real deployment where weak clients both train smaller
submodels and return updates at different times. A naive combination is not
enough, because buffered asynchronous aggregation assumes every accepted update
covers the same parameter set. In model-heterogeneous FL, that assumption is
false: low-rate clients update only a subset of the global model.

FedCover should answer:

> For a fixed model-rate assignment, can asynchronous training recover much of
> the wall-clock benefit of FedBuff while preserving the accuracy and
> local-submodel quality expected from model-heterogeneous training?

The primary comparison is therefore against synchronous HeteroFL/FedRolex and
their naive asynchronous variants, not against full-model FedAsync alone.

## Non-Goals

- Do not depend on FIARSE-style sparse/importance masks for the first version.
  Those are algorithmically interesting but slow on the current PyTorch/RPi
  stack without specialised sparse kernels.
- Do not try arbitrary per-parameter importance scoring in the first version.
  The first version should be cheap, dense, explainable, and robust enough for
  a dissertation experiment.
- Do not claim FedCover should beat full-model methods on raw accuracy. The fair
  claim is speed/accuracy trade-off under the same model-rate assignment.

## Core Idea

FedCover is FedBuff-style asynchronous buffering plus coverage-aware aggregation
for nested submodels.

In full-model FedBuff, every buffered update covers every parameter, so the
server can aggregate

```text
Delta = sum_i w_i Delta_i
```

where the weights `w_i` are normalised over the buffer.

In model-heterogeneous training, update `i` covers only parameters in its
submodel. If uncovered parameters are treated as zero updates and the aggregate
is still normalised by the full buffer size, higher-rate-only blocks can be
systematically under-updated. FedCover corrects this by tracking the observed
coverage mass of each nested model-rate block within the buffer and increasing
the contribution of under-covered blocks with a capped, damped multiplier.

For a block `b`:

```text
observed_mass_b = sum_i w_i * 1[update i covers block b]
safe_mass_b = max(min_observed_mass, observed_mass_b)
cover_gain_b = min(max_block_weight, max(1, safe_mass_b ^ (-coverage_power)))
Delta_b = cover_gain_b * sum_i w_i * Delta_{i,b}
```

Defaults should make this conservative:

```text
coverage_power = 0.5
max_block_weight = 2.0
min_observed_mass = 0.15
server_learning_rate = 0.5
```

This means a block covered by only one update in a buffer of five is helped, but
not multiplied by five. With `coverage_power = 0.5`, the raw correction for
coverage mass `0.2` is about `2.24`, then capped to `2.0`.

## Method Variants

### FedCover-H

First implementation target. Uses fixed HeteroFL-style nested slicing:

- lower-rate clients receive prefix/nested submodels;
- each model-rate level corresponds to a deterministic set of covered
  parameters;
- coverage correction is well defined and cheap.

This is the highest-probability variant because it reuses existing HeteroFL
slicing helpers and avoids ambiguity in block coverage.

### FedCover-R

Second-stage extension. Uses FedRolex rolling extraction:

- rolling windows mean the covered parameters for a given rate change by server
  step;
- coverage should be tracked from the actual `param_idx` mask, not only the
  scalar model rate.

Do not implement this until FedCover-H has a stable pilot result.

### FedCover-SW

Optional ablation. Uses FedStaleWeight's `fair` staleness weighting as the base
client weight before applying coverage correction. This tests whether coverage
correction adds value beyond stale-client reweighting.

This variant has higher instability risk, so it should keep the conservative
coverage cap and `server_learning_rate = 0.5`.

## Recommended Default Setup

Use a setup that maximises the chance of a meaningful improvement without
confounding the result.

### First Pilot

- Task: `cifar10_cnn`
- Data: non-IID, same Dirichlet/control setting as the network-main study where
  possible
- Topology: mixed `10 rpi4 + 10 rpi5`
- Deployment profile: `none`
- Seed: `1337`
- Model-rate assignment:
  - `rpi4`: five clients at `1/8`, five clients at `1/4`
  - `rpi5`: five clients at `1/2`, five clients at `1`
- Buffer size: `5`
- Train concurrency: `20` if the existing async setup supports all nodes
- Server learning rate: `0.5`
- Coverage power: `0.5`
- Max block weight: `2.0`
- Base staleness: `polynomial`, `alpha = 0.5`

This pilot should compare:

- `heterofl`
- `heterofl_fedbuff_naive`
- `heterofl_fedsw_naive`
- `fedcover_h`

The naive asynchronous baselines can share the FedCover implementation path with
coverage disabled, for example `coverage-power = 0.0` or
`max-block-weight = 1.0`. This keeps the comparison implementation-controlled:
the only intended difference between naive HeteroFL+FedBuff and FedCover-H is
the coverage correction.

If runtime budget allows, add:

- `fedrolex`
- `fedrolex_fedbuff_naive`
- `fedrolex_fedsw_naive`

The pilot should not include full-model `FedAsync` as a primary baseline. It can
be shown later as context, but it answers a different question.

### Main Grid

Only run this if the pilot is stable.

- Seeds: `1337`, `1338`, `1339`
- Profiles: `none`, `med`, `asym_up`
- Methods:
  - `heterofl`
  - `heterofl_fedbuff_naive`
  - `heterofl_fedsw_naive`
  - `fedcover_h`
  - optional `fedcover_h_sw`

Add FedRolex variants only if FedCover-H behaves sensibly and time remains.

## Why This Setup Has a High Probability of Improving

The desired improvement is not "beat every method on accuracy". The desired
improvement is a better Pareto point under fixed model capacity:

- compared with synchronous HeteroFL, FedCover should reduce wall-clock time
  because it avoids round-level straggler blocking;
- compared with naive HeteroFL+FedBuff, FedCover should improve accuracy or
  local-submodel quality because high-rate-only blocks are not diluted by
  updates that do not cover them;
- compared with HeteroFL+FedSW, FedCover should be more stable because it does
  not blindly amplify an entire stale update; it applies a capped correction to
  under-covered model blocks.

The conservative defaults improve the odds:

- `buffer-size = 5` matches the current network-main async setting and avoids
  very sparse buffers;
- `coverage_power = 0.5` makes correction sublinear;
- `max_block_weight = 2.0` prevents high-rate-only blocks from receiving a huge
  step when only one update covers them;
- `server_learning_rate = 0.5` compensates for noisier partial coverage;
- first testing `profile = none` separates algorithmic behaviour from netem
  effects.

## Implementation Plan

### Config Surface

Add `method = "fedcover"` as a first-class method. Keep the submodel extractor
explicit:

```toml
method = "fedcover"

[fedcover]
slicer = "heterofl"
base-staleness-weighting = "polynomial"
staleness-alpha = 0.5
buffer-size = 5
train-concurrency = 20
num-server-steps = 200
evaluate-every-steps = 5
server-learning-rate = 0.5
coverage-power = 0.5
max-block-weight = 2.0
min-observed-mass = 0.15
```

The implementation can map these to flattened run-config keys such as:

```text
fedcover-slicer
fedcover-base-staleness-weighting
fedcover-staleness-alpha
fedcover-buffer-size
fedcover-train-concurrency
fedcover-num-server-steps
fedcover-evaluate-every-steps
fedcover-server-learning-rate
fedcover-coverage-power
fedcover-max-block-weight
fedcover-min-observed-mass
```

Mirror the same keys in `apps/fedctl_research/pyproject.toml` and the
normalisation whitelist in `src/fedctl/project/run_config.py`.

### Server Loop

Reuse the FedBuff async loop structure, but dispatch submodels:

1. Discover node device types.
2. Build typed partition plan.
3. Build a `ModelRateAssigner` from existing HeteroFL config fields.
4. On dispatch:
   - assign model rate for the selected node;
   - build `param_idx` using HeteroFL slicing;
   - send only the sliced local state;
   - store `param_idx`, `model_rate`, and sent server version with the in-flight
     request.
5. On reply:
   - compute the local delta in local parameter space;
   - scatter-add the delta into global aggregate buffers using `param_idx`;
   - scatter-add the normalised client weight into coverage buffers for covered
     parameters or blocks.
6. On buffer flush:
   - compute coverage gain;
   - apply capped coverage correction;
   - update `current_state = current_state - eta_g * aggregate_delta`.

For MVP, implement tensor-level coverage using the same scatter masks needed to
merge local deltas. Log summaries by model-rate block for interpretability. This
costs one extra global-size coverage buffer during aggregation, which is
acceptable for the current CIFAR-10 CNN, and avoids a separate approximate block
mapper.

### Client Apps

Client train/evaluate can reuse the existing model-rate path:

- resolve model rate from message config;
- build the local model at that rate;
- train/evaluate using dense local tensors.

No sparse kernels are required.

### Logging

Add enough diagnostics to make the evaluation convincing:

- accepted updates by model rate;
- accepted updates by device type;
- aggregate applied weight by model rate;
- aggregate applied weight by device type;
- mean staleness by model rate/device;
- observed coverage mass per model-rate block;
- coverage gain per block;
- final local-submodel table, enabled with `submodel-local-eval-enabled=true`.

Suggested W&B keys:

```text
fedcover/coverage_mass_rate_0p125
fedcover/coverage_mass_rate_0p25
fedcover/coverage_mass_rate_0p5
fedcover/coverage_mass_rate_1p0
fedcover/coverage_gain_rate_0p125
fedcover/coverage_gain_rate_0p25
fedcover/coverage_gain_rate_0p5
fedcover/coverage_gain_rate_1p0
fairness/model_rate_weight_share_0p125
fairness/model_rate_weight_share_0p25
fairness/model_rate_weight_share_0p5
fairness/model_rate_weight_share_1p0
```

## Evaluation Claims

A successful result would support this claim:

> Combining asynchronous training with model-heterogeneous submodels is not a
> trivial composition. FedCover corrects the coverage dilution introduced by
> partial updates, recovering much of the asynchronous wall-clock benefit while
> preserving local-submodel quality better than naive buffered variants.

Primary table:

- method;
- target reached;
- client trips to target;
- elapsed time to target;
- final accuracy;
- worst-quartile local submodel accuracy;
- `rpi4` aggregate weight share;
- low-rate aggregate weight share.

Primary figure:

- x-axis: elapsed time to target;
- y-axis: worst-quartile local submodel accuracy or `rpi4`/low-rate weight
  share;
- marker colour: method;
- marker shape or facet: profile.

This makes the contribution visible as a Pareto result, not just a single
accuracy number.

## Failure Modes and Fallbacks

- If FedCover is unstable, lower `server-learning-rate` to `0.25` before
  changing the algorithm.
- If high-rate blocks overfit or become noisy, reduce `max-block-weight` to
  `1.5`.
- If FedCover behaves the same as naive FedBuff, increase `coverage-power` to
  `0.75` for a small ablation only.
- If FedCover improves accuracy but loses too much speed, keep the method but
  position it as a speed/quality trade-off rather than a universal winner.
- If FedRolex integration is messy, omit FedCover-R and keep the dissertation
  claim scoped to fixed nested submodels.

## Writeup Placement

Add FedCover after the existing compute/network evaluation is stable:

1. Related work: short paragraph saying model-heterogeneous and asynchronous FL
   are usually treated separately.
2. Implementation/methods: concise FedCover mechanism with one equation for
   coverage gain.
3. Evaluation: separate subsection framed as an extension study:
   "Can asynchronous buffering be safely combined with model-heterogeneous
   submodels?"

Do not insert strong claims until the pilot result is available.
