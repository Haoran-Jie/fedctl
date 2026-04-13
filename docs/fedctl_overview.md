# fedctl Overview

This repository has two layers.

- `src/fedctl/`: the generic control plane for building, deploying, submitting, and inspecting Flower runs on the Nomad cluster
- `apps/fedctl_research/`: the dissertation Flower app, including methods, tasks, experiment TOMLs, and deployment-side repo-config templates

The important design boundary is:

- experiment config = scientific definition of the run
- repo config = deployment definition of the run

That split is what keeps model/method comparisons separate from placement and network conditions.

## Core commands

### Direct remote execution

```bash
fedctl run apps/fedctl_research \
  --experiment-config apps/fedctl_research/experiment_configs/smoke/compute_heterogeneity/fashion_mnist_mlp/heterofl.toml \
  --repo-config apps/fedctl_research/repo_configs/smoke/compute_heterogeneity.yaml
```

Use this when you want the workstation to drive the deploy-and-run flow directly.

### Queued remote execution

```bash
fedctl submit run apps/fedctl_research \
  --experiment-config apps/fedctl_research/experiment_configs/compute_heterogeneity/main/cifar10_cnn/fedrolex.toml \
  --repo-config apps/fedctl_research/repo_configs/compute_heterogeneity/main/none.yaml \
  --exp fedrolex-main-cifar10-cnn
```

Use this for the normal dissertation workflow. The submit service records the run, executes it remotely, and keeps logs/artifacts available after the original terminal session is gone.

### Inspection commands

```bash
fedctl submit ls
fedctl submit status <submission-id>
fedctl submit logs <submission-id>
fedctl submit results <submission-id>
```

## Repository responsibilities

- `src/fedctl/cli.py`: CLI entrypoint
- `src/fedctl/commands/`: command implementations
- `src/fedctl/deploy/`: Nomad rendering, submission, placement, and address resolution
- `src/fedctl/submit/`: submit-runner orchestration and result capture
- `submit_service/`: queue, API, and web UI for submissions
- `apps/fedctl_research/src/fedctl_research/`: methods, tasks, runtime helpers, partitioning, and W&B logging

## Deployment-side config usage

The deployment presets now live under `apps/fedctl_research/repo_configs/`.
They are checked in as templates, so replace cluster-specific endpoints, tokens, image registries, and W&B credentials before real runs.

The active families are:

- `smoke/compute_heterogeneity.yaml`
- `smoke/network_heterogeneity.yaml`
- `compute_heterogeneity/main/none.yaml`
- `network_heterogeneity/main/none.yaml`
- `network_heterogeneity/ablations/deployment_stressors/*.yaml`
- `network_heterogeneity/ablations/scale_concurrency/scale_async/*.yaml`

Anything older under `experiments/dissertation/` has been retired.
