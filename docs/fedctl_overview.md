# fedctl Overview

This repository has two layers.

- `src/fedctl/`: the generic control plane for building, deploying, submitting, and inspecting Flower runs on the Nomad cluster
- `apps/fedctl_research/`: the dissertation Flower app, including methods, tasks, experiment TOMLs, and deployment config templates under `repo_configs/`

The important design boundary is:

- experiment config = scientific definition of the run
- deploy config = deployment definition of the run

That split is what keeps model/method comparisons separate from placement and network conditions.

## Core commands

### Submit remote execution

```bash
fedctl submit run apps/fedctl_research \
  --experiment-config apps/fedctl_research/experiment_configs/smoke/compute_heterogeneity/fashion_mnist_mlp/heterofl.toml \
  --deploy-config apps/fedctl_research/repo_configs/smoke/compute_heterogeneity.yaml
```

Use `fedctl submit run` as the normal entrypoint; direct deploy/run commands are retained as hidden internal/debug commands.

### Named dissertation run

```bash
fedctl submit run apps/fedctl_research \
  --experiment-config apps/fedctl_research/experiment_configs/compute_heterogeneity/main/cifar10_cnn/fedrolex.toml \
  --deploy-config apps/fedctl_research/repo_configs/compute_heterogeneity/main/none.yaml \
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

The deployment configs now live under `apps/fedctl_research/repo_configs/`.
Fresh installs also get a user-level deploy config at `~/.config/fedctl/deploy-default.yaml`.
That generated config already points at the CamMLSys submit service, Nomad endpoint, artifact store, and cluster registry. Add only the submit-service bearer token (`submit.token`, or `FEDCTL_SUBMIT_TOKEN`) before running a project without a project-local deploy config.

Checked-in deployment configs are still used for named dissertation runs and specialized placement/network experiments. Treat those as templates for experiment-specific topology and W&B settings, not as the basic first-install setup.

The active families are:

- `smoke/compute_heterogeneity.yaml`
- `smoke/network_heterogeneity.yaml`
- `compute_heterogeneity/main/none.yaml`
- `network_heterogeneity/main/none.yaml`
- `network_heterogeneity/ablations/deployment_stressors/*.yaml`
- `network_heterogeneity/ablations/scale_concurrency/scale_async/*.yaml`

Anything older under `experiments/dissertation/` has been retired.
