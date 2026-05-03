# Dissertation Experiment Plan

This document is the authoritative source for the dissertation experiment programme. The application-side run-config tree under `apps/fedctl_research/run_configs/` defines the scientific comparisons, while deployment configs under `apps/fedctl_research/repo_configs/` define placement, resources, and network shaping. The plan below is therefore organized around **paper claims and required evidence**, not just around config directories.

## Implemented methods and dissertation structure

The application implements `fedavg`, `fedavgm`, `heterofl`, `fedrolex`, `fiarse`, `fedbuff`, and `fedstaleweight`.

The dissertation uses two headline study families:

- **Compute heterogeneity**: `fedavg`, `heterofl`, `fedrolex`, `fiarse`
- **Network heterogeneity**: `fedavg`, `fedavgm`, `fedbuff`, `fedstaleweight`

The headline studies are the main story. Method-specific supporting studies then justify that each implemented method is being evaluated on the axes that matter in its original paper.

## Headline cluster assumptions

The headline studies now use two live rack profiles rather than one universal pool:

- compute-main `cifar10_cnn` and `california_housing_mlp`: `10 x rpi4` + `10 x rpi5`
- remaining headline studies: balanced `6 x rpi4` + `6 x rpi5`

Shared headline settings:

- `fraction-train = 1.0`
- `fraction-evaluate = 1.0`

Device settings:

- `rpi4`: `batch-size = 8`
- `rpi5`: `batch-size = 32`

Natural equal-split dataset caps for the live IID headline studies:

- compute-main `cifar10_cnn` on the `20`-node rack: `max-train-examples = 2500`, `max-test-examples = 500`
- compute-main `california_housing_mlp` on the `20`-node rack: `max-train-examples = 826`, `max-test-examples = 207`

Headline schedules:

- **Compute main**
  - `cifar10_cnn`: `20` rounds, `local-epochs = 3`, `learning-rate = 0.05`
  - `california_housing_mlp`: `20` rounds, `local-epochs = 3`, `learning-rate = 0.001`
- **Network main**
  - synchronous baselines: `15/20` rounds
  - buffered async methods: `15/20` server steps
  - low-concurrency CIFAR-10 branch: `buffer-size = 5`, `train-concurrency = 20`
  - high-concurrency CIFAR-10 branch: `buffer-size = 10`, `train-concurrency = 50`
  - default `fedbuff` weighting: `polynomial`, `staleness-alpha = 0.5`

## Completed validation runs

Completed smoke checks:

- `smoke-fedavg-fmnist-mlp-seed1337`
- `smoke-heterofl-fmnist-mlp-seed1337`

Completed headline pilots:

- legacy compute-main pilot: `fedavg`, `heterofl`, `fedrolex`, `fiarse` on `fashion_mnist_cnn`, seed `1337`
- network main: `fedavgm`, `fedbuff`, `fedstaleweight` on `fashion_mnist_cnn`, seed `1337`

These pilots already validated the real cluster path. The active compute-main task pair is now `cifar10_cnn` plus `california_housing_mlp`, so the remaining work is the full seeded sweeps and the supporting studies required to make the method claims paper-faithful.

## Evidence matrix

