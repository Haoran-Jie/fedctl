from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import hashlib

from fastapi import HTTPException, Request

from .config import SubmitConfig
from .models import SubmissionRecord
from .nomad_client import NomadClient, NomadError
from .storage import Storage, utcnow


@dataclass(frozen=True)
class AuthPrincipal:
    name: str
    role: str
    token: str | None = None


@dataclass(frozen=True)
class ResolvedLogs:
    content: str
    source: str


_ACTIVE_STATUSES = {"queued", "running", "blocked"}
_CANCELLABLE_STATUSES = {"queued", "running", "blocked"}


def authenticate_request(request: Request, cfg: SubmitConfig) -> AuthPrincipal:
    auth_header = request.headers.get("Authorization", "")
    if cfg.tokens or cfg.token_identities:
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        token = auth_header.replace("Bearer ", "", 1).strip()
        principal = principal_for_token(token, cfg)
        if principal is None:
            raise HTTPException(status_code=403, detail="Invalid token")
        return principal
    if not cfg.allow_unauth:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return AuthPrincipal(name="anonymous", role="admin", token=None)



def principal_for_token(token: str, cfg: SubmitConfig) -> AuthPrincipal | None:
    token = token.strip()
    if not token:
        return None
    identity = cfg.token_identities.get(token)
    if identity is not None:
        return AuthPrincipal(name=identity.name, role=identity.role, token=token)
    if token in cfg.tokens:
        return AuthPrincipal(name=_legacy_token_name(token), role="admin", token=token)
    return None



def ensure_submission_access(record: dict[str, Any], principal: AuthPrincipal) -> None:
    if principal.role == "admin":
        return
    owner = record.get("user")
    if isinstance(owner, str) and owner == principal.name:
        return
    raise HTTPException(status_code=404, detail="Submission not found")



