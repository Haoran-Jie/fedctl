from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
import re
from typing import Any

from ansi2html import Ansi2HTMLConverter
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import SubmitConfig
from ..submissions_service import (
    cancel_submission_record,
    get_submission_or_404,
    is_cancellable,
    is_purgeable,
    list_visible_submissions_for_ui,
    purge_submission_record,
    resolve_submission_logs_detail,
    submission_stats_for_ui,
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
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_ANSI_CONVERTER = Ansi2HTMLConverter(inline=True, dark_bg=False)


@router.get("/", response_class=HTMLResponse, response_model=None)
def home(request: Request) -> RedirectResponse:
    if current_ui_principal(request) is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    return RedirectResponse(url="/ui/submissions", status_code=303)


@router.get("/ui/login", response_class=HTMLResponse, response_model=None)
def login_page(request: Request) -> HTMLResponse | RedirectResponse:
    if current_ui_principal(request) is not None:
        return RedirectResponse(url="/ui/submissions", status_code=303)
    return _render(request, "login.html", {"error": None})


@router.post("/ui/login", response_class=HTMLResponse, response_model=None)
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


@router.post("/ui/logout", response_model=None)
def logout_submit(request: Request) -> RedirectResponse:
    logout(request)
    return RedirectResponse(url="/ui/login", status_code=303)


@router.get("/ui/submissions", response_class=HTMLResponse, response_model=None)
def submissions_page(
    request: Request,
    status: str = Query("active"),
) -> HTMLResponse | RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    status_filter = status if status in _STATUS_FILTERS else "active"
    visible_rows = list_visible_submissions_for_ui(
        request.app.state.storage,
        principal.as_auth_principal(),
        status_filter="all",
    )
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
            "stats": submission_stats_for_ui(visible_rows),
            "rows": [_submission_row_view(row, principal.role) for row in rows],
            "quick_command": _submission_list_command(status_filter),
        },
    )


@router.get("/ui/submissions/{submission_id}", response_class=HTMLResponse, response_model=None)
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
    logs_content, logs_error, logs_source = _resolve_logs_for_view(
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
        logs_source=logs_source,
    )


@router.post("/ui/submissions/{submission_id}/cancel", response_model=None)
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


@router.post("/ui/submissions/{submission_id}/purge", response_model=None)
def submission_purge(
    submission_id: str,
    request: Request,
) -> RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    purge_submission_record(
        request.app.state.storage,
        submission_id=submission_id,
        principal=principal.as_auth_principal(),
    )
    return RedirectResponse(url="/ui/submissions", status_code=303)


@router.get("/ui/submissions/{submission_id}/logs", response_class=HTMLResponse, response_model=None)
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
    logs_content, logs_error, logs_source = _resolve_logs_for_view(
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
            "logs_html": _render_logs_html(logs_content),
            "logs_error": logs_error,
            "logs_source": logs_source,
            "job": job,
            "task": task or "",
            "index": index,
            "stderr": stderr,
            "log_jobs": _LOG_JOBS,
        },
    )