| Method | Paper claim to reproduce | Metric / evidence required | Closest repo experiment family | Status | Dissertation location |
|---|---|---|---|---|---|
| `HeteroFL` | Mixed-capacity subnetworks improve efficiency while preserving one global model, including fixed/dynamic capacity settings and balanced non-IID robustness | Global accuracy, local/submodel accuracy, capacity-level comparisons, non-IID local/global results | `compute_heterogeneity/main/`, `compute_heterogeneity/ablations/capacity_design/uniform_five_levels/`, `compute_heterogeneity/ablations/capacity_design/capacity_distribution/`, `compute_heterogeneity/ablations/robustness_extension/non_iid/` | Partial | Main text for headline compute study; appendix for five-level and non-IID detail |
| `FedRolex` | Rolling extraction reduces the gap to homogeneous FL, supports larger server models, and improves inclusiveness | Gap-to-baseline accuracy, large-server comparison, participation/coverage evidence | `compute_heterogeneity/main/`, `compute_heterogeneity/ablations/capacity_design/capacity_distribution/`, `compute_heterogeneity/ablations/method_mechanisms/large_server/`, `compute_heterogeneity/ablations/participation_coverage/inclusiveness/` | Partial | Main text for compute study and large-server headline note; appendix for inclusiveness sweeps |
| `FIARSE` | Importance-aware extraction improves over simpler partial-training policies and thresholding choices matter | Global accuracy, local/submodel accuracy, threshold comparison | `compute_heterogeneity/main/`, `compute_heterogeneity/ablations/method_mechanisms/fiarse_thresholds/` | Partial | Main text for compute study; appendix for threshold studies |
| `FedBuff` | Buffered async improves time-to-quality and scales with concurrency/buffer size | Accuracy-vs-step or time, target-accuracy attainment, client trips, concurrency and buffer sensitivity | `network_heterogeneity/main/`, `network_heterogeneity/ablations/scale_concurrency/scale_async/`, `network_heterogeneity/ablations/scale_concurrency/buffer_k/`, `network_heterogeneity/ablations/deployment_stressors/netem/` | Partial | Main text for async headline study; appendix for scale and buffer sweeps |
| `FedStaleWeight` | Fair stale-update weighting improves fairness and accuracy when slow devices hold distinct data | Global accuracy, fairness-oriented device-group comparison, device-correlated skew results | `network_heterogeneity/main/`, `network_heterogeneity/ablations/stale_update_control/staleness_weighting/`, `network_heterogeneity/ablations/deployment_stressors/device_correlated_non_iid/` | Partial | Main text for fairness interpretation in async study; appendix for stale-weighting and skew sweeps |

## Method-by-method paper-faithful plan

### HeteroFL

Current interpolation evidence update (2026-04-13): the first fixed-assignment CIFAR-10 `a_e` slice (`e`, `p001`-`p009`, seed `1337`) completed cleanly and produced a strictly monotonic increase in final global accuracy from `0.4870` at singleton `e` to `0.6785` at `p009`. This is the expected paper-faithful direction for the `a-e` interpolation figure and is strong enough to justify continuing with the remaining headline pair families `b_e`, `c_e`, and `d_e` before expanding to the appendix-only pair grid.


**Original paper claim**

HeteroFL argues that clients with different compute budgets can train nested subnetworks yet still contribute to one global model. The paper emphasizes fixed versus dynamic complexity assignment, five computation levels `a`-`e`, and robustness under balanced non-IID partitions.

**What the paper measures**

The paper reports:

- interpolation across five model sizes
- fixed versus dynamic complexity assignment
- IID and balanced non-IID settings
- both **Global** and **Local** results under non-IID
- supporting ablations for sBN, Scaler, and Masked Cross-Entropy

**Closest existing experiment families in this repo**

- `compute_heterogeneity/main/`
- `compute_heterogeneity/ablations/capacity_design/uniform_five_levels/`
- `compute_heterogeneity/ablations/capacity_design/capacity_distribution/`
- `compute_heterogeneity/ablations/robustness_extension/non_iid/`

**What is already covered**

- the real-hardware mixed-capacity headline comparison
- a five-level capacity family
- non-IID robustness families for Fashion-MNIST and CIFAR-10
- submodel evaluation support in the runtime/artifact layer

**Current compute-main CIFAR-10 headline allocation**

The official compute-main `cifar10_cnn` study now uses a hardware-constrained fixed four-level split on `20` nodes:

- `10 x rpi4`, `10 x rpi5`
- `model-rate-levels = [1.0, 0.5, 0.25, 0.125]`
- deterministic exact assignment:
  - `rpi4`: `5 x 0.125`, `5 x 0.25`
  - `rpi5`: `5 x 0.5`, `5 x 1.0`

This replaces the earlier `12`-node two-level device-default setup for the CIFAR-10 compute-main headline study.

**What is missing**