def get_submission_or_404(
    storage: Storage,
    submission_id: str,
    principal: AuthPrincipal,
) -> dict[str, Any]:
    try:
        record = storage.get_submission(submission_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Submission not found") from exc
    ensure_submission_access(record, principal)
    return record



def list_visible_submissions(
    storage: Storage,
    principal: AuthPrincipal,
    *,
    limit: int = 20,
    active_only: bool = False,
) -> list[SubmissionRecord]:
    statuses = ["queued", "running", "blocked"] if active_only else None
    rows = storage.list_submissions(
        limit=limit,
        statuses=statuses,
        user=None if principal.role == "admin" else principal.name,
    )
    return [SubmissionRecord.from_row(row) for row in rows]



def list_visible_submissions_for_ui(
    storage: Storage,
    principal: AuthPrincipal,
    *,
    status_filter: str = "all",
    limit: int = 200,
) -> list[dict[str, Any]]:
    rows = storage.list_submissions(
        limit=limit,
        user=None if principal.role == "admin" else principal.name,
    )
    filtered = [row for row in rows if _matches_status_filter(row, status_filter)]
    filtered.sort(key=lambda row: str(row.get("id") or ""))
    filtered.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    if status_filter == "all":
        filtered.sort(key=lambda row: 0 if str(row.get("status") or "") in _ACTIVE_STATUSES else 1)
    return filtered


def submission_stats_for_ui(rows: list[dict[str, Any]]) -> dict[str, int]:
    stats = {
        "total": 0,
        "active": 0,
        "blocked": 0,
        "failed": 0,
        "completed": 0,
    }
    for row in rows:
        status = str(row.get("status") or "")
        stats["total"] += 1
        if status in _ACTIVE_STATUSES:
            stats["active"] += 1
        if status == "blocked":
            stats["blocked"] += 1
        if status == "failed":
            stats["failed"] += 1
        if status == "completed":
            stats["completed"] += 1
    return stats



def resolve_submission_logs(
    record: dict[str, Any],
    cfg: SubmitConfig,
    *,
    job: str = "submit",
    task: str | None = None,
    index: int = 1,
    stderr: bool = True,
    follow: bool = False,
) -> str:
    return resolve_submission_logs_detail(
        record,
        cfg,
        job=job,
        task=task,
        index=index,
        stderr=stderr,
        follow=follow,
    ).content


def resolve_submission_logs_detail(
    record: dict[str, Any],
    cfg: SubmitConfig,
    *,
    job: str = "submit",
    task: str | None = None,
    index: int = 1,
    stderr: bool = True,
    follow: bool = False,
) -> ResolvedLogs:
    archived = archived_log_text(
        record=record,
        job=job,
        task=task,
        index=index,
        stderr=stderr,
    )
    resolve_error: HTTPException | None = None
    nomad_job_id: str | None = None
    resolved_task = task or "submit"
    try:
        nomad_job_id, resolved_task = resolve_nomad_job(record, job, task, index)
    except HTTPException as exc:
        resolve_error = exc

    if not nomad_job_id:
        if archived is not None:
            return ResolvedLogs(content=archived, source="archived")
        if resolve_error is not None:
            raise resolve_error
        raise HTTPException(status_code=409, detail="Submission not running in Nomad")
    if not cfg.nomad_endpoint:
        if archived is not None:
            return ResolvedLogs(content=archived, source="archived")
        raise HTTPException(status_code=500, detail="Nomad endpoint not configured")

    client = NomadClient(
        cfg.nomad_endpoint,
        token=cfg.nomad_token,
        namespace=record.get("namespace") or cfg.nomad_namespace,
        tls_ca=cfg.nomad_tls_ca,
        tls_skip_verify=cfg.nomad_tls_skip_verify,
    )
    try:
        allocs = client.job_allocations(nomad_job_id)
        alloc = latest_alloc(allocs)
        if not alloc:
            if archived is not None:
                return ResolvedLogs(content=archived, source="archived")
            raise HTTPException(status_code=404, detail="No allocations found")
        alloc_id = alloc.get("ID")
        if not isinstance(alloc_id, str):
            if archived is not None:
                return ResolvedLogs(content=archived, source="archived")
            raise HTTPException(status_code=404, detail="Allocation ID missing")
        return ResolvedLogs(
            content=client.alloc_logs(alloc_id, resolved_task, stderr=stderr, follow=follow),
            source="live",
        )
    except NomadError as exc:
        if archived is not None:
            return ResolvedLogs(content=archived, source="archived")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        client.close()



def cancel_submission_record(
    storage: Storage,
    cfg: SubmitConfig,
    *,
    submission_id: str,
    principal: AuthPrincipal,
) -> SubmissionRecord:
    record = get_submission_or_404(storage, submission_id, principal)
    nomad_job_id = record.get("nomad_job_id")
    if nomad_job_id and cfg.nomad_endpoint:
        client = NomadClient(
            cfg.nomad_endpoint,
            token=cfg.nomad_token,
            namespace=record.get("namespace") or cfg.nomad_namespace,
            tls_ca=cfg.nomad_tls_ca,
            tls_skip_verify=cfg.nomad_tls_skip_verify,
        )
        try:
            client.stop_job(nomad_job_id)
        except NomadError:
            pass
        finally:
            client.close()

    updated = storage.set_status(
        submission_id,
        "cancelled",
        finished_at=utcnow(),
    )
    return SubmissionRecord.from_row(updated)



def is_cancellable(status: object) -> bool:
    return isinstance(status, str) and status in _CANCELLABLE_STATUSES



def latest_alloc(allocs: object) -> dict[str, Any] | None:
    if not isinstance(allocs, list) or not allocs:
        return None
    candidates = [a for a in allocs if isinstance(a, dict)]
    if not candidates:
        return None
    candidates.sort(key=alloc_sort_key, reverse=True)
    return candidates[0]



def alloc_sort_key(alloc: dict[str, Any]) -> int:
    for key in ("ModifyTime", "CreateTime"):
        value = alloc.get(key)
        if isinstance(value, int):
            return value
    return 0



def resolve_nomad_job(
    record: dict[str, Any], job: str, task: str | None, index: int
) -> tuple[str | None, str]:
    if job == "submit":
        nomad_job_id = record.get("nomad_job_id") or record.get("id")
        return nomad_job_id, task or "submit"

    jobs = record.get("jobs") or {}
    info = jobs.get(job)
    if not isinstance(info, dict):
        raise HTTPException(status_code=404, detail=f"Job mapping not found: {job}")

    job_id: str | None = None
    if isinstance(info.get("job_id"), str):
        job_id = info.get("job_id")
    elif isinstance(info.get("job_ids"), list):
        job_ids = [j for j in info.get("job_ids") if isinstance(j, str)]
        if not job_ids:
            raise HTTPException(status_code=404, detail=f"No job IDs for: {job}")
        if index > len(job_ids):
            raise HTTPException(
                status_code=404,
                detail=f"Job index out of range for {job}: {index}",
            )
        job_id = job_ids[index - 1]

    if not job_id:
        raise HTTPException(status_code=404, detail=f"Job ID missing for: {job}")

    if task:
        return job_id, task

    if isinstance(info.get("task"), str):
        return job_id, info.get("task")

    tasks = info.get("tasks") if isinstance(info.get("tasks"), list) else None
    if tasks:
        clean = [t for t in tasks if isinstance(t, str)]
        if len(clean) == 1:
            return job_id, clean[0]
        raise HTTPException(
            status_code=400,
            detail=f"Multiple tasks for {job}; specify task. Options: {clean}",
        )

    return job_id, job_id



def archived_log_text(
    *,
    record: dict[str, Any],
    job: str,
    task: str | None,
    index: int,
    stderr: bool,
) -> str | None:
    archive = record.get("logs_archive")
    if not isinstance(archive, dict):
        return None
    raw_entries = archive.get("entries")
    if not isinstance(raw_entries, list):
        return None
    candidates: list[dict[str, Any]] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("job") != job:
            continue
        entry_index = entry.get("index")
        if isinstance(entry_index, bool):
            continue
        if isinstance(entry_index, int):
            resolved_index = entry_index
        elif isinstance(entry_index, str) and entry_index.isdigit():
            resolved_index = int(entry_index)
        else:
            resolved_index = 1
        if resolved_index != index:
            continue
        if bool(entry.get("stderr")) != stderr:
            continue
        if not isinstance(entry.get("content"), str):
            continue
        candidates.append(entry)
    if not candidates:
        return None
    if task:
        for entry in candidates:
            if archive_task(entry) == task:
                return entry["content"]
        return None
    if len(candidates) == 1:
        return candidates[0]["content"]
    unique_tasks = {archive_task(entry) for entry in candidates}
    if len(unique_tasks) == 1:
        return candidates[0]["content"]
    return None



def archive_task(entry: dict[str, Any]) -> str | None:
    task = entry.get("task")
    return task if isinstance(task, str) else None



def _legacy_token_name(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"legacy-{digest[:12]}"



def _matches_status_filter(record: dict[str, Any], status_filter: str) -> bool:
    status = str(record.get("status") or "")
    if status_filter == "all":
        return True
    if status_filter == "active":
        return status in _ACTIVE_STATUSES
    return status == status_filter
