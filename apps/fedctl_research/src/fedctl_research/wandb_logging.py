"""Optional Weights & Biases logging for server-side experiment metrics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import PurePosixPath
import re
from typing import Any

from flwr.app import Context
from flwr.common import MetricRecord
from flwr.common.logger import log
from logging import INFO, WARNING

from fedctl_research.config import (
    get_method_name,
    get_model_rate_levels,
    get_model_rate_proportions,
    get_optional_bool,
    get_optional_str,
    get_task_name,
)
from fedctl_research.metrics import normalize_metric_mapping


def _metric_record_to_dict(metrics: MetricRecord | Mapping[str, Any] | None) -> dict[str, int | float]:
    if metrics is None:
        return {}
    items = dict(metrics).items() if isinstance(metrics, Mapping) else []
    resolved: dict[str, int | float] = {}
    for key, value in items:
        if isinstance(value, bool):
            resolved[str(key)] = int(value)
        elif isinstance(value, int):
            resolved[str(key)] = value
        elif isinstance(value, float):
            resolved[str(key)] = value
    return normalize_metric_mapping(resolved)


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _sanitize_config(run_config: Mapping[str, object]) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    for key, value in run_config.items():
        if isinstance(value, (str, int, float, bool)):
            sanitized[str(key)] = value
        elif value is None:
            sanitized[str(key)] = None
        else:
            sanitized[str(key)] = str(value)
    return sanitized


_ROUND_SYSTEM_KEYS = {
    "round-sampled-nodes": "round_system/sampled_nodes",
    "round-successful-train-replies": "round_system/successful_train_replies",
    "round-failed-train-replies": "round_system/failed_train_replies",
    "round-successful-eval-replies": "round_system/successful_eval_replies",
    "round-failed-eval-replies": "round_system/failed_eval_replies",
    "round-train-duration-s": "round_system/train_duration_s",
    "round-client-eval-duration-s": "round_system/client_eval_duration_s",
    "round-server-eval-duration-s": "round_system/server_eval_duration_s",
}

_ROUND_CLIENT_STATS_KEYS = {
    "round-train-client-duration-mean-s": "round_client_stats/train_duration_mean_s",
    "round-train-client-duration-min-s": "round_client_stats/train_duration_min_s",
    "round-train-client-duration-max-s": "round_client_stats/train_duration_max_s",
    "round-train-client-duration-std-s": "round_client_stats/train_duration_std_s",
    "round-train-straggler-gap-s": "round_client_stats/train_straggler_gap_s",
    "round-eval-client-duration-mean-s": "round_client_stats/eval_duration_mean_s",
    "round-eval-client-duration-min-s": "round_client_stats/eval_duration_min_s",
    "round-eval-client-duration-max-s": "round_client_stats/eval_duration_max_s",
    "round-eval-client-duration-std-s": "round_client_stats/eval_duration_std_s",
}

_ROUND_COST_KEYS = {
    "round_avg_params": "round_cost/avg_params",
    "round_avg_size_mb": "round_cost/avg_size_mb",
    "round_avg_flops": "round_cost/avg_flops",
    "round_total_client_flops": "round_cost/total_client_flops",
    "round_avg_model_rate": "round_cost/avg_model_rate",
}


def _system_metric_alias_payload(metrics: Mapping[str, int | float]) -> dict[str, int | float]:
    payload: dict[str, int | float] = {}
    for key, value in metrics.items():
        alias = _ROUND_SYSTEM_KEYS.get(key)
        if alias is None:
            alias = _ROUND_CLIENT_STATS_KEYS.get(key)
        if alias is None:
            alias = _ROUND_COST_KEYS.get(key)
        if alias is not None:
            payload[alias] = value
            continue

        device_type, _, suffix = key.partition("_")
        if _ and device_type:
            payload[f"round_device/{device_type}/{suffix}"] = value
    return payload


class ExperimentLogger:
    """No-op base logger."""

    def log_train_metrics(self, server_round: int, metrics: MetricRecord | Mapping[str, Any] | None) -> None:
        del server_round, metrics

    def log_client_eval_metrics(
        self, server_round: int, metrics: MetricRecord | Mapping[str, Any] | None
    ) -> None:
        del server_round, metrics

    def log_server_eval_metrics(
        self, server_round: int, metrics: MetricRecord | Mapping[str, Any] | None
    ) -> None:
        del server_round, metrics

    def log_system_metrics(self, server_round: int, metrics: MetricRecord | Mapping[str, Any] | None) -> None:
        del server_round, metrics

    def log_progress_metrics(self, step: int, metrics: MetricRecord | Mapping[str, Any] | None) -> None:
        del step, metrics

    def log_async_metrics(
        self,
        method_label: str,
        server_step: int,
        metrics: MetricRecord | Mapping[str, Any] | None,
    ) -> None:
        del method_label, server_step, metrics

    def log_fedbuff_metrics(self, server_step: int, metrics: MetricRecord | Mapping[str, Any] | None) -> None:
        self.log_async_metrics("fedbuff", server_step, metrics)

    def log_model_catalog(self, catalog: Mapping[str, Mapping[str, Any]]) -> None:
        del catalog

    def log_summary_metrics(self, metrics: Mapping[str, Any] | None) -> None:
        del metrics

    def log_submodel_client_events(
        self,
        server_step: int,
        rows: list[Mapping[str, Any]],
    ) -> None:
        del server_step, rows

    def log_run_summary(
        self,
        *,
        total_runtime_s: float,
        result: Any,
    ) -> None:
        del total_runtime_s, result

    def finish(self) -> None:
        return None


@dataclass
class WandbExperimentLogger(ExperimentLogger):
    run: Any
    wandb_module: Any | None = None
    submission_id: str = ""
    canonical_key: str = ""
    attempt_id: str = ""
    attempt_started_at: str = ""
    disabled: bool = False

    def _disable(self, phase: str, exc: Exception) -> None:
        if not self.disabled:
            log(WARNING, "wandb logging failed during %s; disabling W&B logging: %s", phase, exc)
        self.disabled = True

    def _set_summary_value(self, key: str, value: object) -> None:
        if self.disabled:
            return
        try:
            self.run.summary[key] = value
        except Exception as exc:  # pragma: no cover - defensive guard for live W&B runtime
            self._disable(f"summary update for {key}", exc)

    def _set_attempt_status(self, status: str) -> None:
        self._set_summary_value("fedctl_attempt_status", status)

    def write_attempt_metadata(self, *, status: str) -> None:
        self._set_attempt_status(status)
        if self.submission_id:
            self._set_summary_value("fedctl_submission_id", self.submission_id)
        if self.canonical_key:
            self._set_summary_value("fedctl_canonical_key", self.canonical_key)
        if self.attempt_id:
            self._set_summary_value("fedctl_attempt_id", self.attempt_id)
        if self.attempt_started_at:
            self._set_summary_value("fedctl_attempt_started_at", self.attempt_started_at)

    def _log(
        self,
        prefix: str,
        axis_value: int,
        metrics: MetricRecord | Mapping[str, Any] | None,
        *,
        axis_key: str = "server_round",
    ) -> None:
        if self.disabled:
            return
        payload = {
            f"{prefix}/{key}": value for key, value in _metric_record_to_dict(metrics).items()
        }
        if not payload:
            return
        payload[axis_key] = axis_value
        try:
            self.run.log(payload, step=axis_value)
        except Exception as exc:  # pragma: no cover - defensive guard for live W&B runtime
            self._disable(f"log payload {prefix}", exc)

    def log_train_metrics(self, server_round: int, metrics: MetricRecord | Mapping[str, Any] | None) -> None:
        self._log("train", server_round, metrics)

    def log_client_eval_metrics(
        self, server_round: int, metrics: MetricRecord | Mapping[str, Any] | None
    ) -> None:
        self._log("eval_client", server_round, metrics)

    def log_server_eval_metrics(
        self, server_round: int, metrics: MetricRecord | Mapping[str, Any] | None
    ) -> None:
        self._log("eval_server", server_round, metrics)

    def log_system_metrics(self, server_round: int, metrics: MetricRecord | Mapping[str, Any] | None) -> None:
        if self.disabled:
            return
        resolved = _metric_record_to_dict(metrics)
        payload = {f"system/{key}": value for key, value in resolved.items()}
        payload.update(_system_metric_alias_payload(resolved))
        if not payload:
            return
        payload["server_round"] = server_round
        try:
            self.run.log(payload, step=server_round)
        except Exception as exc:  # pragma: no cover - defensive guard for live W&B runtime
            self._disable("log payload system", exc)

    def log_progress_metrics(self, step: int, metrics: MetricRecord | Mapping[str, Any] | None) -> None:
        self._log("progress", step, metrics, axis_key="client_trip")

    def log_async_metrics(
        self,
        method_label: str,
        server_step: int,
        metrics: MetricRecord | Mapping[str, Any] | None,
    ) -> None:
        self._log(method_label, server_step, metrics, axis_key="server_step")

    def log_fedbuff_metrics(self, server_step: int, metrics: MetricRecord | Mapping[str, Any] | None) -> None:
        self.log_async_metrics("fedbuff", server_step, metrics)

    def log_model_catalog(self, catalog: Mapping[str, Mapping[str, Any]]) -> None:
        for name, metrics in catalog.items():
            for key, value in _metric_record_to_dict(metrics).items():
                self._set_summary_value(f"model/{name}/{key}", value)

    def log_summary_metrics(self, metrics: Mapping[str, Any] | None) -> None:
        for key, value in _metric_record_to_dict(metrics).items():
            self._set_summary_value(key, value)

    def log_submodel_client_events(
        self,
        server_step: int,
        rows: list[Mapping[str, Any]],
    ) -> None:
        if self.disabled or not rows or self.wandb_module is None:
            return
        try:
            columns = sorted({str(key) for row in rows for key in row.keys()})
            data = [[row.get(column) for column in columns] for row in rows]
            table = self.wandb_module.Table(columns=columns, data=data)
            self.run.log(
                {
                    "submodel/local_client_table": table,
                    "server_step": int(server_step),
                },
                step=int(server_step),
            )
        except Exception as exc:  # pragma: no cover - defensive guard for live W&B runtime
            self._disable("log submodel client table", exc)

    def log_run_summary(
        self,
        *,
        total_runtime_s: float,
        result: Any,
    ) -> None:
        self._set_summary_value("runtime/total_server_s", total_runtime_s)
        self._set_summary_value("run_system/total_server_s", total_runtime_s)
        train_metrics_clientapp = getattr(result, "train_metrics_clientapp", {})
        if isinstance(train_metrics_clientapp, Mapping) and train_metrics_clientapp:
            last_round = max(int(round_id) for round_id in train_metrics_clientapp)
            last_metrics = train_metrics_clientapp[last_round]
            for key, value in _metric_record_to_dict(last_metrics).items():
                self._set_summary_value(f"final/train/{key}", value)
        evaluate_metrics_clientapp = getattr(result, "evaluate_metrics_clientapp", {})
        if isinstance(evaluate_metrics_clientapp, Mapping) and evaluate_metrics_clientapp:
            last_round = max(int(round_id) for round_id in evaluate_metrics_clientapp)
            last_metrics = evaluate_metrics_clientapp[last_round]
            for key, value in _metric_record_to_dict(last_metrics).items():
                self._set_summary_value(f"final/eval_client/{key}", value)
        evaluate_metrics_serverapp = getattr(result, "evaluate_metrics_serverapp", {})
        if isinstance(evaluate_metrics_serverapp, Mapping) and evaluate_metrics_serverapp:
            last_round = max(int(round_id) for round_id in evaluate_metrics_serverapp)
            last_metrics = evaluate_metrics_serverapp[last_round]
            for key, value in _metric_record_to_dict(last_metrics).items():
                self._set_summary_value(f"final/eval_server/{key}", value)

    def finish(self) -> None:
        if self.disabled:
            return
        try:
            self.write_attempt_metadata(status="completed")
            self.run.finish()
        except Exception as exc:  # pragma: no cover - defensive guard for live W&B runtime
            self._disable("finish", exc)


@dataclass(frozen=True)
class _RunIdentity:
    canonical_key: str
    submission_id: str
    attempt_id: str
    attempt_started_at: str


def _submission_id() -> str:
    return os.environ.get("FEDCTL_SUBMISSION_ID", "").strip()


def _attempt_started_at() -> str:
    return os.environ.get("FEDCTL_ATTEMPT_STARTED_AT", "").strip()


def _repo_config_label() -> str:
    value = os.environ.get("FEDCTL_REPO_CONFIG_LABEL", "").strip()
    return value or "default"


def _seed_label(run_config: Mapping[str, object]) -> str:
    seed = run_config.get("seed")
    if isinstance(seed, int):
        return str(seed)
    if isinstance(seed, str) and seed.isdigit():
        return seed
    experiment = os.environ.get("FEDCTL_EXPERIMENT", "")
    match = re.search(r"(?:^|-)seed(\d+)(?:-|$)", experiment)
    return match.group(1) if match else "unknown"


def _study_key(experiment_config: str | None) -> str:
    if not experiment_config:
        return "study"
    parts = PurePosixPath(experiment_config).parts
    if "compute_heterogeneity" in parts:
        return f"compute-{_study_phase(parts, 'compute_heterogeneity')}"
    if "network_heterogeneity" in parts:
        return f"network-{_study_phase(parts, 'network_heterogeneity')}"
    return "study"


def _study_phase(parts: tuple[str, ...], study_dir: str) -> str:
    if "smoke" in parts:
        return "smoke"
    idx = parts.index(study_dir)
    candidate = parts[idx + 1] if idx + 1 < len(parts) else "study"
    return str(candidate).replace("_", "-")


def _attempt_id(submission_id: str) -> str:
    if not submission_id:
        return "direct"
    tail = submission_id.rsplit("-", 1)[-1]
    return f"sub{tail}"


def _node_count_label(run_config: Mapping[str, object]) -> str:
    for key in ("min-available-nodes", "min-train-nodes", "min-evaluate-nodes"):
        value = run_config.get(key)
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            return f"n{count}"
    return "n?"


def _rate_token(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text.replace(".", "p") if text else "0"


def _capacity_split_label(run_config: Mapping[str, object]) -> str:
    levels = get_model_rate_levels(run_config)
    proportions = get_model_rate_proportions(run_config)
    pairs = []
    for level, proportion in zip(levels, proportions, strict=False):
        pct = int(round(proportion * 100))
        pairs.append(f"{_rate_token(level)}x{pct}")
    if not pairs:
        return "split-unknown"
    return "split-" + "_".join(pairs)


def _resolve_run_identity(run_config: Mapping[str, object]) -> _RunIdentity:
    method = get_method_name(run_config)
    task = get_task_name(run_config)
    seed = _seed_label(run_config)
    submission_id = _submission_id()
    attempt_started_at = _attempt_started_at()
    node_count = _node_count_label(run_config)
    capacity_split = _capacity_split_label(run_config)
    canonical_key = (
        f"{_study_key(os.environ.get('FEDCTL_EXPERIMENT_CONFIG'))}"
        f"/{task}/{method}/{node_count}/{capacity_split}/seed{seed}/profile-{_repo_config_label()}"
    )
    return _RunIdentity(
        canonical_key=canonical_key,
        submission_id=submission_id,
        attempt_id=_attempt_id(submission_id),
        attempt_started_at=attempt_started_at,
    )


def create_experiment_logger(context: Context) -> ExperimentLogger:
    run_config = context.run_config
    enabled = get_optional_bool(run_config, "wandb-enabled")
    project = get_optional_str(run_config, "wandb-project") or os.environ.get("WANDB_PROJECT")
    entity = get_optional_str(run_config, "wandb-entity") or os.environ.get("WANDB_ENTITY")
    group = get_optional_str(run_config, "wandb-group") or os.environ.get("WANDB_GROUP")
    mode = get_optional_str(run_config, "wandb-mode") or os.environ.get("WANDB_MODE")
    tags = _parse_tags(get_optional_str(run_config, "wandb-tags") or os.environ.get("WANDB_TAGS"))

    if enabled is False:
        return ExperimentLogger()
    if not project:
        if enabled:
            log(WARNING, "wandb requested but no WANDB_PROJECT or wandb-project configured; disabling")
        return ExperimentLogger()

    try:
        import wandb  # type: ignore
    except ImportError:
        log(WARNING, "wandb dependency not installed in app image; disabling W&B logging")
        return ExperimentLogger()

    method = get_method_name(run_config)
    task = get_task_name(run_config)
    experiment = os.environ.get("FEDCTL_EXPERIMENT", "experiment")
    identity = _resolve_run_identity(run_config)
    init_kwargs = {
        "project": project,
        "entity": entity,
        "group": group,
        "mode": mode,
        "name": (
            f"{experiment}-{method}-{task}-"
            f"{_node_count_label(run_config)}-{_capacity_split_label(run_config)}-"
            f"{identity.attempt_id}"
        ),
        "tags": sorted(set(tags + [method, task, experiment])),
        "config": {
            **_sanitize_config(run_config),
            "fedctl_experiment": experiment,
            "fedctl_method": method,
            "fedctl_task": task,
            "fedctl_node_count_label": _node_count_label(run_config),
            "fedctl_capacity_split_label": _capacity_split_label(run_config),
            "fedctl_flwr_home": os.environ.get("FLWR_HOME", ""),
            "fedctl_submission_id": identity.submission_id,
            "fedctl_canonical_key": identity.canonical_key,
            "fedctl_attempt_status": "running",
            "fedctl_attempt_started_at": identity.attempt_started_at,
            "fedctl_attempt_id": identity.attempt_id,
        },
        "reinit": True,
    }
    init_kwargs = {key: value for key, value in init_kwargs.items() if value not in (None, "")}
    run = wandb.init(**init_kwargs)
    log(INFO, "wandb enabled: project=%s entity=%s mode=%s run=%s", project, entity, mode, run.name)
    logger = WandbExperimentLogger(
        run=run,
        wandb_module=wandb,
        submission_id=identity.submission_id,
        canonical_key=identity.canonical_key,
        attempt_id=identity.attempt_id,
        attempt_started_at=identity.attempt_started_at,
    )
    logger.write_attempt_metadata(status="running")
    return logger
