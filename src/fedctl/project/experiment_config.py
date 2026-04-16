from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
import tomllib
from tomllib import TOMLDecodeError

import tomlkit

from fedctl.project.errors import ProjectError

_ARCHIVED_EXPERIMENT_CONFIG = Path(".fedctl") / "experiment_config.toml"

_SECTION_KEY_MAP: dict[str, dict[str, str]] = {
    "experiment": {
        "method": "method",
        "task": "task",
        "seed": "seed",
    },
    "server": {
        "num-server-rounds": "num-server-rounds",
        "fraction-train": "fraction-train",
        "fraction-evaluate": "fraction-evaluate",
        "min-available-nodes": "min-available-nodes",
        "min-train-nodes": "min-train-nodes",
        "min-evaluate-nodes": "min-evaluate-nodes",
        "capability-discovery-timeout-s": "capability-discovery-timeout-s",
    },
    "client": {
        "local-epochs": "local-epochs",
        "learning-rate": "learning-rate",
        "optimizer": "optimizer",
        "batch-size": "batch-size",
    },
    "data": {
        "partitioning": "partitioning",
        "partitioning-num-labels": "partitioning-num-labels",
        "partitioning-dirichlet-alpha": "partitioning-dirichlet-alpha",
        "partitioning-continuous-column": "partitioning-continuous-column",
        "partitioning-continuous-strictness": "partitioning-continuous-strictness",
        "masked-cross-entropy": "masked-cross-entropy",
    },
    "model": {
        "global-model-rate": "global-model-rate",
        "default-model-rate": "default-model-rate",
    },
    "capacity": {
        "model-split-mode": "model-split-mode",
        "model-rate-levels": "model-rate-levels",
        "model-rate-proportions": "model-rate-proportions",
        "heterofl-node-device-types": "heterofl-node-device-types",
        "heterofl-node-rates": "heterofl-node-rates",
        "heterofl-partition-rates": "heterofl-partition-rates",
        "heterofl-device-type-allocations": "heterofl-device-type-allocations",
    },
    "fedrolex": {
        "roll-mode": "fedrolex-roll-mode",
        "overlap": "fedrolex-overlap",
        "fedrolex-roll-mode": "fedrolex-roll-mode",
        "fedrolex-overlap": "fedrolex-overlap",
    },
    "fedavgm": {
        "server-momentum": "fedavgm-server-momentum",
        "fedavgm-server-momentum": "fedavgm-server-momentum",
    },
    "fedbuff": {
        "buffer-size": "fedbuff-buffer-size",
        "train-concurrency": "fedbuff-train-concurrency",
        "poll-interval-s": "fedbuff-poll-interval-s",
        "num-server-steps": "fedbuff-num-server-steps",
        "evaluate-every-steps": "fedbuff-evaluate-every-steps",
        "staleness-weighting": "fedbuff-staleness-weighting",
        "staleness-alpha": "fedbuff-staleness-alpha",
        "fedbuff-buffer-size": "fedbuff-buffer-size",
        "fedbuff-train-concurrency": "fedbuff-train-concurrency",
        "fedbuff-poll-interval-s": "fedbuff-poll-interval-s",
        "fedbuff-num-server-steps": "fedbuff-num-server-steps",
        "fedbuff-evaluate-every-steps": "fedbuff-evaluate-every-steps",
        "fedbuff-staleness-weighting": "fedbuff-staleness-weighting",
        "fedbuff-staleness-alpha": "fedbuff-staleness-alpha",
    },
    "fiarse": {
        "threshold-mode": "fiarse-threshold-mode",
        "global-learning-rate": "fiarse-global-learning-rate",
        "fiarse-threshold-mode": "fiarse-threshold-mode",
        "fiarse-global-learning-rate": "fiarse-global-learning-rate",
    },
    "evaluation": {
        "client-eval-enabled": "client-eval-enabled",
        "final-client-eval-enabled": "final-client-eval-enabled",
        "target-score": "target-score",
        "stop-on-target-score": "stop-on-target-score",
    },
    "wandb": {
        "enabled": "wandb-enabled",
        "project": "wandb-project",
        "entity": "wandb-entity",
        "group": "wandb-group",
        "mode": "wandb-mode",
        "tags": "wandb-tags",
        "wandb-enabled": "wandb-enabled",
        "wandb-project": "wandb-project",
        "wandb-entity": "wandb-entity",
        "wandb-group": "wandb-group",
        "wandb-mode": "wandb-mode",
        "wandb-tags": "wandb-tags",
    },
}

_DEVICE_VALUE_MAP = {
    "model-rate": "model-rate",
    "batch-size": "batch-size",
    "max-train-examples": "max-train-examples",
    "max-test-examples": "max-test-examples",
}


@dataclass(frozen=True)
class ExperimentConfigResolution:
    resolved_path: Path
    runner_path: str
    archive_source: Path | None


