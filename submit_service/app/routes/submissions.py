from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
import logging

from ..artifacts import validate_artifact_url
from ..config import SubmitConfig
from ..models import (
    SubmissionCreateRequest,
    SubmissionJobsUpdate,
    SubmissionLogsUpdate,
    SubmissionRecord,
    TokenRegistrationRequest,
    TokenRegistrationResponse,
)
from ..storage import Storage, new_submission_id, utcnow
from ..submissions_service import (
    AuthPrincipal,
    authenticate_request,
    cancel_submission_record,
    get_submission_or_404,
    is_report_token_request,
    list_visible_submissions,
    purge_submission_record,
    register_bearer_token,
    resolve_submission_logs,
)
from ..workers.dispatcher import dispatch_submission

router = APIRouter()
logger = logging.getLogger(__name__)
_SUBMISSION_STATUS_FILTERS = {"active", "completed", "failed", "cancelled", "all"}


def get_config(request: Request) -> SubmitConfig:
    return request.app.state.cfg


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


def authenticate(request: Request, cfg: SubmitConfig) -> AuthPrincipal:
    return authenticate_request(request, cfg)


def _reportable_submission(
    storage: Storage,
    submission_id: str,
    request: Request,
    cfg: SubmitConfig,
) -> dict[str, Any]:
    if is_report_token_request(request, cfg):
        try:
            return storage.get_submission(submission_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Submission not found") from exc
    principal = authenticate(request, cfg)
    return get_submission_or_404(storage, submission_id, principal)


@router.post("/v1/tokens/register", response_model=TokenRegistrationResponse)
def register_token(
    payload: TokenRegistrationRequest,
    request: Request,
    cfg: SubmitConfig = Depends(get_config),
    storage: Storage = Depends(get_storage),
) -> TokenRegistrationResponse:
    registered = register_bearer_token(
        storage,
        cfg,
        name=payload.name,
        token=payload.token,
    )
    return TokenRegistrationResponse(**registered)


@router.post("/v1/submissions", response_model=SubmissionRecord)
def create_submission(
    payload: SubmissionCreateRequest,
    request: Request,
    cfg: SubmitConfig = Depends(get_config),
    storage: Storage = Depends(get_storage),
) -> SubmissionRecord:
    principal = authenticate(request, cfg)
    artifact_url = validate_artifact_url(payload.artifact_url)
    submission_id = new_submission_id("sub")
    created_at = utcnow().isoformat()
    record = storage.create_submission(
        {
            "id": submission_id,
            "user": principal.name,
            "project_name": payload.project_name,
            "experiment": payload.experiment,
            "status": "queued",
            "created_at": created_at,
            "started_at": None,
            "finished_at": None,
            "nomad_job_id": None,
            "artifact_url": artifact_url,
            "submit_image": payload.submit_image,
            "node_class": payload.node_class,
            "args": payload.args,
            "env": payload.env,
            "submit_request": payload.submit_request,
            "priority": payload.priority,
            "logs_location": None,
            "result_location": None,
            "result_artifacts": [],
            "error_message": None,
            "blocked_reason": None,
            "namespace": payload.namespace,
        }
    )

    if cfg.dispatch_mode == "immediate":
        dispatch_submission(storage, record, cfg)
        record = storage.get_submission(submission_id)

    return SubmissionRecord.from_row(record)


@router.get("/v1/submissions", response_model=list[SubmissionRecord])
def list_submissions(
    request: Request,
    limit: int = Query(20, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    active_only: bool = Query(False),
    status: str | None = Query(None),
    cfg: SubmitConfig = Depends(get_config),
    storage: Storage = Depends(get_storage),
) -> list[SubmissionRecord]:
    principal = authenticate(request, cfg)
    status_filter = status.strip().lower() if isinstance(status, str) and status.strip() else None
    if status_filter is not None and status_filter not in _SUBMISSION_STATUS_FILTERS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported status filter: {status_filter}",
        )
    return list_visible_submissions(
        storage,
        principal,
        limit=limit,
        offset=offset,
        status_filter=status_filter,
        active_only=active_only,
    )


@router.get("/v1/submissions/{submission_id}", response_model=SubmissionRecord)
def get_submission(
    submission_id: str,
    request: Request,
    cfg: SubmitConfig = Depends(get_config),
    storage: Storage = Depends(get_storage),
) -> SubmissionRecord:
    principal = authenticate(request, cfg)
    record = get_submission_or_404(storage, submission_id, principal)
    return SubmissionRecord.from_row(record)


@router.get("/v1/submissions/{submission_id}/logs", response_class=PlainTextResponse)
def get_submission_logs(
    submission_id: str,
    request: Request,
    job: str = Query("submit"),
    task: str | None = Query(None),
    index: int = Query(1, ge=1),
    stderr: bool = Query(True),
    follow: bool = Query(False),
    cfg: SubmitConfig = Depends(get_config),
    storage: Storage = Depends(get_storage),
) -> str:
    principal = authenticate(request, cfg)
    record = get_submission_or_404(storage, submission_id, principal)
    return resolve_submission_logs(
        record,
        cfg,
        job=job,
        task=task,
        index=index,
        stderr=stderr,
        follow=follow,
    )


@router.post("/v1/submissions/{submission_id}/cancel", response_model=SubmissionRecord)
def cancel_submission(
    submission_id: str,
    request: Request,
    cfg: SubmitConfig = Depends(get_config),
    storage: Storage = Depends(get_storage),
) -> SubmissionRecord:
    principal = authenticate(request, cfg)
    return cancel_submission_record(
        storage,
        cfg,
        submission_id=submission_id,
        principal=principal,
    )


@router.post("/v1/submissions/{submission_id}/jobs", response_model=SubmissionRecord)
def update_submission_jobs(
    submission_id: str,
    payload: SubmissionJobsUpdate,
    request: Request,
    cfg: SubmitConfig = Depends(get_config),
    storage: Storage = Depends(get_storage),
) -> SubmissionRecord:
    record = _reportable_submission(storage, submission_id, request, cfg)
    updated = storage.update_submission(submission_id, {"jobs": payload.jobs})
    logger.info(
        "submission jobs updated: id=%s keys=%s",
        submission_id,
        sorted([k for k in payload.jobs.keys() if isinstance(k, str)]),
    )
    return SubmissionRecord.from_row(updated)


@router.post("/v1/submissions/{submission_id}/logs", response_model=SubmissionRecord)
def update_submission_logs(
    submission_id: str,
    payload: SubmissionLogsUpdate,
    request: Request,
    cfg: SubmitConfig = Depends(get_config),
    storage: Storage = Depends(get_storage),
) -> SubmissionRecord:
    record = _reportable_submission(storage, submission_id, request, cfg)

    updates: dict[str, Any] = {}
    if payload.logs_location is not None:
        updates["logs_location"] = payload.logs_location
    if payload.logs_archive is not None:
        updates["logs_archive"] = payload.logs_archive
    if not updates:
        return SubmissionRecord.from_row(record)

    updated = storage.update_submission(submission_id, updates)
    return SubmissionRecord.from_row(updated)


@router.post("/v1/submissions/{submission_id}/results", response_model=SubmissionRecord)
def update_submission_results(
    submission_id: str,
    payload: dict[str, Any],
    request: Request,
    cfg: SubmitConfig = Depends(get_config),
    storage: Storage = Depends(get_storage),
) -> SubmissionRecord:
    record = _reportable_submission(storage, submission_id, request, cfg)

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        artifacts = []
    clean = [a for a in artifacts if isinstance(a, str)]
    existing = record.get("result_artifacts") or []
    if not isinstance(existing, list):
        existing = []
    merged = existing + [a for a in clean if a not in existing]

    result_location = payload.get("result_location")
    updates: dict[str, Any] = {"result_artifacts": merged}
    if isinstance(result_location, str) and result_location:
        updates["result_location"] = result_location

    updated = storage.update_submission(submission_id, updates)
    return SubmissionRecord.from_row(updated)


@router.post("/v1/submissions/purge")
def purge_submissions(
    request: Request,
    cfg: SubmitConfig = Depends(get_config),
    storage: Storage = Depends(get_storage),
) -> dict[str, str]:
    principal = authenticate(request, cfg)
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    storage.clear_submissions()
    return {"status": "ok"}


@router.post("/v1/submissions/{submission_id}/purge")
def purge_submission(
    submission_id: str,
    request: Request,
    cfg: SubmitConfig = Depends(get_config),
    storage: Storage = Depends(get_storage),
) -> dict[str, str]:
    principal = authenticate(request, cfg)
    purge_submission_record(
        storage,
        submission_id=submission_id,
        principal=principal,
    )
    return {"status": "ok"}