- a fixed pairwise interpolation family matching the paper's `Fix` figures
- an explicit dynamic-capacity reproduction on the current rack
- the paper's normalization/scaler ablations as first-class experiment families
- WikiText2-scale reproduction

**What goes in main text vs appendix**

- **Main text**: headline compute study, including global accuracy and weaker-device/submodel behavior
- **Appendix**: five-level capacity tables, non-IID local/global tables, and any dynamic-capacity follow-up

**Paper-faithful interpolation plan**

This is the next HeteroFL-specific supporting family to add. The goal is to reproduce the paper's fixed-assignment interpolation logic rather than reuse the current dynamic `a-b-c-d-e` run.

- New planned family: `compute_heterogeneity/ablations/capacity_design/fixed_pair_interpolation/`
- Dataset/task: `cifar10_cnn`
- Method: `heterofl`
- Assignment mode: `Fix`
- Active client count per run: `10`
- Why `10`, not `12`: the original paper interpolates with `10%` steps. Using `10` active logical clients gives exact `10%` increments without distorting the x-axis. This is a supporting-study design choice, not a new headline-rack default.
- Level mapping:
  - `a = 1.0`
  - `b = 0.5`
  - `c = 0.25`
  - `d = 0.125`
  - `e = 0.0625`
- Keep fixed across the family:
  - IID partitioning
  - same total active client count
  - same total local epochs, learning rate, and round budget
  - same evaluation protocol

**Interpolation run matrix**

Run singleton baselines first:

- `a`
- `b`
- `c`
- `d`
- `e`

Then run all pairwise interpolation families:

- `a-b`
- `a-c`
- `a-d`
- `a-e`
- `b-c`
- `b-d`
- `b-e`
- `c-d`
- `c-e`
- `d-e`

For each pair `x-y`, run the following fixed mixtures:

- `10%x + 90%y`
- `20%x + 80%y`
- `30%x + 70%y`
- `40%x + 60%y`
- `50%x + 50%y`
- `60%x + 40%y`
- `70%x + 30%y`
- `80%x + 20%y`
- `90%x + 10%y`

The pure endpoints are taken from the singleton baselines, so the plotted curve for `x-y` is:

- `y` baseline
- `10%x + 90%y` through `90%x + 10%y`
- `x` baseline

This gives:

- `5` singleton runs
- `10 x 9 = 90` pairwise interpolation runs
- `95` single-seed HeteroFL runs for the full paper-faithful interpolation package

**What this family measures**

- final global accuracy versus average model-parameter ratio
- whether adding a minority of stronger clients lifts the federation above the pure weaker-client baseline
- whether the accuracy trend is monotonic as stronger-client share increases
- whether extracted final submodels preserve the expected ordering `a > b > c > d > e`

**Metrics required**

- global final accuracy and loss
- global accuracy by round
- final extracted submodel accuracy for the active levels in the pair
- realised assignment counts per level
- actual average model-parameter ratio implied by the assignment
- round duration and client throughput for system-cost context

**Expected result**

For each pair `x-y`, the interpolation curve should:

- start near the weaker singleton baseline `y`
- improve as the share of stronger level `x` increases
- approach, but usually remain below, the pure stronger singleton baseline `x`

This is the cleanest evidence for the HeteroFL claim that weak clients need not be the performance bottleneck if they are allowed to train smaller models while stronger clients contribute larger subnetworks.

**Main text vs appendix**

- **Main text**: one compact figure for the `a-e`, `b-e`, `c-e`, and `d-e` curves, because these most directly show how weak clients benefit from stronger partners
- **Appendix**: the full `10` pair grid and the singleton baseline table

### FedRolex

**Original paper claim**

FedRolex claims that rolling extraction trains the server model more evenly than static extraction, reduces the gap to homogeneous FL, can train a server model larger than the largest client model, and improves inclusiveness under heterogeneous device distributions.

**What the paper measures**

The paper focuses on:

- performance gap to homogeneous FL
- small-model and large-model regimes
- larger-server-than-client settings via server scaling
- inclusiveness under heterogeneous device distributions

**Closest existing experiment families in this repo**

