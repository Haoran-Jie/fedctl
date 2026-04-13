"""Structured result artifact helpers for dissertation experiment runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping


def _sanitize_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)


class ResultArtifactLogger:
    def __init__(self, *, experiment: str, method: str, task: str) -> None:
        base = Path(os.environ.get("FEDCTL_RESULT_DIR", "outputs/fedctl_results"))
        base_dir = base / _sanitize_name(experiment) / _sanitize_name(method) / _sanitize_name(task)
        base_dir.mkdir(parents=True, exist_ok=True)
        self.base_dir = base_dir
        self._paths = {
            "client_update": base_dir / "client_update_events.jsonl",
            "server_step": base_dir / "server_step_events.jsonl",
            "evaluation": base_dir / "evaluation_events.jsonl",
            "submodel_evaluation": base_dir / "submodel_evaluation_events.jsonl",
        }

    def _append(self, event_kind: str, payload: Mapping[str, Any]) -> None:
        path = self._paths[event_kind]
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(payload), sort_keys=True))
            handle.write("\n")

    def log_client_update_event(self, payload: Mapping[str, Any]) -> None:
        self._append("client_update", payload)

    def log_server_step_event(self, payload: Mapping[str, Any]) -> None:
        self._append("server_step", payload)

    def log_evaluation_event(self, payload: Mapping[str, Any]) -> None:
        self._append("evaluation", payload)

    def log_submodel_evaluation_event(self, payload: Mapping[str, Any]) -> None:
        self._append("submodel_evaluation", payload)
