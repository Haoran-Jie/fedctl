# fedctl Experiment Run Configs

This directory turns the dissertation experiment plan into concrete `fedctl` artifacts.

## Structure

- `repo_config/`: YAML repo-config fragments to pass via `--repo-config`
- `matrices/`: CSV matrices describing the intended run set
- `commands.md`: concrete command templates for the main experiment families

## Usage model

Each repo-config file can be used in one of two ways:

1. Pass it explicitly:

```bash
fedctl submit run <project-path> --repo-config experiments/dissertation/repo_config/heterofl_core.yaml ...
```

2. Copy its contents into the experiment project's `.fedctl/fedctl.yaml`

The files here are intended to be the dissertation reference versions, not necessarily the final runtime copies.