- `compute_heterogeneity/main/`
- `compute_heterogeneity/ablations/capacity_design/capacity_distribution/`
- `compute_heterogeneity/ablations/method_mechanisms/large_server/`
- `compute_heterogeneity/ablations/participation_coverage/inclusiveness/`

**What is already covered**

- the headline rolling-extraction comparison against `fedavg`, `heterofl`, and `fiarse`
- `rho`-style capacity-distribution sweeps
- explicit large-server config families
- explicit inclusiveness sweeps

**What is missing**

- a writeup-facing homogeneous-gap table tying the headline results to the FedRolex claim directly
- an explicit emulated real-world device-distribution narrative beyond the current `rpi4`/`rpi5` split

**What goes in main text vs appendix**

- **Main text**: compute headline study and the larger-server claim
- **Appendix**: `rho` sweeps, inclusiveness sweeps, and secondary coverage tables

### FIARSE

**Original paper claim**

FIARSE argues that importance-aware structured extraction is better than simpler selection rules and that threshold strategy matters for how partial models are formed.

**What the paper measures**

The paper reports:

- local and global performance
- comparisons against simpler extraction rules
- threshold strategy studies such as layerwise versus global thresholding
- additional task extensions such as CIFAR-100 and AGNews

**Closest existing experiment families in this repo**

- `compute_heterogeneity/main/`
- `compute_heterogeneity/ablations/method_mechanisms/fiarse_thresholds/`

**What is already covered**

- the headline importance-aware method comparison on the mixed rack
- dedicated threshold-strategy sweeps
- local/submodel evaluation plumbing

**What is missing**

- CIFAR-100 and AGNews task extensions
- the sharding-wise threshold variant from the paper appendix

**What goes in main text vs appendix**

- **Main text**: compute headline study and the interpretation of FIARSE as importance-aware extraction
- **Appendix**: threshold tables and any extra extraction-mechanism studies

### FedBuff

**Original paper claim**

FedBuff argues that buffered asynchronous training scales to higher concurrency, improves time-to-quality, and remains attractive once buffer size and systems overlap are tuned.

**What the paper measures**

The paper emphasizes:

- accuracy as a function of time or server progress
- target-accuracy attainment
- client trips or update efficiency
- concurrency sensitivity
- buffer-size sensitivity

**Closest existing experiment families in this repo**

- `network_heterogeneity/main/`
- `network_heterogeneity/ablations/scale_concurrency/scale_async/`
- `network_heterogeneity/ablations/scale_concurrency/buffer_k/`
- `network_heterogeneity/ablations/deployment_stressors/netem/`

**What is already covered**

- the headline buffered-async study against synchronous baselines
- concurrency and buffer-size sweep families
- deployment-stressor profiles for network impairment
- event logging needed for time-vs-progress analysis

**What is missing**

- a formal analysis script and figure plan for time-to-target and client-trip reporting
- a dissertation-facing presentation that treats FedBuff as a scaling method rather than a final-accuracy-only method

**What goes in main text vs appendix**

- **Main text**: async headline study, including time-to-quality interpretation
- **Appendix**: concurrency, buffer-size, and network-impairment sweep tables and plots

### FedStaleWeight

**Original paper claim**

FedStaleWeight argues that buffered async learning is unfair to slow devices and that stale-update reweighting improves both fairness and global accuracy when slow devices hold distinct data.

**What the paper measures**

The paper emphasizes:

- fast-versus-slow device asymmetry
- device-correlated non-IID data assignment
- comparison against unweighted buffered averaging
- fairness-driven gains in global accuracy

**Closest existing experiment families in this repo**

- `network_heterogeneity/main/`
- `network_heterogeneity/ablations/stale_update_control/staleness_weighting/`
- `network_heterogeneity/ablations/deployment_stressors/device_correlated_non_iid/`

**What is already covered**

- a headline buffered-async comparison that includes `fedstaleweight`
- explicit stale-weighting sweeps
- a device-correlated non-IID family on the async branch

**What is missing**

