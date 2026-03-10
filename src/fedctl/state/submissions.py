from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fedctl.config.paths import user_config_dir
from .errors import StateError


@dataclass(frozen=True)
class SubmissionRecord:
    submission_id: str
    experiment: str
    created_at: str
    status: str = "queued"
    namespace: str | None = None
    artifact_url: str | None = None
    submit_image: str | None = None
    node_class: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "submission_id": self.submission_id,
            "experiment": self.experiment,
            "created_at": self.created_at,
            "status": self.status,
            "namespace": self.namespace,
            "artifact_url": self.artifact_url,
            "submit_image": self.submit_image,
            "node_class": self.node_class,
        }


def submissions_path() -> Path:
    return user_config_dir() / "state" / "submissions.json"


def load_submissions() -> list[dict[str, Any]]:
    path = submissions_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StateError(f"Submissions state at {path} is invalid JSON.") from exc
    if not isinstance(data, list):
        return []
    return [_normalize_entry(entry) for entry in data if isinstance(entry, dict)]


def _normalize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(entry)
    status = normalized.get("status")
    if not isinstance(status, str) or not status:
        normalized["status"] = "queued"
    return normalized


def record_submission(record: SubmissionRecord, *, max_entries: int = 200) -> Path:
    path = submissions_path()
    entries = load_submissions()
    entries.insert(0, record.to_dict())
    if max_entries > 0:
        entries = entries[:max_entries]
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(entries, indent=2, sort_keys=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, path)
    return path


def clear_submissions() -> Path:
    path = submissions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([], indent=2, sort_keys=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, path)
    return path


def clear_submission(submission_id: str) -> Path:
    path = submissions_path()
    entries = [
        entry
        for entry in load_submissions()
        if entry.get("submission_id") != submission_id
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(entries, indent=2, sort_keys=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, path)
    return path
