# heterofl_fedctl

A modern Flower `ServerApp`/`ClientApp` scaffold for a fixed-rate HeteroFL
implementation designed to run under `fedctl`.

## Purpose

This directory is separate from `refs/heterofl/`, which contains the historical
Flower baseline implementation. The goal here is not to preserve that older API,
but to port the core HeteroFL ideas into the current Flower framework.

## What is implemented

- modern Flower app structure
- fixed-rate client model selection
- one width-scaled CNN for Fashion-MNIST
- server-side parameter slicing
- masked aggregation back into the global model

## Capability discovery

The current Flower `Grid` API does not expose node metadata directly to the
strategy. This scaffold handles that by running a lightweight `query` round
before training:

1. `fedctl` injects `FEDCTL_DEVICE_TYPE`, `FEDCTL_INSTANCE_IDX`, and optionally
   `FEDCTL_NOMAD_NODE_ID` into each client runtime
2. each `ClientApp` replies to a capability query with its `device-type`
3. the `ServerApp` builds `Flower node_id -> device_type`
4. the strategy resolves `Flower node_id -> model_rate`

The preferred configuration is therefore device-based:

- `rpi4-model-rate = 0.5`
- `rpi5-model-rate = 1.0`

Two manual overrides remain available for debugging:

- `heterofl-node-device-types = "<node_id>:<device_type>,..."`
- `heterofl-node-rates = "<node_id>:<rate>,..."`

## Package layout

- `heterofl_fedctl/task.py`: model and data pipeline
- `heterofl_fedctl/slicing.py`: HeteroFL slicing/merge logic
- `heterofl_fedctl/strategy.py`: fixed-rate HeteroFL strategy
- `heterofl_fedctl/client_app.py`: Flower ClientApp
- `heterofl_fedctl/server_app.py`: Flower ServerApp

## First milestone

Run a smoke test with:

- dataset: Fashion-MNIST
- partitioning: IID
- model rates:
  - slow tier: 0.5
  - fast tier: 1.0
- 3 to 5 rounds

The goal of the first milestone is correctness of slicing and aggregation, not
final benchmark quality.

## Recommended first commands

Local simulation:

```bash
cd /Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/refs/heterofl_fedctl
uv run flwr run . local-simulation
```

Remote smoke test via `fedctl`:

```bash
cd /Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl
fedctl run refs/heterofl_fedctl \
  --repo-config experiments/dissertation/repo_config/heterofl_smoke.yaml \
  --exp heterofl-smoke-4nodes \
  --supernodes rpi4=2 \
  --supernodes rpi5=2 \
  --stream \
  --no-destroy
```

Detailed notes:

- `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/experiments/dissertation/heterofl_smoke_test.md`
