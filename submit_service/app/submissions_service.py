from __future__ import annotations

from dataclasses import dataclass
import secrets
import re
from typing import Any
import hashlib
import json
import sqlite3

from fastapi import HTTPException, Request
import httpx

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
_PURGEABLE_STATUSES = {"completed", "failed", "cancelled"}
_REGISTERED_TOKEN_PREFIX = "fedctl_"
_MIN_REGISTERED_TOKEN_LENGTH = 24
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


def authenticate_request(request: Request, cfg: SubmitConfig) -> AuthPrincipal:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "", 1).strip()
        principal = principal_for_token(token, cfg, storage=getattr(request.app.state, "storage", None))
        if principal is None:
            raise HTTPException(status_code=403, detail="Invalid token")
        return principal
    if cfg.tokens or cfg.token_identities or cfg.registration_enabled:
        if not cfg.allow_unauth:
            raise HTTPException(status_code=401, detail="Missing bearer token")
    if not cfg.allow_unauth:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return AuthPrincipal(name="anonymous", role="admin", token=None)



def principal_for_token(
    token: str,
    cfg: SubmitConfig,
    *,
    storage: Storage | None = None,
) -> AuthPrincipal | None:
    token = token.strip()
    if not token:
        return None
    identity = cfg.token_identities.get(token)
    if identity is not None:
        return AuthPrincipal(name=identity.name, role=identity.role, token=token)
    if token in cfg.tokens:
        return AuthPrincipal(name=_legacy_token_name(token), role="admin", token=token)
    if storage is not None:
        registered = storage.get_bearer_token(_token_hash(token))
        if registered is not None:
            name = registered.get("name")
            role = registered.get("role")
            if isinstance(name, str) and isinstance(role, str) and role in {"user", "admin"}:
                return AuthPrincipal(name=name, role=role, token=token)
    return None


def register_bearer_token(
    storage: Storage,
    cfg: SubmitConfig,
    *,
    name: str,
    token: str | None = None,
    registration_code: str | None = None,
) -> dict[str, str]:
    if not cfg.registration_enabled:
        raise HTTPException(status_code=403, detail="Token registration is disabled.")
    if cfg.registration_code and not secrets.compare_digest(
        cfg.registration_code, (registration_code or "").strip()
    ):
        raise HTTPException(status_code=403, detail="Invalid registration code.")
    clean_name = _clean_registered_name(name)
    issued_token = _clean_registered_token(token) if token else _generate_bearer_token()
    try:
        record = storage.create_bearer_token(
            token_hash=_token_hash(issued_token),
            name=clean_name,
            role="user",
            created_at=utcnow().isoformat(),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="That username or bearer token is already registered.",
        ) from exc
    return {
        "name": str(record["name"]),
        "role": str(record["role"]),
        "token": issued_token,
    }



def ensure_submission_access(record: dict[str, Any], principal: AuthPrincipal) -> None:
    if principal.role == "admin":
        return
    owner = record.get("user")
    if isinstance(owner, str) and owner == principal.name:
        return
    raise HTTPException(status_code=404, detail="Submission not found")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generate_bearer_token() -> str:
    return f"{_REGISTERED_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def _clean_registered_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not _USERNAME_RE.fullmatch(cleaned):
        raise HTTPException(
            status_code=422,
            detail="Username must be 3-64 characters and use only letters, numbers, dot, dash, or underscore.",
        )
    return cleaned


def _clean_registered_token(token: str) -> str:
    cleaned = (token or "").strip()
    if len(cleaned) < _MIN_REGISTERED_TOKEN_LENGTH or any(ch.isspace() for ch in cleaned):
        raise HTTPException(
            status_code=422,
            detail=f"Bearer token must be at least {_MIN_REGISTERED_TOKEN_LENGTH} characters with no whitespace.",
        )
    return cleaned



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
    offset: int = 0,
    status_filter: str | None = None,
    active_only: bool = False,
) -> list[SubmissionRecord]:
    effective_filter = status_filter or ("active" if active_only else "all")
    statuses = _submission_statuses_for_filter(effective_filter)
    rows = storage.list_submissions(
        limit=limit,
        offset=offset,
        statuses=statuses,
        user=None if principal.role == "admin" else principal.name,
    )
    return [SubmissionRecord.from_row(row) for row in rows]