- the exact synthetic `10` fast / `5` slow protocol from the paper
- a dissertation-facing fairness section that reports device-group outcomes explicitly rather than only final global accuracy

**What goes in main text vs appendix**

- **Main text**: fairness interpretation inside the async headline study
- **Appendix**: stale-weighting sweeps and device-correlated skew comparisons

## Remaining execution queue

### Headline sweeps

1. **Full compute-main sweep**
   - methods: `fedavg`, `heterofl`, `fedrolex`, `fiarse`
   - tasks: `fashion_mnist_cnn`, `cifar10_cnn`
   - seeds: `1337`, `1338`, `1339`
   - total: `24` runs
2. **Full network-main sweep**
   - methods: `fedavg`, `fedavgm`, `fedbuff`, `fedstaleweight`
   - tasks: `fashion_mnist_cnn`, `cifar10_cnn`
   - seeds: `1337`, `1338`, `1339`
   - total: `24` runs

### Supporting studies to prioritize after headline sweeps

- **HeteroFL**
  - `compute_heterogeneity/ablations/capacity_design/uniform_five_levels/`
  - `compute_heterogeneity/ablations/robustness_extension/non_iid/`
- **FedRolex**
  - `compute_heterogeneity/ablations/capacity_design/capacity_distribution/`
  - `compute_heterogeneity/ablations/method_mechanisms/large_server/`
  - `compute_heterogeneity/ablations/participation_coverage/inclusiveness/`
- **FIARSE**
  - `compute_heterogeneity/ablations/method_mechanisms/fiarse_thresholds/`
- **FedBuff**
  - `network_heterogeneity/ablations/scale_concurrency/scale_async/`
  - `network_heterogeneity/ablations/scale_concurrency/buffer_k/`
- **FedStaleWeight**
  - `network_heterogeneity/ablations/stale_update_control/staleness_weighting/`
  - `network_heterogeneity/ablations/deployment_stressors/device_correlated_non_iid/`

## Remaining ablation run checklist

This section turns the evidence matrix into the concrete post-headline execution list. A family should only be marked complete once at least one run from that family produces the evidence named here.

### Compute heterogeneity

- [ ] `compute_heterogeneity/ablations/capacity_design/uniform_five_levels/`
  - Paper link: `HeteroFL`
  - Required evidence: five-level capacity interpolation beyond the two-level rack story
  - Minimum dissertation deliverable: one table showing global accuracy across the five-level capacity family
  - Pilot status on 2026-04-09: instrumentation is sufficient and the family is now runnable after fixing width materialization for submodels below `0.25`.
  - Evidence confirmed by the clean pilot:
    - `evaluation_events.jsonl` records global accuracy by round
    - `client_update_events.jsonl` records the realised per-update `model_rate`, `device_type`, throughput, and duration
    - `server_step_events.jsonl` records round-level system cost
    - `submodel_evaluation_events.jsonl` plus W&B summary metrics remain the right surface for final width-specific evaluation
  - Interpretation note: this family is the dynamic all-five-level table-style companion, not the fixed interpolation figure itself.
  - Current blocking item before marking this family complete: aggregate the final per-rate/global table from the clean pilot and pair it with the new fixed interpolation family.
- [ ] `compute_heterogeneity/ablations/capacity_design/fixed_pair_interpolation/`
  - Paper link: `HeteroFL`
  - Required evidence: fixed-assignment pairwise interpolation curves over average model parameters
  - Minimum dissertation deliverable: singleton baselines `a`-`e` plus pairwise curves for `a-b`, `a-c`, `a-d`, `a-e`, `b-c`, `b-d`, `b-e`, `c-d`, `c-e`, and `d-e`
  - Planned protocol:
    - use `10` active logical clients so mixture weights are exact `10%` steps
    - keep task, round budget, and optimizer settings fixed
    - sweep `10%x + 90%y` through `90%x + 10%y` for each pair `x-y`
  - Main-text subset:
    - `a-e`, `b-e`, `c-e`, `d-e`
  - Appendix subset:
    - all `10` pairs plus singleton baseline table
