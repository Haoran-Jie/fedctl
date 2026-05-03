Run config files are Flower `run_config` override TOML files.

They can be written in a nested, human-structured form. `fedctl run` and
`fedctl submit run` normalize them back into the flat key/value shape the Flower
app currently expects.

Use them with:

```bash
fedctl submit run apps/fedctl_research \
  --run-config apps/fedctl_research/run_configs/compute_heterogeneity/main/fashion_mnist_cnn/heterofl.toml
```

These files override `[tool.flwr.app.config]` values from `pyproject.toml`.

Recommended sections:

- `[run]`
- `[server]`
- `[client]`
- `[data]`
- `[model]`
- `[capacity]`
- `[devices.rpi4]` / `[devices.rpi5]`
- `[wandb]`
- `[fedrolex]` when needed

Recommended folder layout:

- `smoke/<family>/<task>/<method>.toml`
- `compute_heterogeneity/main/<task>/<method>.toml`
- `compute_heterogeneity/ablations/<group>/<study>/<task>/<method>.toml`
- `network_heterogeneity/main/<task>/<method>.toml`
- `network_heterogeneity/ablations/<group>/<study>/<task>/<method>.toml`

For repeated trials, you can also define a seed sweep:

```toml
[run]
method = "heterofl"
task = "fashion_mnist_cnn"
seeds = [1337, 1338, 1339]
```

`fedctl run` and `fedctl submit run` will detect this and launch one run per
seed automatically, appending `-seed<value>` to the experiment name.

Study guidance:

- `compute_heterogeneity/main/` is the headline mixed `rpi4`/`rpi5` result set.
- `compute_heterogeneity/ablations/capacity_design/four_levels/` uses 4 dynamic model-rate levels and should be presented as an algorithmic ablation.
- `compute_heterogeneity/ablations/robustness_extension/non_iid/` uses `partitioning = "label-skew-balanced"`.
- `compute_heterogeneity/ablations/method_mechanisms/large_server/` isolates the FedRolex large-server claim.
- `compute_heterogeneity/ablations/robustness_extension/preresnet18/` is the stronger CIFAR-10 model extension.
- `compute_heterogeneity/ablations/capacity_design/uniform_five_levels/` mirrors the paper's uniform 5-capacity PT setup.
- `compute_heterogeneity/ablations/participation_coverage/participation_rate/` adapts the paper's client-participation study to `25/50/100%` on a 4-node cluster.
- `compute_heterogeneity/ablations/capacity_design/capacity_distribution/` mirrors the paper's `rho` sweep between large and tiny client capacities.
- `compute_heterogeneity/ablations/participation_coverage/inclusiveness/` mirrors the paper's real-world device-distribution experiment.