@router.get("/ui/nodes", response_class=HTMLResponse, response_model=None)
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
            "quick_command": _inventory_command(
                status=status,
                node_class=node_class,
                device_type=device_type,
            ),
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
    logs_source: str | None,
) -> HTMLResponse:
    detail = _submission_detail_view(record, role)
    return _render(
        request,
        "submission_detail.html",
        {
            "submission": detail,
            "logs_content": logs_content,
            "logs_html": _render_logs_html(logs_content),
            "logs_error": logs_error,
            "logs_source": logs_source,
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
) -> tuple[str | None, str | None, str | None]:
    try:
        resolved = resolve_submission_logs_detail(
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
        return None, detail, None
    return resolved.content, None, resolved.source



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
    args = record.get("args") if isinstance(record.get("args"), list) else []
    env = record.get("env") if isinstance(record.get("env"), dict) else {}
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
        "args": args,
        "args_view": [_arg_view(arg, idx) for idx, arg in enumerate(args, start=1)],
        "env": env,
        "env_items": _env_items_view(env),
        "jobs": jobs,
        "job_entries": _job_entries_view(jobs),
        "result_location": record.get("result_location") or "-",
        "result_artifacts": result_artifacts,
        "error_message": record.get("error_message") or "",
        "blocked_reason": record.get("blocked_reason") or "",
        "can_cancel": is_cancellable(record.get("status")),
        "can_purge": is_purgeable(record.get("status")),
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



def _arg_view(arg: Any, index: int) -> dict[str, Any]:
    raw = str(arg)
    if raw.startswith("--") and "=" in raw:
        name, value = raw.split("=", 1)
        return {"index": index, "kind": "option", "name": name, "value": value, "raw": raw}
    if raw.startswith("--"):
        return {"index": index, "kind": "flag", "name": raw, "value": "", "raw": raw}
    if raw.startswith("-") and len(raw) > 1:
        return {"index": index, "kind": "switch", "name": raw, "value": "", "raw": raw}
    return {"index": index, "kind": "value", "name": raw, "value": "", "raw": raw}


def _env_items_view(env: dict[str, Any]) -> list[dict[str, str]]:
    return [{"key": str(key), "value": str(env[key])} for key in sorted(env)]


def _job_entries_view(jobs: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for job_name, info in jobs.items():
        if not isinstance(info, dict):
            entries.append(
                {
                    "name": str(job_name),
                    "summary": str(info),
                    "job_ids": [],
                    "tasks": [],
                    "fields": [],
                }
            )
            continue
        job_ids: list[str] = []
        if isinstance(info.get("job_id"), str):
            job_ids.append(info["job_id"])
        if isinstance(info.get("job_ids"), list):
            job_ids.extend(str(item) for item in info["job_ids"] if isinstance(item, str))
        tasks: list[str] = []
        if isinstance(info.get("task"), str):
            tasks.append(info["task"])
        if isinstance(info.get("tasks"), list):
            tasks.extend(str(item) for item in info["tasks"] if isinstance(item, str))
        fields: list[dict[str, str]] = []
        for key in sorted(info):
            if key in {"job_id", "job_ids", "task", "tasks"}:
                continue
            value = info[key]
            if isinstance(value, list):
                rendered = ", ".join(str(item) for item in value)
            elif isinstance(value, dict):
                rendered = ", ".join(f"{k}={v}" for k, v in sorted(value.items()))
            else:
                rendered = str(value)
            fields.append({"label": key.replace("_", " "), "value": rendered})
        summary_bits: list[str] = []
        if job_ids:
            summary_bits.append(f"{len(job_ids)} job id" + ("" if len(job_ids) == 1 else "s"))
        if tasks:
            summary_bits.append(f"{len(tasks)} task" + ("" if len(tasks) == 1 else "s"))
        entries.append(
            {
                "name": str(job_name),
                "summary": ", ".join(summary_bits) or "No mapping details",
                "job_ids": job_ids,
                "tasks": tasks,
                "fields": fields,
            }
        )
    entries.sort(key=lambda item: item["name"])
    return entries


def _submission_list_command(status_filter: str) -> str:
    if status_filter == "active":
        return "fedctl submit ls --active"
    return "fedctl submit ls --all"


def _inventory_command(
    *,
    status: str | None,
    node_class: str | None,
    device_type: str | None,
) -> str:
    parts = ["fedctl submit inventory"]
    if status:
        parts.extend(["--status", status])
    if node_class:
        parts.extend(["--class", node_class])
    if device_type:
        parts.extend(["--device-type", device_type])
    return " ".join(parts)


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


def _render_logs_html(content: str | None) -> str:
    if not content:
        return '<span class="log-empty">No log content available for this selection.</span>'
    if _ANSI_RE.search(content):
        return _ANSI_CONVERTER.convert(content, full=False)
    return escape(content)