def list_visible_submissions_for_ui(
    storage: Storage,
    principal: AuthPrincipal,
    *,
    status_filter: str = "all",
    limit: int = 100,
    offset: int = 0,
    search_query: str | None = None,
    default_priority: int = 50,
) -> list[dict[str, Any]]:
    user = _ui_submission_list_user(principal, status_filter=status_filter)
    rows = storage.list_submissions(
        limit=limit,
        offset=offset,
        statuses=_submission_statuses_for_filter(status_filter),
        user=user,
        query=search_query,
        order="ui",
        default_priority=default_priority,
    )
    return rows


def count_visible_submissions_for_ui(
    storage: Storage,
    principal: AuthPrincipal,
    *,
    status_filter: str = "all",
    search_query: str | None = None,
) -> int:
    user = _ui_submission_list_user(principal, status_filter=status_filter)
    return storage.count_submissions(
        statuses=_submission_statuses_for_filter(status_filter),
        user=user,
        query=search_query,
    )


def _ui_submission_list_user(principal: AuthPrincipal, *, status_filter: str) -> str | None:
    if principal.role == "admin":
        return None
    if status_filter == "active":
        return None
    return principal.name


def submission_stats_for_principal(
    storage: Storage,
    principal: AuthPrincipal,
) -> dict[str, int]:
    if principal.role == "admin":
        return {
            "total": storage.count_submissions(),
            "active": storage.count_submissions(statuses=list(_ACTIVE_STATUSES)),
            "blocked": storage.count_submissions(statuses=["blocked"]),
            "failed": storage.count_submissions(statuses=["failed"]),
            "completed": storage.count_submissions(statuses=["completed"]),
        }

    user = principal.name
    own_total = storage.count_submissions(user=user)
    own_active = storage.count_submissions(statuses=list(_ACTIVE_STATUSES), user=user)
    all_active = storage.count_submissions(statuses=list(_ACTIVE_STATUSES))
    return {
        "total": own_total + max(0, all_active - own_active),
        "active": all_active,
        "blocked": storage.count_submissions(statuses=["blocked"]),
        "failed": storage.count_submissions(statuses=["failed"], user=user),
        "completed": storage.count_submissions(statuses=["completed"], user=user),
    }


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
    archived = external_archived_log_text(
        record=record,
        job=job,
        task=task,
        index=index,
        stderr=stderr,
    )
    archived_issue = external_archived_log_issue(
        record=record,
        job=job,
        task=task,
        index=index,
        stderr=stderr,
    )
    if archived is None and archived_issue is None:
        archived = archived_log_text(
            record=record,
            job=job,
            task=task,
            index=index,
            stderr=stderr,
        )
    if archived_issue is None:
        archived_issue = archived_log_issue(
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
        if archived_issue is not None:
            raise HTTPException(status_code=404, detail=f"Archived log unavailable: {archived_issue}")
        if resolve_error is not None:
            raise resolve_error
        raise HTTPException(status_code=409, detail="Submission not running in Nomad")
    if not cfg.nomad_endpoint:
        if archived is not None:
            return ResolvedLogs(content=archived, source="archived")
        if archived_issue is not None:
            raise HTTPException(status_code=404, detail=f"Archived log unavailable: {archived_issue}")
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
        alloc = latest_alloc_for_task(allocs, resolved_task)
        if not alloc:
            if archived is not None:
                return ResolvedLogs(content=archived, source="archived")
            if archived_issue is not None:
                raise HTTPException(status_code=404, detail=f"Archived log unavailable: {archived_issue}")
            raise HTTPException(status_code=404, detail="No allocations found")
        alloc_id = alloc.get("ID")
        if not isinstance(alloc_id, str):
            if archived is not None:
                return ResolvedLogs(content=archived, source="archived")
            if archived_issue is not None:
                raise HTTPException(status_code=404, detail=f"Archived log unavailable: {archived_issue}")
            raise HTTPException(status_code=404, detail="Allocation ID missing")
        return ResolvedLogs(
            content=client.alloc_logs(alloc_id, resolved_task, stderr=stderr, follow=follow),
            source="live",
        )
    except NomadError as exc:
        if archived is not None:
            return ResolvedLogs(content=archived, source="archived")
        if archived_issue is not None:
            raise HTTPException(status_code=404, detail=f"Archived log unavailable: {archived_issue}")
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


def purge_submission_record(
    storage: Storage,
    *,
    submission_id: str,
    principal: AuthPrincipal,
) -> None:
    record = get_submission_or_404(storage, submission_id, principal)
    if not is_purgeable(record.get("status")):
        raise HTTPException(
            status_code=409,
            detail="Only completed, failed, or cancelled submissions can be purged",
        )
    storage.delete_submission(submission_id)


def is_cancellable(status: object) -> bool:
    return isinstance(status, str) and status in _CANCELLABLE_STATUSES


def is_purgeable(status: object) -> bool:
    return isinstance(status, str) and status in _PURGEABLE_STATUSES



def latest_alloc(allocs: object) -> dict[str, Any] | None:
    if not isinstance(allocs, list) or not allocs:
        return None
    candidates = [a for a in allocs if isinstance(a, dict)]
    if not candidates:
        return None
    candidates.sort(key=alloc_sort_key, reverse=True)
    return candidates[0]



def latest_alloc_for_task(allocs: object, task: str) -> dict[str, Any] | None:
    alloc = latest_matching_alloc(allocs, task)
    if alloc is not None:
        return alloc
    return latest_alloc(allocs)


def latest_matching_alloc(allocs: object, task: str) -> dict[str, Any] | None:
    if not isinstance(allocs, list) or not allocs:
        return None
    candidates = [
        alloc
        for alloc in allocs
        if isinstance(alloc, dict) and alloc_has_task(alloc, task)
    ]
    if not candidates:
        return None
    candidates.sort(key=alloc_sort_key, reverse=True)
    return candidates[0]


def alloc_has_task(alloc: dict[str, Any], task: str) -> bool:
    task_states = alloc.get("TaskStates")
    if isinstance(task_states, dict) and task in task_states:
        return True
    task_resources = alloc.get("TaskResources")
    if isinstance(task_resources, dict) and task in task_resources:
        return True
    allocated_resources = alloc.get("AllocatedResources")
    if isinstance(allocated_resources, dict):
        tasks = allocated_resources.get("Tasks")
        if isinstance(tasks, dict) and task in tasks:
            return True
    return False


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

    targets = _clean_log_targets(info.get("targets"))
    if targets:
        if task:
            for target_entry in targets:
                if target_entry["task"] == task:
                    return target_entry["job_id"], target_entry["task"]
            raise HTTPException(status_code=404, detail=f"Task not found for {job}: {task}")
        for target_entry in targets:
            if target_entry["index"] == index:
                return target_entry["job_id"], target_entry["task"]
        raise HTTPException(
            status_code=404,
            detail=f"Job index out of range for {job}: {index}",
        )

    if task:
        return job_id, task

    if isinstance(info.get("task"), str):
        return job_id, info.get("task")

    tasks = info.get("tasks") if isinstance(info.get("tasks"), list) else None
    if tasks:
        clean = [t for t in tasks if isinstance(t, str)]
        if not clean:
            raise HTTPException(status_code=404, detail=f"No tasks for: {job}")
        if index > len(clean):
            raise HTTPException(
                status_code=404,
                detail=f"Task index out of range for {job}: {index}",
            )
        if len(clean) == 1:
            return job_id, clean[0]
        return job_id, clean[index - 1]

    return job_id, job_id


def _clean_log_targets(raw_targets: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_targets, list):
        return []
    targets: list[dict[str, Any]] = []
    for entry in raw_targets:
        if not isinstance(entry, dict):
            continue
        index = entry.get("index")
        job_id = entry.get("job_id")
        task = entry.get("task")
        if not isinstance(index, int) or isinstance(index, bool):
            continue
        if not isinstance(job_id, str) or not isinstance(task, str):
            continue
        targets.append({"index": index, "job_id": job_id, "task": task})
    targets.sort(key=lambda item: item["index"])
    return targets



def archived_log_text(
    *,
    record: dict[str, Any],
    job: str,
    task: str | None,
    index: int,
    stderr: bool,
) -> str | None:
    candidates = matching_archive_entries(
        record=record,
        job=job,
        index=index,
        stderr=stderr,
        field="content",
    )
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


def external_archived_log_text(
    *,
    record: dict[str, Any],
    job: str,
    task: str | None,
    index: int,
    stderr: bool,
) -> str | None:
    candidates = matching_external_archive_entries(
        record=record,
        job=job,
        index=index,
        stderr=stderr,
        field="url",
    )
    if not candidates:
        return None
    entry = _resolve_archive_candidate(candidates, task)
    if entry is None:
        return None
    url = entry.get("url")
    if not isinstance(url, str) or not url:
        return None
    try:
        return _fetch_text_url(url)
    except httpx.HTTPError:
        return None



def archived_log_issue(
    *,
    record: dict[str, Any],
    job: str,
    task: str | None,
    index: int,
    stderr: bool,
) -> str | None:
    candidates = matching_archive_entries(
        record=record,
        job=job,
        index=index,
        stderr=stderr,
        field="error",
    )
    if not candidates:
        return None
    if task:
        for entry in candidates:
            if archive_task(entry) == task:
                return archive_error(entry)
        return None
    if len(candidates) == 1:
        return archive_error(candidates[0])
    unique_tasks = {archive_task(entry) for entry in candidates}
    if len(unique_tasks) == 1:
        return archive_error(candidates[0])
    return None


def external_archived_log_issue(
    *,
    record: dict[str, Any],
    job: str,
    task: str | None,
    index: int,
    stderr: bool,
) -> str | None:
    candidates = matching_external_archive_entries(
        record=record,
        job=job,
        index=index,
        stderr=stderr,
        field="error",
    )
    if not candidates:
        return None
    entry = _resolve_archive_candidate(candidates, task)
    if entry is None:
        return None
    return archive_error(entry)


def matching_archive_entries(
    *,
    record: dict[str, Any],
    job: str,
    index: int,
    stderr: bool,
    field: str,
) -> list[dict[str, Any]]:
    archive = record.get("logs_archive")
    if not isinstance(archive, dict):
        return []
    raw_entries = archive.get("entries")
    if not isinstance(raw_entries, list):
        return []
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
        if field == "content" and not isinstance(entry.get("content"), str):
            continue
        if field == "error" and not isinstance(entry.get("error"), str):
            continue
        candidates.append(entry)
    return candidates


def matching_external_archive_entries(
    *,
    record: dict[str, Any],
    job: str,
    index: int,
    stderr: bool,
    field: str,
) -> list[dict[str, Any]]:
    manifest = _load_external_logs_manifest(record)
    if not isinstance(manifest, dict):
        return []
    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list):
        return []
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
        if field == "url" and not isinstance(entry.get("url"), str):
            continue
        if field == "error" and not isinstance(entry.get("error"), str):
            continue
        candidates.append(entry)
    return candidates