def resolve_experiment_config_input(
    project_root: Path,
    experiment_config: str | None,
) -> Path | None:
    if not experiment_config:
        return None

    raw = Path(experiment_config).expanduser()
    candidates = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append((project_root / raw).resolve())
        candidates.append(raw.resolve())

    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise ProjectError(f"Experiment config not found: {experiment_config}")


def resolve_experiment_config(
    project_root: Path,
    experiment_config: str | None,
) -> ExperimentConfigResolution | None:
    resolved = resolve_experiment_config_input(project_root, experiment_config)
    if resolved is None:
        return None

    normalized_path = _normalize_experiment_config(resolved)
    normalized_source = normalized_path or resolved
    project_root_resolved = project_root.resolve()
    try:
        rel = resolved.relative_to(project_root_resolved)
        return ExperimentConfigResolution(
            resolved_path=normalized_source,
            runner_path=str(rel),
            archive_source=normalized_source if normalized_path is not None else None,
        )
    except ValueError:
        return ExperimentConfigResolution(
            resolved_path=normalized_source,
            runner_path=str(_ARCHIVED_EXPERIMENT_CONFIG),
            archive_source=normalized_source,
        )


def extract_seed_sweep(
    project_root: Path,
    experiment_config: str | None,
) -> tuple[int, ...]:
    resolved = resolve_experiment_config_input(project_root, experiment_config)
    if resolved is None:
        return ()

    data = tomllib.loads(resolved.read_text(encoding="utf-8"))
    if "experiment" in data and isinstance(data["experiment"], dict):
        raw = data["experiment"].get("seeds")
    else:
        raw = data.get("seeds")
    if raw is None:
        return ()
    if not isinstance(raw, list) or not raw:
        raise ProjectError("Experiment seed sweep must be a non-empty array")
    return tuple(int(value) for value in raw)


def materialize_run_config(
    *,
    base_path: Path | None,
    run_config_overrides: list[str] | None,
) -> Path | None:
    overrides = list(run_config_overrides or [])
    if base_path is None:
        return None
    if not overrides:
        return base_path

    data = tomllib.loads(base_path.read_text(encoding="utf-8"))
    for override in overrides:
        key, value = _parse_run_config_override(override)
        data[key] = value
    return _write_temp_toml(data, prefix="fedctl-run-config-")


def _normalize_experiment_config(path: Path) -> Path | None:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    normalized, changed = _flatten_experiment_config(data)
    if not changed:
        return None
    return _write_temp_toml(normalized, prefix="fedctl-experiment-config-")


def _flatten_experiment_config(data: dict[str, object]) -> tuple[dict[str, object], bool]:
    normalized: dict[str, object] = {}
    changed = False

    for key, value in data.items():
        if isinstance(value, dict):
            changed = True
            _flatten_section(normalized, key, value)
            continue
        normalized[key] = _normalize_scalar_value(value)

    return normalized, changed


def _flatten_section(normalized: dict[str, object], section: str, value: dict[str, object]) -> None:
    if section in _SECTION_KEY_MAP:
        mapping = _SECTION_KEY_MAP[section]
        for key, item in value.items():
            if section == "experiment" and key == "seeds":
                continue
            flat_key = mapping.get(key)
            if flat_key is None:
                raise ProjectError(
                    f"Unsupported key in experiment config section [{section}]: {key}"
                )
            normalized[flat_key] = _normalize_scalar_value(item)
        return

    if section == "devices":
        for device_name, device_values in value.items():
            if not isinstance(device_values, dict):
                raise ProjectError("Expected [devices.<device>] tables in experiment config")
            for key, item in device_values.items():
                suffix = _DEVICE_VALUE_MAP.get(key)
                if suffix is None:
                    raise ProjectError(
                        f"Unsupported key in experiment config section [devices.{device_name}]: {key}"
                    )
                normalized[f"{device_name}-{suffix}"] = _normalize_scalar_value(item)
        return

    raise ProjectError(f"Unsupported experiment config section: [{section}]")


def _normalize_scalar_value(value: object) -> object:
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if isinstance(value, dict):
        raise ProjectError("Nested tables deeper than one supported schema level are not allowed")
    return value


def _parse_run_config_override(override: str) -> tuple[str, object]:
    if "=" not in override:
        raise ProjectError(f"Run config override must be key=value: {override}")
    key, raw_value = override.split("=", 1)
    key = key.strip()
    if not key:
        raise ProjectError(f"Run config override must use a non-empty key: {override}")
    raw_value = raw_value.strip()
    return key, _parse_override_value(raw_value)


def _parse_override_value(raw_value: str) -> object:
    try:
        return tomllib.loads(f"value = {raw_value}")["value"]
    except TOMLDecodeError:
        return raw_value


def _write_temp_toml(data: dict[str, object], *, prefix: str) -> Path:
    fd, raw_path = tempfile.mkstemp(prefix=prefix, suffix=".toml")
    tmp_path = Path(raw_path)
    doc = tomlkit.document()
    for key, value in data.items():
        doc[key] = value
    tmp_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    os.close(fd)
    return tmp_path
