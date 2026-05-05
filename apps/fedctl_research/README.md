# fedctl_research

Flower application for the dissertation experiments.

This app owns three things:

- the method implementations used in the dissertation, including `fedavg`, `fedavgm`, `heterofl`, `fedrolex`, `fiarse`, `fedbuff`, and `fedstaleweight`
- the reusable task code for the current benchmark tasks
- the run-config TOMLs and deployment config templates used by `fedctl run` and `fedctl submit run`

## Layout

- `src/fedctl_research/app/`: generic Flower entrypoints
- `src/fedctl_research/methods/`: method-specific logic
- `src/fedctl_research/tasks/`: benchmark task implementations
- `run_configs/`: application-side run-config families
- `deploy_configs/`: deploy config presets for placement, resources, and network shaping

## Example

```bash
cd /Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl
.venv/bin/fedctl submit run apps/fedctl_research \
  --run-config apps/fedctl_research/run_configs/compute_heterogeneity/main/fashion_mnist_cnn/heterofl.toml \
  --deploy-config apps/fedctl_research/deploy_configs/compute_heterogeneity/main/none.yaml \
  --exp heterofl-fmnist-cnn-main \
  --stream --destroy
```

## Experiment families

Application-side configs are organized by study family:

- `run_configs/smoke/`: fast validation split into compute-heterogeneity and network-heterogeneity smoke paths
- `run_configs/compute_heterogeneity/`: headline mixed `rpi4`/`rpi5` model-heterogeneity study plus its supporting ablations
- `run_configs/network_heterogeneity/`: buffered-asynchronous study plus its supporting ablations

For the scientific queue, method-level justification, and dissertation-facing run structure, use:

- `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/docs/experiment_plan.md`

Deploy config presets live under `deploy_configs/`:

- `deploy_configs/smoke/compute_heterogeneity.yaml`: 4-node compute-heterogeneity smoke validation
- `deploy_configs/smoke/network_heterogeneity.yaml`: 4-node network-heterogeneity smoke validation
- `deploy_configs/compute_heterogeneity/main/none.yaml`: 12-node balanced mixed-hardware main-study profile with no impairment
- `deploy_configs/network_heterogeneity/main/mixed/none.yaml`: 15-node mixed-device async main-study profile with no impairment
- `deploy_configs/network_heterogeneity/main/all_rpi5/none.yaml`: 15-node all-RPi5 async main-study profile with no impairment
- `deploy_configs/network_heterogeneity/ablations/deployment_stressors/*.yaml`: network-heterogeneity stressor presets, including named impairment profiles
- `deploy_configs/network_heterogeneity/ablations/scale_concurrency/scale_async/*.yaml`: larger-cluster scaling profiles

## W&B

W&B is logged from the server side only, so one remote experiment corresponds to one W&B run.
Configure the environment injection in the deploy config and enable logging in the run-config TOML.
The checked-in deploy configs are templates, so replace their placeholder values before using them against a real cluster.

## More detail

- `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/docs/fedctl_overview.md`
- `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/docs/submit_service_pipeline.md`
- `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/docs/experiment_plan.md`
