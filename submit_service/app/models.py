from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SubmissionCreateRequest(BaseModel):
    project_name: str
    experiment: str | None = None
    artifact_url: str
    submit_image: str
    node_class: str = "submit"
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    priority: int | None = None
    namespace: str | None = None


class SubmissionRecord(BaseModel):
    submission_id: str
    user: str
    project_name: str
    experiment: str | None
    status: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    nomad_job_id: str | None = None
    artifact_url: str
    submit_image: str
    node_class: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    priority: int | None = None
    logs_location: str | None = None
    result_location: str | None = None
    error_message: str | None = None
    namespace: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "SubmissionRecord":
        return cls(
            submission_id=row["id"],
            user=row["user"],
            project_name=row["project_name"],
            experiment=row.get("experiment"),
            status=row["status"],
            created_at=_parse_dt(row["created_at"]),
            started_at=_parse_dt(row.get("started_at")),
            finished_at=_parse_dt(row.get("finished_at")),
            nomad_job_id=row.get("nomad_job_id"),
            artifact_url=row["artifact_url"],
            submit_image=row["submit_image"],
            node_class=row["node_class"],
            args=row.get("args", []),
            env=row.get("env", {}),
            priority=row.get("priority"),
            logs_location=row.get("logs_location"),
            result_location=row.get("result_location"),
            error_message=row.get("error_message"),
            namespace=row.get("namespace"),
        )


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
