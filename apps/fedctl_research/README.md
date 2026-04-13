# fedctl_research

Flower application for the dissertation experiments.

This app owns three things:

- the method implementations used in the dissertation, including `fedavg`, `fedavgm`, `heterofl`, `fedrolex`, `fiarse`, `fedbuff`, and `fedstaleweight`
- the reusable task code for the current benchmark tasks
- the experiment TOMLs and deployment-side repo-config templates used by `fedctl run` and `fedctl submit run`

## Layout

- `src/fedctl_research/app/`: generic Flower entrypoints
- `src/fedctl_research/methods/`: method-specific logic
- `src/fedctl_research/tasks/`: benchmark task implementations
- `experiment_configs/`: application-side experiment families
- `repo_configs/`: deployment-side presets for placement, resources, and network shaping

## Example

```bash
cd /Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl
.venv/bin/fedctl submit run apps/fedctl_research \
  --experiment-config apps/fedctl_research/experiment_configs/compute_heterogeneity/main/fashion_mnist_cnn/heterofl.toml \
  --repo-config apps/fedctl_research/repo_configs/compute_heterogeneity/main/none.yaml \
  --exp heterofl-fmnist-cnn-main \
  --stream --destroy
```

## Experiment families

Application-side configs are organized by study family:

- `experiment_configs/smoke/`: fast validation split into compute-heterogeneity and network-heterogeneity smoke paths
- `experiment_configs/compute_heterogeneity/`: headline mixed `rpi4`/`rpi5` model-heterogeneity study plus its supporting ablations
- `experiment_configs/network_heterogeneity/`: buffered-asynchronous study plus its supporting ablations

For the scientific queue, method-level justification, and dissertation-facing run structure, use:

- `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/docs/experiment_plan.md`

Deployment-side presets live under `repo_configs/`:

- `repo_configs/smoke/compute_heterogeneity.yaml`: 4-node compute-heterogeneity smoke validation
- `repo_configs/smoke/network_heterogeneity.yaml`: 4-node network-heterogeneity smoke validation
- `repo_configs/compute_heterogeneity/main/none.yaml`: 12-node balanced mixed-hardware main-study profile with no impairment
- `repo_configs/network_heterogeneity/main/none.yaml`: 12-node balanced async main-study profile with no impairment
- `repo_configs/network_heterogeneity/ablations/deployment_stressors/*.yaml`: network-heterogeneity stressor presets, including named impairment profiles
- `repo_configs/network_heterogeneity/ablations/scale_concurrency/scale_async/*.yaml`: larger-cluster scaling profiles

## W&B

W&B is logged from the server side only, so one remote experiment corresponds to one W&B run.
Configure the environment injection in the repo-config and enable logging in the experiment TOML.
The checked-in repo-configs are templates, so replace their placeholder values before using them against a real cluster.

## More detail

- `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/docs/fedctl_overview.md`
- `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/docs/submit_service_pipeline.md`
- `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/docs/experiment_plan.md`
