# Concrete `fedctl` Command Templates

These commands are the execution-side counterpart of the dissertation matrices.

Assumptions:

- Run from the repository root.
- Replace `<project-path>` with the Flower project under evaluation.
- Replace any experiment-specific application config inside the project itself.
- The repo-config files in `experiments/dissertation/repo_config/` are passed explicitly with `--repo-config`.

## 1. Core HeteroFL runs

### 1.1 IID baseline, homogeneous full model

```bash
fedctl submit run <project-path> \
  --repo-config experiments/dissertation/repo_config/heterofl_core.yaml \
  --exp heterofl-fmnist-iid-s1 \
  --supernodes rpi4=6 \
  --supernodes rpi5=22 \
  --stream \
  --destroy
```

### 1.2 IID baseline, homogeneous reduced model

```bash
fedctl submit run <project-path> \
  --repo-config experiments/dissertation/repo_config/heterofl_core.yaml \
  --exp heterofl-fmnist-iid-small-s1 \
  --supernodes rpi4=6 \
  --supernodes rpi5=22 \
  --stream \
  --destroy
```

### 1.3 IID HeteroFL

```bash
fedctl submit run <project-path> \
  --repo-config experiments/dissertation/repo_config/heterofl_core.yaml \
  --exp heterofl-fmnist-iid-hetero-s1 \
  --supernodes rpi4=6 \
  --supernodes rpi5=22 \
  --stream \
  --destroy
```

### 1.4 Dirichlet HeteroFL

```bash
fedctl submit run <project-path> \
  --repo-config experiments/dissertation/repo_config/heterofl_core.yaml \
  --exp heterofl-cifar-dir-hetero-s1 \
  --supernodes rpi4=6 \
  --supernodes rpi5=22 \
  --stream \
  --destroy
```

## 2. Network impairment runs

### 2.1 Moderate impairment for all supernodes

```bash
fedctl submit run <project-path> \
  --repo-config experiments/dissertation/repo_config/heterofl_network.yaml \
  --exp net-fmnist-med-hetero-s1 \
  --supernodes rpi4=6 \
  --supernodes rpi5=22 \
  --net 'rpi4[*]=med,rpi5[*]=med' \
  --stream \
  --destroy
```

### 2.2 Asymmetric impairment with slower uplink on `rpi4`

```bash
fedctl submit run <project-path> \
  --repo-config experiments/dissertation/repo_config/heterofl_network.yaml \
  --exp net-fmnist-asym-hetero-s1 \
  --supernodes rpi4=6 \
  --supernodes rpi5=22 \
  --net 'rpi4[*]=(asym_up,asym_down),rpi5[*]=(med,mild)' \
  --stream \
  --destroy
```

## 3. Buffered async / FedBuff-style extension

### 3.1 No impairment

```bash
fedctl submit run <project-path> \
  --repo-config experiments/dissertation/repo_config/fedbuff_extension.yaml \
  --exp fedbuff-fmnist-none-buffered-s1 \
  --supernodes rpi4=6 \
  --supernodes rpi5=22 \
  --stream \
  --destroy
```

### 3.2 Asymmetric impairment

```bash
fedctl submit run <project-path> \
  --repo-config experiments/dissertation/repo_config/fedbuff_extension.yaml \
  --exp fedbuff-fmnist-asym-buffered-s1 \
  --supernodes rpi4=6 \
  --supernodes rpi5=22 \
  --net 'rpi4[*]=(asym_up,asym_down),rpi5[*]=(med,mild)' \
  --stream \
  --destroy
```

## 4. Results retrieval

### 4.1 Submission status

```bash
fedctl submit status <submission-id>
```

### 4.2 Fetch second supernode log

```bash
fedctl submit logs <submission-id> --job supernodes --index 2
```

### 4.3 Fetch stderr for the first supernode

```bash
fedctl submit logs <submission-id> --job supernodes --index 1 --stderr
```

## 5. Notes

- Use one experiment id per matrix row.
- Keep seed encoded in `--exp` for traceability.
- Store parsed results under a separate results directory after each run.
- If the project embeds its own `.fedctl/fedctl.yaml`, ensure it matches the repo-config used here or pass `--repo-config` explicitly.
