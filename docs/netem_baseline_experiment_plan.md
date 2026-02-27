# Revised Dissertation Benchmark Plan: Netem + Communication-Only

Updated: 2026-02-27

## 1) Summary

This benchmark campaign focuses on three dimensions only:

1. Netem fidelity (requested impairment vs applied impairment)
2. Communication volume (uplink/downlink bytes)
3. Timing (fit/eval/round/e2e runtime)

Removed from scope:

- model quality/convergence metrics
- client completion/participation ratios
- straggler/failure/cancelled/blocked count analyses

## 2) Measurement Approach (Hybrid)

Use two complementary paths:

- FedAvg app-level instrumentation in `pytorchexample`:
  - project path: `refs/quickstart-pytorch`
  - per-client, per-round protobuf size logging for fit/evaluate downlink/uplink
  - per-round timing logs (`fit_phase_time_s`, `eval_phase_time_s`, `round_end_to_end_time_s`)
- Message-level microbenchmark (`msgbench`) using `Grid.send_and_receive`:
  - project path: `refs/msgbench-tabular`
  - controlled request/reply payload sizes
  - deterministic client targeting
  - wall-clock send/receive latency and derived goodput

Flower run-level `bytes_sent`/`bytes_recv` can be used as a coarse sanity check only.

## 3) Metrics Contract

### 3.1 Netem Fidelity

- `profile_expected`
- `qdisc_applied`
- `delay_ms_applied`
- `jitter_ms_applied`
- `loss_pct_applied`
- `rate_mbit_applied`
- `fidelity_mismatch_count`

### 3.2 Timing

- `fit_phase_time_s[round]`
- `eval_phase_time_s[round]`
- `round_end_to_end_time_s[round]`
- `e2e_runtime_s` (submission started -> finished)

### 3.3 Communication

- `fit_downlink_bytes_proto[round, client]`
- `fit_uplink_bytes_proto[round, client]`
- `eval_downlink_bytes_proto[round, client]`
- `eval_uplink_bytes_proto[round, client]`
- `round_total_downlink_bytes_proto`
- `round_total_uplink_bytes_proto`
- `round_total_bytes_proto`

## 4) Raw/Parsed Artifacts

Recommended raw structure:

```text
results/netem_baseline/
  raw/<scenario>/<replicate>/
    submission.json
    submit.stdout.log
    supernodes.<task>.stdout.log
    supernodes.<task>.stderr.log
```

Parsed outputs:

- `runs.csv`: one row/run (scenario, replicate, status, e2e runtime, total bytes)
- `round_timing.csv`: per-round fit/eval/total timing
- `round_comm.csv`: per-client/per-round/proto bytes
- `qdisc.csv`: observed qdisc parameters + expected profile mapping
- `msgbench.csv`: per-round message benchmark latency/bytes/goodput rows

## 5) Benchmark Suite (Compact Core)

### Suite A: Netem Fidelity Validation

Goal: verify that requested profile assignments are actually applied.

- Scenarios: `none`, `med`, `high`, mixed single-node, ingress/egress asymmetry
- Replicates: 2 per scenario
- Output focus: `qdisc.csv`, fidelity heatmap

### Suite B: FedAvg Communication-Time Under Impairment

Goal: quantify communication and timing impact under netem.

- App: `pytorchexample` (`refs/quickstart-pytorch`) with communication JSON logs
- Scenarios: `S0_none`, `S2_med_all`, `S3_high_all`, `S4_mixed_single`, `S6_asym_dir`
- Replicates: 3 per scenario
- Controls: fixed model config/supernodes/images
- Output focus: `round_timing.csv`, `round_comm.csv`, `runs.csv`

### Suite C: Controlled Message-Size Benchmark

Goal: isolate transport behavior from model behavior.

- App: `msgbench` (`refs/msgbench-tabular`, standalone pyproject)
- Request sizes: `64KB`, `1MB`
- Reply sizes:
  - symmetric (`req == reply`)
  - asymmetric (`64KB -> 1MB`)
- Fanout: `1`, `3`
- Profiles: `none`, `high`, `asym`
- Replicates: 2 per scenario
- Output focus: `msgbench.csv`, latency/goodput curves

## 6) Figures

1. Netem fidelity heatmap (`expected` vs `applied`)
2. Round end-to-end time boxplot by scenario
3. Fit vs eval phase stacked timing by scenario
4. Uplink vs downlink bytes per round (FedAvg suite)
5. Message-size latency curves (msgbench suite)
6. Goodput (`bytes/sec`) vs payload size and fanout

## 7) Validation Checks

1. Byte helper unit tests on synthetic Fit/Evaluate messages.
2. Log parser unit tests for `[comm-json]` and round timing.
3. Integration smoke run for each suite on `none`.
4. Consistency check: summed per-client bytes == per-round totals.
5. Netem check: impaired tasks contain at least one qdisc evidence line.

## 8) Defaults and Assumptions

- Suite size is fixed to compact core.
- App-level protobuf serialization is the authoritative communication metric.
- Flower run-level traffic counters are optional coarse checks.
- Existing submit-service archived logs remain the post-run source of truth.
