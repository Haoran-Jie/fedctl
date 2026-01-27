from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from ..artifacts import validate_artifact_url
from ..config import SubmitConfig
from ..models import SubmissionCreateRequest, SubmissionRecord
from ..nomad_client import NomadClient, NomadError
from ..storage import Storage, new_submission_id, utcnow
from ..workers.dispatcher import dispatch_submission

router = APIRouter()


def get_config(request: Request) -> SubmitConfig:
    return request.app.state.cfg


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


def authenticate(request: Request, cfg: SubmitConfig) -> str:
    auth_header = request.headers.get("Authorization", "")
    if cfg.tokens:
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        token = auth_header.replace("Bearer ", "", 1).strip()
        if token not in cfg.tokens:
            raise HTTPException(status_code=403, detail="Invalid token")
    elif not cfg.allow_unauth:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return request.headers.get("X-Submit-User") or "anonymous"


@router.post("/v1/submissions", response_model=SubmissionRecord)
def create_submission(
    payload: SubmissionCreateRequest,
    request: Request,
    cfg: SubmitConfig = Depends(get_config),
    storage: Storage = Depends(get_storage),
) -> SubmissionRecord:
    user = authenticate(request, cfg)
    artifact_url = validate_artifact_url(payload.artifact_url)
    submission_id = new_submission_id("sub")
    created_at = utcnow().isoformat()
    record = storage.create_submission(
        {
            "id": submission_id,
            "user": user,
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
            "priority": payload.priority,
            "logs_location": None,
            "result_location": None,
            "error_message": None,
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
    limit: int = Query(20, ge=1, le=200),
    cfg: SubmitConfig = Depends(get_config),
    storage: Storage = Depends(get_storage),
) -> list[SubmissionRecord]:
    authenticate(request, cfg)
    rows = storage.list_submissions(limit=limit)
    return [SubmissionRecord.from_row(row) for row in rows]


@router.get("/v1/submissions/{submission_id}", response_model=SubmissionRecord)
def get_submission(
    submission_id: str,
    request: Request,
    cfg: SubmitConfig = Depends(get_config),
    storage: Storage = Depends(get_storage),
) -> SubmissionRecord:
    authenticate(request, cfg)
    try:
        record = storage.get_submission(submission_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Submission not found")
    return SubmissionRecord.from_row(record)


@router.get("/v1/submissions/{submission_id}/logs", response_class=PlainTextResponse)
def get_submission_logs(
    submission_id: str,
    request: Request,
    task: str = Query("submit"),
    stderr: bool = Query(True),
    follow: bool = Query(False),
    cfg: SubmitConfig = Depends(get_config),
    storage: Storage = Depends(get_storage),
) -> str:
    authenticate(request, cfg)
    try:
        record = storage.get_submission(submission_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Submission not found")

    nomad_job_id = record.get("nomad_job_id")
    if not nomad_job_id:
        raise HTTPException(status_code=409, detail="Submission not running in Nomad")
    if not cfg.nomad_endpoint:
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
        alloc = _latest_alloc(allocs)
        if not alloc:
            raise HTTPException(status_code=404, detail="No allocations found")
        alloc_id = alloc.get("ID")
        if not isinstance(alloc_id, str):
            raise HTTPException(status_code=404, detail="Allocation ID missing")
        return client.alloc_logs(alloc_id, task, stderr=stderr, follow=follow)
    except NomadError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    finally:
        client.close()


@router.post("/v1/submissions/{submission_id}/cancel", response_model=SubmissionRecord)
def cancel_submission(
    submission_id: str,
    request: Request,
    cfg: SubmitConfig = Depends(get_config),
    storage: Storage = Depends(get_storage),
) -> SubmissionRecord:
    authenticate(request, cfg)
    try:
        record = storage.get_submission(submission_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Submission not found")

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


def _latest_alloc(allocs: object) -> dict[str, Any] | None:
    if not isinstance(allocs, list) or not allocs:
        return None
    candidates = [a for a in allocs if isinstance(a, dict)]
    if not candidates:
        return None
    candidates.sort(key=_alloc_sort_key, reverse=True)
    return candidates[0]


def _alloc_sort_key(alloc: dict[str, Any]) -> int:
    for key in ("ModifyTime", "CreateTime"):
        value = alloc.get(key)
        if isinstance(value, int):
            return value
    return 0
