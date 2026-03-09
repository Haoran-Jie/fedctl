from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import SubmitConfig
from ..submissions_service import (
    cancel_submission_record,
    get_submission_or_404,
    is_cancellable,
    list_visible_submissions_for_ui,
    resolve_submission_logs,
)
from ..ui_auth import current_ui_principal, login_via_token, logout, require_ui_admin

router = APIRouter(include_in_schema=False)

_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

_STATUS_FILTERS = ["active", "completed", "failed", "cancelled", "all"]
_LOG_JOBS = [
    ("submit", "Submit"),
    ("superlink", "SuperLink"),
    ("supernodes", "Supernodes"),
    ("superexec_serverapp", "SuperExec serverapp"),
    ("superexec_clientapps", "SuperExec clientapps"),
]


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> RedirectResponse:
    if current_ui_principal(request) is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    return RedirectResponse(url="/ui/submissions", status_code=303)


@router.get("/ui/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse | RedirectResponse:
    if current_ui_principal(request) is not None:
        return RedirectResponse(url="/ui/submissions", status_code=303)
    return _render(request, "login.html", {"error": None})


@router.post("/ui/login", response_class=HTMLResponse)
def login_submit(request: Request, token: str = Form(...)) -> HTMLResponse | RedirectResponse:
    cfg: SubmitConfig = request.app.state.cfg
    try:
        login_via_token(request, cfg, token)
    except HTTPException as exc:
        return _render(
            request,
            "login.html",
            {"error": exc.detail if isinstance(exc.detail, str) else "Login failed."},
            status_code=exc.status_code,
        )
    return RedirectResponse(url="/ui/submissions", status_code=303)


@router.post("/ui/logout")
def logout_submit(request: Request) -> RedirectResponse:
    logout(request)
    return RedirectResponse(url="/ui/login", status_code=303)


@router.get("/ui/submissions", response_class=HTMLResponse)
def submissions_page(
    request: Request,
    status: str = Query("active"),
) -> HTMLResponse | RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    status_filter = status if status in _STATUS_FILTERS else "active"
    rows = list_visible_submissions_for_ui(
        request.app.state.storage,
        principal.as_auth_principal(),
        status_filter=status_filter,
    )
    return _render(
        request,
        "submissions_list.html",
        {
            "status_filter": status_filter,
            "status_filters": _STATUS_FILTERS,
            "rows": [_submission_row_view(row, principal.role) for row in rows],
        },
    )


@router.get("/ui/submissions/{submission_id}", response_class=HTMLResponse)
def submission_detail_page(
    submission_id: str,
    request: Request,
    job: str = Query("submit"),
    task: str | None = Query(None),
    index: int = Query(1, ge=1),
    stderr: bool = Query(True),
) -> HTMLResponse | RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    record = get_submission_or_404(
        request.app.state.storage,
        submission_id,
        principal.as_auth_principal(),
    )
    logs_content, logs_error = _resolve_logs_for_view(
        request,
        record,
        job=job,
        task=task,
        index=index,
        stderr=stderr,
    )
    return _render_submission_detail(
        request,
        principal.role,
        record,
        job=job,
        task=task,
        index=index,
        stderr=stderr,
        logs_content=logs_content,
        logs_error=logs_error,
    )


@router.post("/ui/submissions/{submission_id}/cancel")
def submission_cancel(
    submission_id: str,
    request: Request,
) -> RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    cancel_submission_record(
        request.app.state.storage,
        request.app.state.cfg,
        submission_id=submission_id,
        principal=principal.as_auth_principal(),
    )
    return RedirectResponse(url=f"/ui/submissions/{submission_id}", status_code=303)


@router.get("/ui/submissions/{submission_id}/logs", response_class=HTMLResponse)
def submission_logs_panel(
    submission_id: str,
    request: Request,
    job: str = Query("submit"),
    task: str | None = Query(None),
    index: int = Query(1, ge=1),
    stderr: bool = Query(True),
) -> HTMLResponse | RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    record = get_submission_or_404(
        request.app.state.storage,
        submission_id,
        principal.as_auth_principal(),
    )
    logs_content, logs_error = _resolve_logs_for_view(
        request,
        record,
        job=job,
        task=task,
        index=index,
        stderr=stderr,
    )
    return templates.TemplateResponse(
        request=request,
        name="logs_panel.html",
        context={
            "request": request,
            "submission": _submission_detail_view(record, principal.role),
            "logs_content": logs_content,
            "logs_error": logs_error,
            "job": job,
            "task": task or "",
            "index": index,
            "stderr": stderr,
            "log_jobs": _LOG_JOBS,
        },
    )


@router.get("/ui/nodes", response_class=HTMLResponse)
def nodes_page(
    request: Request,
    status: str | None = Query(None),
    node_class: str | None = Query(None),
    device_type: str | None = Query(None),
) -> HTMLResponse | RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    try:
        require_ui_admin(request)
    except HTTPException:
        return RedirectResponse(url="/ui/submissions", status_code=303)
    inventory = request.app.state.inventory
    try:
        nodes = inventory.list_nodes(include_allocs=True)
    except Exception as exc:
        return _render(
            request,
            "nodes.html",
            {
                "nodes": [],
                "filters": {
                    "status": status or "",
                    "node_class": node_class or "",
                    "device_type": device_type or "",
                },
                "error": str(exc),
            },
            status_code=502,
        )
    filtered = []
    for node in nodes:
        if status and node.get("status") != status:
            continue
        if node_class and node.get("node_class") != node_class:
            continue
        if device_type and node.get("device_type") != device_type:
            continue
        filtered.append(_node_view(node))
    return _render(
        request,
        "nodes.html",
        {
            "nodes": filtered,
            "filters": {
                "status": status or "",
                "node_class": node_class or "",
                "device_type": device_type or "",
            },
            "error": None,
        },
    )



def _render_submission_detail(
    request: Request,
    role: str,
    record: dict[str, Any],
    *,
    job: str,
    task: str | None,
    index: int,
    stderr: bool,
    logs_content: str | None,
    logs_error: str | None,
) -> HTMLResponse:
    detail = _submission_detail_view(record, role)
    return _render(
        request,
        "submission_detail.html",
        {
            "submission": detail,
            "logs_content": logs_content,
            "logs_error": logs_error,
            "job": job,
            "task": task or "",
            "index": index,
            "stderr": stderr,
            "log_jobs": _LOG_JOBS,
        },
    )



def _resolve_logs_for_view(
    request: Request,
    record: dict[str, Any],
    *,
    job: str,
    task: str | None,
    index: int,
    stderr: bool,
) -> tuple[str | None, str | None]:
    try:
        content = resolve_submission_logs(
            record,
            request.app.state.cfg,
            job=job,
            task=task,
            index=index,
            stderr=stderr,
            follow=False,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Failed to load logs."
        return None, detail
    return content, None



def _render(
    request: Request,
    template: str,
    context: dict[str, Any],
    *,
    status_code: int = 200,
) -> HTMLResponse:
    principal = current_ui_principal(request)
    merged = {
        "request": request,
        "principal": principal,
        **context,
    }
    return templates.TemplateResponse(
        request=request,
        name=template,
        context=merged,
        status_code=status_code,
    )



def _submission_row_view(record: dict[str, Any], role: str) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "project_name": record.get("project_name") or "-",
        "experiment": record.get("experiment") or "-",
        "status": record.get("status") or "unknown",
        "owner": record.get("user") if role == "admin" else None,
        "created_at": _fmt_dt(record.get("created_at")),
        "finished_at": _fmt_dt(record.get("finished_at")),
        "blocked_reason": record.get("blocked_reason") or record.get("error_message") or "",
        "namespace": record.get("namespace") or "-",
    }



def _submission_detail_view(record: dict[str, Any], role: str) -> dict[str, Any]:
    jobs = record.get("jobs") if isinstance(record.get("jobs"), dict) else {}
    result_artifacts = record.get("result_artifacts")
    if not isinstance(result_artifacts, list):
        result_artifacts = []
    return {
        "id": record.get("id"),
        "project_name": record.get("project_name") or "-",
        "experiment": record.get("experiment") or "-",
        "status": record.get("status") or "unknown",
        "owner": record.get("user") if role == "admin" else record.get("user"),
        "namespace": record.get("namespace") or "-",
        "priority": record.get("priority") if record.get("priority") is not None else "-",
        "created_at": _fmt_dt(record.get("created_at")),
        "started_at": _fmt_dt(record.get("started_at")),
        "finished_at": _fmt_dt(record.get("finished_at")),
        "nomad_job_id": record.get("nomad_job_id") or "-",
        "artifact_url": record.get("artifact_url") or "-",
        "submit_image": record.get("submit_image") or "-",
        "args": record.get("args") if isinstance(record.get("args"), list) else [],
        "env": record.get("env") if isinstance(record.get("env"), dict) else {},
        "jobs": jobs,
        "result_location": record.get("result_location") or "-",
        "result_artifacts": result_artifacts,
        "error_message": record.get("error_message") or "",
        "blocked_reason": record.get("blocked_reason") or "",
        "can_cancel": is_cancellable(record.get("status")),
    }



def _node_view(node: dict[str, Any]) -> dict[str, Any]:
    allocs = node.get("allocations") if isinstance(node.get("allocations"), list) else []
    return {
        "name": node.get("name") or node.get("node_name") or node.get("id") or "-",
        "id": node.get("id") or "-",
        "status": node.get("status") or "unknown",
        "node_class": node.get("node_class") or "-",
        "device_type": node.get("device_type") or "-",
        "alloc_count": len(allocs),
        "alloc_summary": ", ".join(
            sorted(
                str(alloc.get("Name") or alloc.get("ID"))
                for alloc in allocs
                if isinstance(alloc, dict)
            )
        ) or "-",
    }



def _fmt_dt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value)
    return dt.strftime("%Y-%m-%d %H:%M:%S")
