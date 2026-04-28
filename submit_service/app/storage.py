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
                    submit_request_json TEXT,
                    priority INTEGER,
                    logs_location TEXT,
                    logs_archive_json TEXT,
                    result_location TEXT,
                    result_artifacts_json TEXT,
                    error_message TEXT,
                    blocked_reason TEXT,
                    namespace TEXT,
                    jobs_json TEXT
                )
                """
            )
            try:
                conn.execute("ALTER TABLE submissions ADD COLUMN jobs_json TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE submissions ADD COLUMN blocked_reason TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE submissions ADD COLUMN result_artifacts_json TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE submissions ADD COLUMN logs_archive_json TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE submissions ADD COLUMN submit_request_json TEXT")
            except sqlite3.OperationalError:
                pass

    def create_submission(self, payload: dict[str, Any]) -> dict[str, Any]:
        args = payload.pop("args", []) or []
        env = payload.pop("env", {}) or {}
        submit_request = payload.pop("submit_request", {}) or {}
        jobs = payload.pop("jobs", None)
        if "blocked_reason" not in payload:
            payload["blocked_reason"] = None
        if "result_artifacts" not in payload:
            payload["result_artifacts"] = []
        if "logs_archive" not in payload:
            payload["logs_archive"] = {}
        payload = {
            **payload,
            "args_json": json.dumps(args),
            "env_json": json.dumps(env),
            "submit_request_json": json.dumps(submit_request),
            "jobs_json": json.dumps(jobs) if jobs is not None else None,
            "logs_archive_json": json.dumps(payload.pop("logs_archive")),
            "result_artifacts_json": json.dumps(payload.pop("result_artifacts")),
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO submissions (
                    id, user, project_name, experiment, status, created_at,
                    started_at, finished_at, nomad_job_id, artifact_url,
                    submit_image, node_class, args_json, env_json, submit_request_json, priority,
                    logs_location, logs_archive_json, result_location, result_artifacts_json, error_message, blocked_reason, namespace, jobs_json
                ) VALUES (
                    :id, :user, :project_name, :experiment, :status, :created_at,
                    :started_at, :finished_at, :nomad_job_id, :artifact_url,
                    :submit_image, :node_class, :args_json, :env_json, :submit_request_json, :priority,
                    :logs_location, :logs_archive_json, :result_location, :result_artifacts_json, :error_message, :blocked_reason, :namespace, :jobs_json
                )
                """,
                payload,
            )
        return self.get_submission(payload["id"])

    def list_submissions(
        self,
        limit: int = 20,
        *,
        offset: int = 0,
        statuses: list[str] | None = None,
        user: str | None = None,
        query: str | None = None,
        order: str = "created_desc",
        default_priority: int = 50,
    ) -> list[dict[str, Any]]:
        where, params = _submission_where(statuses=statuses, user=user, query=query)
        order_sql = _submission_order(order, default_priority=default_priority)
        limit = max(1, int(limit))
        offset = max(0, int(offset))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM submissions{where} {order_sql} LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def count_submissions(
        self,
        *,
        statuses: list[str] | None = None,
        user: str | None = None,
        query: str | None = None,
    ) -> int:
        where, params = _submission_where(statuses=statuses, user=user, query=query)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS count FROM submissions{where}",
                params,
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def list_dispatch_candidates(
        self,
        *,
        limit: int = 50,
        statuses: list[str] | None = None,
        default_priority: int = 50,
    ) -> list[dict[str, Any]]:
        candidate_statuses = statuses or ["queued", "blocked"]
        placeholders = ", ".join("?" for _ in candidate_statuses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM submissions WHERE status IN ({placeholders}) "
                "ORDER BY COALESCE(priority, ?) DESC, created_at ASC, id ASC LIMIT ?",
                (*candidate_statuses, default_priority, limit),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def clear_submissions(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM submissions")

    def delete_submission(self, submission_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM submissions WHERE id = ?",
                (submission_id,),
            )
        return cursor.rowcount > 0

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
            if key in {"args", "env", "submit_request", "jobs", "result_artifacts", "logs_archive"}:
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
        blocked_reason: str | None = None,
    ) -> dict[str, Any]:
        updates: dict[str, Any] = {"status": status}
        if started_at:
            updates["started_at"] = started_at.isoformat()
        if finished_at:
            updates["finished_at"] = finished_at.isoformat()
        if error_message is not None:
            updates["error_message"] = error_message
        if blocked_reason is not None:
            updates["blocked_reason"] = blocked_reason
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
        record["submit_request"] = _safe_json_loads(record.pop("submit_request_json") or "{}")
        record["jobs"] = _safe_json_loads(record.pop("jobs_json") or "{}")
        record["logs_archive"] = _safe_json_loads(record.pop("logs_archive_json") or "{}")
        record["result_artifacts"] = _safe_json_loads(
            record.pop("result_artifacts_json") or "[]"
        )
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


def _submission_where(
    *,
    statuses: list[str] | None,
    user: str | None,
    query: str | None,
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    if statuses:
        placeholders = ", ".join("?" for _ in statuses)
        clauses.append(f"status IN ({placeholders})")
        params.extend(statuses)
    if user:
        clauses.append("user = ?")
        params.append(user)
    search_query = (query or "").strip().casefold()
    if search_query:
        pattern = f"%{search_query}%"
        searchable = ["id", "project_name", "experiment", "user", "namespace"]
        clauses.append(
            "("
            + " OR ".join(f"LOWER(COALESCE({field}, '')) LIKE ?" for field in searchable)
            + ")"
        )
        params.extend([pattern] * len(searchable))
    where = ""
    if clauses:
        where = " WHERE " + " AND ".join(clauses)
    return where, tuple(params)


def _submission_order(order: str, *, default_priority: int = 50) -> str:
    if order == "ui":
        safe_default_priority = int(default_priority)
        return (
            "ORDER BY "
            "CASE "
            "WHEN status = 'running' THEN 0 "
            "WHEN status IN ('queued', 'blocked') THEN 1 "
            "ELSE 2 END ASC, "
            f"CASE WHEN status IN ('queued', 'blocked') THEN COALESCE(priority, {safe_default_priority}) END DESC, "
            "CASE WHEN status IN ('queued', 'blocked') THEN created_at END ASC, "
            "CASE WHEN status IN ('queued', 'blocked') THEN id END ASC, "
            "CASE WHEN status NOT IN ('queued', 'blocked') THEN created_at END DESC, "
            "id DESC"
        )
    return "ORDER BY created_at DESC, id DESC"