def _load_external_logs_manifest(record: dict[str, Any]) -> dict[str, Any] | None:
    location = record.get("logs_location")
    if not isinstance(location, str) or not location or location == "inline://submit-service-db":
        return None
    try:
        content = _fetch_text_url(location)
    except httpx.HTTPError:
        return None
    try:
        manifest = json.loads(content)
    except ValueError:
        return None
    return manifest if isinstance(manifest, dict) else None


def _fetch_text_url(url: str) -> str:
    response = httpx.get(url, timeout=30.0)
    response.raise_for_status()
    return response.text


def _resolve_archive_candidate(
    candidates: list[dict[str, Any]],
    task: str | None,
) -> dict[str, Any] | None:
    if task:
        for entry in candidates:
            if archive_task(entry) == task:
                return entry
        return None
    if len(candidates) == 1:
        return candidates[0]
    unique_tasks = {archive_task(entry) for entry in candidates}
    if len(unique_tasks) == 1:
        return candidates[0]
    return None


def archive_task(entry: dict[str, Any]) -> str | None:
    task = entry.get("task")
    return task if isinstance(task, str) else None


def archive_error(entry: dict[str, Any]) -> str | None:
    error = entry.get("error")
    return error if isinstance(error, str) else None



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


def _submission_statuses_for_filter(status_filter: str) -> list[str] | None:
    if status_filter == "all":
        return None
    if status_filter == "active":
        return list(_ACTIVE_STATUSES)
    return [status_filter]