- [ ] `compute_heterogeneity/ablations/robustness_extension/non_iid/`
  - Paper link: `HeteroFL`
  - Required evidence: balanced non-IID robustness with both global and local/submodel views
  - Minimum dissertation deliverable: one non-IID comparison table and one short interpretation paragraph
- [ ] `compute_heterogeneity/ablations/capacity_design/capacity_distribution/`
  - Paper link: `FedRolex`
  - Required evidence: `rho`-style capacity-distribution sensitivity and gap-to-homogeneous interpretation
  - Minimum dissertation deliverable: one sweep plot or table tying the trend back to the FedRolex claim
- [ ] `compute_heterogeneity/ablations/method_mechanisms/large_server/`
  - Paper link: `FedRolex`
  - Required evidence: larger-server-than-client comparison
  - Minimum dissertation deliverable: one focused result showing whether larger server width materially helps
- [ ] `compute_heterogeneity/ablations/participation_coverage/inclusiveness/`
  - Paper link: `FedRolex`
  - Required evidence: inclusiveness or coverage under broader device-capacity variation
  - Minimum dissertation deliverable: one appendix table tied explicitly to the inclusiveness claim
- [ ] `compute_heterogeneity/ablations/method_mechanisms/fiarse_thresholds/`
  - Paper link: `FIARSE`
  - Required evidence: threshold-strategy comparison, especially `global` versus `layerwise`
  - Minimum dissertation deliverable: one appendix comparison table and one sentence on why the chosen threshold mode is retained

### Network heterogeneity

- [ ] `network_heterogeneity/ablations/scale_concurrency/scale_async/`
  - Paper link: `FedBuff`
  - Required evidence: concurrency sensitivity and stronger async scaling story
  - Minimum dissertation deliverable: one time-to-quality or progress-to-quality plot across concurrency levels
- [ ] `network_heterogeneity/ablations/scale_concurrency/buffer_k/`
  - Paper link: `FedBuff`
  - Required evidence: buffer-size sensitivity
  - Minimum dissertation deliverable: one appendix table or curve over `K`
- [ ] `network_heterogeneity/ablations/deployment_stressors/netem/`
  - Paper link: `FedBuff`
  - Required evidence: async behavior under controlled network impairment
  - Minimum dissertation deliverable: one comparison showing whether impairment widens the async advantage
- [ ] `network_heterogeneity/ablations/stale_update_control/staleness_weighting/`
  - Paper link: `FedStaleWeight`
  - Required evidence: direct comparison between stale-update weighting rules
  - Minimum dissertation deliverable: one appendix table contrasting `FedBuff` weighting variants with `FedStaleWeight`
- [ ] `network_heterogeneity/ablations/deployment_stressors/device_correlated_non_iid/`
  - Paper link: `FedStaleWeight`
  - Required evidence: fairness under device-correlated skew rather than generic async accuracy only
  - Minimum dissertation deliverable: one figure or table with a fairness-oriented interpretation of the slow-device group

### Explicitly out of scope unless the cluster plan expands

- HeteroFL WikiText2 reproduction
- HeteroFL sBN/Scaler ablation family as a full reproduction package
- FIARSE AGNews and CIFAR-100 extensions
- FedStaleWeight's exact synthetic `10` fast / `5` slow simulation protocol

## Deployment presets

Use these deployment config templates with the application-side configs:

- `apps/fedctl_research/repo_configs/smoke/compute_heterogeneity.yaml`
- `apps/fedctl_research/repo_configs/smoke/network_heterogeneity.yaml`
- `apps/fedctl_research/repo_configs/compute_heterogeneity/main/none.yaml`
- `apps/fedctl_research/repo_configs/network_heterogeneity/main/mixed/none.yaml`
- `apps/fedctl_research/repo_configs/network_heterogeneity/ablations/deployment_stressors/*.yaml`
- `apps/fedctl_research/repo_configs/network_heterogeneity/ablations/scale_concurrency/scale_async/*.yaml`

## Practical rule

Do not start broad supporting sweeps until the full headline sweeps are complete and the evidence matrix above shows which paper claims are still only partially covered.
