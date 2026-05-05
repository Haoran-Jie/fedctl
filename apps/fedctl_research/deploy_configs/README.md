# Research App Deploy Configs

These YAML files are the deploy config presets used with:

- `fedctl run apps/fedctl_research ...`
- `fedctl submit run apps/fedctl_research ...`

They are intentionally checked in as reusable templates, not machine-specific copies.
Replace the submit/image-registry/W&B placeholders with the values for the cluster you are targeting.

## Families

- `smoke/compute_heterogeneity.yaml`: 4-node smoke validation paired with `run_configs/smoke/compute_heterogeneity/`.
- `smoke/network_heterogeneity.yaml`: 4-node smoke validation paired with `run_configs/smoke/network_heterogeneity/`.
- `compute_heterogeneity/main/none.yaml`: 4-node mixed `rpi4`/`rpi5` runs paired with `run_configs/compute_heterogeneity/main/`, with no netem sidecar.
- `network_heterogeneity/main/mixed/none.yaml`: 20-node mixed-device main-study profile paired with `run_configs/network_heterogeneity/main/cifar10_cnn/{iid,noniid}/mixed/`.
- `network_heterogeneity/main/all_rpi5/none.yaml`: 20-node packed all-RPi5 main-study profile paired with `run_configs/network_heterogeneity/main/cifar10_cnn/{iid,noniid}/all_rpi5/`.
- `network_heterogeneity/ablations/deployment_stressors/*.yaml`: named network impairment presets for the async stressor studies.
- `network_heterogeneity/ablations/scale_concurrency/scale_async/*.yaml`: larger-cluster deployment profiles paired with `run_configs/network_heterogeneity/ablations/scale_concurrency/scale_async/`.

## Placeholder fields

Replace these before running against a real cluster:

- `REPLACE_WANDB_API_KEY`
- `REPLACE_SUBMIT_ENDPOINT`
- `REPLACE_SUBMIT_TOKEN`
- `REPLACE_SUBMIT_USER`
- `REPLACE_SUBMIT_IMAGE`
- `REPLACE_ARTIFACT_STORE`
- `REPLACE_IMAGE_REGISTRY`
