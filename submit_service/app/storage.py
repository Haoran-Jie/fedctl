from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
from typing import Any

from .config import ensure_sqlite_path


@dataclass(frozen=True)
class StorageConfig:
    db_url: str


class Storage:
    def __init__(self, config: StorageConfig) -> None:
        self._db_url = config.db_url
        self._db_path = ensure_sqlite_path(self._db_url)
        if self._db_path:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS submissions (
                    id TEXT PRIMARY KEY,
                    user TEXT NOT NULL,
                    project_name TEXT NOT NULL,
                    experiment TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    nomad_job_id TEXT,
                    artifact_url TEXT NOT NULL,
                    submit_image TEXT NOT NULL,
                    node_class TEXT NOT NULL,
                    args_json TEXT,
                    env_json TEXT,
                    priority INTEGER,
                    logs_location TEXT,
                    result_location TEXT,
                    error_message TEXT,
                    namespace TEXT,
                    jobs_json TEXT
                )
                """
            )
            try:
                conn.execute("ALTER TABLE submissions ADD COLUMN jobs_json TEXT")
            except sqlite3.OperationalError:
                pass

    def create_submission(self, payload: dict[str, Any]) -> dict[str, Any]:
        args = payload.pop("args", []) or []
        env = payload.pop("env", {}) or {}
        jobs = payload.pop("jobs", None)
        payload = {
            **payload,
            "args_json": json.dumps(args),
            "env_json": json.dumps(env),
            "jobs_json": json.dumps(jobs) if jobs is not None else None,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO submissions (
                    id, user, project_name, experiment, status, created_at,
                    started_at, finished_at, nomad_job_id, artifact_url,
                    submit_image, node_class, args_json, env_json, priority,
                    logs_location, result_location, error_message, namespace, jobs_json
                ) VALUES (
                    :id, :user, :project_name, :experiment, :status, :created_at,
                    :started_at, :finished_at, :nomad_job_id, :artifact_url,
                    :submit_image, :node_class, :args_json, :env_json, :priority,
                    :logs_location, :result_location, :error_message, :namespace, :jobs_json
                )
                """,
                payload,
            )
        return self.get_submission(payload["id"])

    def list_submissions(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM submissions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_submission(self, submission_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM submissions WHERE id = ?",
                (submission_id,),
            ).fetchone()
        if row is None:
            raise KeyError(submission_id)
        return self._row_to_record(row)

    def update_submission(self, submission_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        if not updates:
            return self.get_submission(submission_id)
        columns = []
        params: dict[str, Any] = {}
        for key, value in updates.items():
            column = key
            if key in {"args", "env", "jobs"}:
                column = f"{key}_json"
                value = json.dumps(value)
            columns.append(f"{column} = :{column}")
            params[column] = value
        params["id"] = submission_id
        sql = f"UPDATE submissions SET {', '.join(columns)} WHERE id = :id"
        with self._connect() as conn:
            conn.execute(sql, params)
        return self.get_submission(submission_id)

    def set_status(
        self,
        submission_id: str,
        status: str,
        *,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        updates: dict[str, Any] = {"status": status}
        if started_at:
            updates["started_at"] = started_at.isoformat()
        if finished_at:
            updates["finished_at"] = finished_at.isoformat()
        if error_message is not None:
            updates["error_message"] = error_message
        return self.update_submission(submission_id, updates)

    def _connect(self) -> sqlite3.Connection:
        if not self._db_path:
            raise ValueError("Only sqlite:/// DB URLs are supported in MVP")
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["args"] = _safe_json_loads(record.pop("args_json") or "[]")
        record["env"] = _safe_json_loads(record.pop("env_json") or "{}")
        record["jobs"] = _safe_json_loads(record.pop("jobs_json") or "{}")
        return record


def new_submission_id(prefix: str = "sub") -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    suffix = datetime.now(timezone.utc).strftime("%f")[-4:]
    return f"{prefix}-{now}-{suffix}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_json_loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return [] if raw.strip().startswith("[") else {}
