# HeteroFL Smoke Test

This is the first end-to-end validation target for the modern HeteroFL prototype
under `fedctl`.

## Goal

Validate four things:

1. `fedctl` deploys typed supernodes correctly
2. client runtimes receive `FEDCTL_DEVICE_TYPE`
3. the Flower `ServerApp` discovers `Flower node_id -> device_type` via `query`
4. sampled `rpi4` clients train with `model_rate=0.5` and sampled `rpi5` clients
   train with `model_rate=1.0`

## Project

- Flower app: `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/refs/heterofl_fedctl`
- Repo config: `/Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/experiments/dissertation/repo_config/heterofl_smoke.yaml`

## Local simulation first

Run this first to validate basic Flower app wiring before touching the cluster:

```bash
cd /Users/samueljie/Library/CloudStorage/OneDrive-UniversityofCambridge/Uni/Computer_Science/Year4/Dissertation/fedctl/refs/heterofl_fedctl
uv run flwr run . local-simulation
```

Expected result:

- app starts
- capability discovery completes
- 4 simulated nodes train for 3 rounds
- no slicing or aggregation shape errors

Note:

- local simulation will not naturally differentiate `rpi4` and `rpi5`
- if needed for debugging, use manual overrides:
  - `heterofl-node-device-types`
  - `heterofl-node-rates`

## Remote smoke test with `fedctl`

Run this from the repository root:

```bash
fedctl run refs/heterofl_fedctl \
  --repo-config experiments/dissertation/repo_config/heterofl_smoke.yaml \
  --exp heterofl-smoke-4nodes \
  --supernodes rpi4=2 \
  --supernodes rpi5=2 \
  --stream \
  --no-destroy
```

Use `--no-destroy` for the first smoke test so logs and state remain available.

If the run succeeds, clean up manually:

```bash
fedctl destroy heterofl-smoke-4nodes
```

## What to look for in logs

### Server-side

Look for:

- capability discovery replies for all 4 nodes
- discovered `node_id -> device_type`
- training rounds starting normally

### Client-side

Look for lines like:

```text
[heterofl] train device_type=rpi4 model_rate=0.5 instance_idx=1
[heterofl] train device_type=rpi5 model_rate=1.0 instance_idx=1
```

## Follow-up checks

If the run fails, debug in this order:

1. capability discovery did not return 4 replies
2. `FEDCTL_DEVICE_TYPE` was not present in client env
3. device rates were not resolved correctly
4. parameter slicing/merge logic produced a tensor mismatch
