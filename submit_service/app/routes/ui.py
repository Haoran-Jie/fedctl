from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
_HELP_COMMANDS = [
    {
        "name": "submit run",
        "summary": "Package a local Flower project, upload the archive, and create a queued submission.",
        "importance": "primary",
        "syntax": "fedctl submit run <project-dir>",
        "examples": [
            "fedctl submit run ../quickstart-pytorch",
            "fedctl submit run ../quickstart-pytorch --exp pytorch-baseline-r1",
            "fedctl submit run ../quickstart-pytorch --priority 70 --no-destroy",
        ],
        "notes": [
            "This is the main entrypoint for normal users.",
            "It handles inspect, archive, upload, and submit in one flow.",
            "Use --no-destroy when you want to inspect live Nomad jobs after completion.",
        ],
    },
    {
        "name": "submit ls",
        "summary": "List recent submissions from the submit service.",
        "importance": "standard",
        "syntax": "fedctl submit ls [--active|--completed|--failed|--cancelled|--all] [--limit N]",
        "examples": [
            "fedctl submit ls",
            "fedctl submit ls --completed",
            "fedctl submit ls --limit 50",
        ],
        "notes": [
            "Default output shows the active queue even when no status flag is provided.",
        ],
    },
    {
        "name": "submit status",
        "summary": "Show the current status, blocked reason, or failure message for one submission.",
        "importance": "standard",
        "syntax": "fedctl submit status <submission-id>",
        "examples": [
            "fedctl submit status sub-20260227182713-5413",
        ],
        "notes": [
            "Use this first when a run looks stuck or blocked.",
        ],
    },
    {
        "name": "submit logs",
        "summary": "Read live or archived logs for the submit job and downstream Flower jobs.",
        "importance": "standard",
        "syntax": "fedctl submit logs <submission-id> [--job JOB] [--task TASK] [--index N] [--stderr|--stdout] [--follow]",
        "examples": [
            "fedctl submit logs sub-20260227182713-5413",
            "fedctl submit logs sub-20260227182713-5413 --job superlink --stderr",
            "fedctl submit logs sub-20260227182713-5413 --job superexec_clientapps --index 2 --stdout",
        ],
        "notes": [
            "Use --job supernodes with --task to target a specific supernode task.",
            "When Nomad allocations are gone, the service falls back to archived logs if available.",
        ],
    },
    {
        "name": "submit cancel",
        "summary": "Stop an active submission and mark it cancelled.",
        "importance": "standard",
        "syntax": "fedctl submit cancel <submission-id>",
        "examples": [
            "fedctl submit cancel sub-20260227182713-5413",
        ],
        "notes": [
            "Use this for queued, running, or blocked submissions.",
        ],
    },
    {
        "name": "submit purge",
        "summary": "Delete submission history, either for one terminal submission or for all history.",
        "importance": "standard",
        "syntax": "fedctl submit purge [submission-id]",
        "examples": [
            "fedctl submit purge sub-20260227182713-5413",
            "fedctl submit purge",
        ],
        "notes": [
            "Purging a single submission is allowed for the owner or admin, but only after it is completed, failed, or cancelled.",
            "Purging without an ID clears the whole submission history and is the stronger action.",
        ],
    },
    {
        "name": "submit results",
        "summary": "Show or download result artifact URLs recorded for a submission.",
        "importance": "standard",
        "syntax": "fedctl submit results <submission-id> [--download] [--out PATH]",
        "examples": [
            "fedctl submit results sub-20260227182713-5413",
            "fedctl submit results sub-20260227182713-5413 --download --out ./results",
        ],
        "notes": [
            "This is useful when the runner uploaded result files and you want the URLs or local copies.",
        ],
    },
    {
        "name": "submit inventory",
        "summary": "Inspect the Nomad node inventory exposed by the submit service.",
        "importance": "standard",
        "syntax": "fedctl submit inventory [--status STATUS] [--class CLASS] [--device-type TYPE] [--detail] [--json]",
        "examples": [
            "fedctl submit inventory",
            "fedctl submit inventory --status ready --class submit",
            "fedctl submit inventory --detail",
        ],
        "notes": [
            "This is mainly an operator/admin command for checking cluster capacity and placement constraints.",
        ],
    },
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
    q: str | None = Query(None),
) -> HTMLResponse | RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    status_filter = status if status in _STATUS_FILTERS else "active"
    search_query = (q or "").strip()
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
    if search_query:
        rows = [row for row in rows if _submission_matches_query(row, search_query)]
    return _render(
        request,
        "submissions_list.html",
        {
            "status_filter": status_filter,
            "status_filters": _STATUS_FILTERS,
            "search_query": search_query,
            "stats": submission_stats_for_ui(visible_rows),
            "rows": [_submission_row_view(row, principal.role) for row in rows],
            "quick_command": _submission_list_command(status_filter),
            "return_to": _submission_list_return_to(status_filter=status_filter, q=search_query),
            "page_palette_commands": _submissions_palette_commands(),
        },
    )


@router.get("/ui/help", response_class=HTMLResponse, response_model=None)
def help_page(request: Request) -> HTMLResponse | RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    quickstart_steps = [
        {
            "title": "Submit a project",
            "body": "Run fedctl submit run on a local Flower project directory. This is the normal path for users.",
            "command": "fedctl submit run ../quickstart-pytorch",
        },
        {
            "title": "Check queue and status",
            "body": "List active submissions, then inspect one specific submission if needed.",
            "command": "fedctl submit ls --active\nfedctl submit status <submission-id>",
        },
        {
            "title": "Inspect logs or results",
            "body": "Use logs during execution and results after completion.",
            "command": "fedctl submit logs <submission-id> --job submit --stderr\nfedctl submit results <submission-id>",
        },
    ]
    return _render(
        request,
        "help.html",
        {
            "commands": _HELP_COMMANDS,
            "quickstart_steps": quickstart_steps,
            "page_palette_commands": _help_palette_commands(_HELP_COMMANDS),
        },
    )


@router.get("/ui/submissions/{submission_id}", response_class=HTMLResponse, response_model=None)
def submission_detail_page(
    submission_id: str,
    request: Request,
    return_to: str | None = Query(None),
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
        return_to=_safe_return_to(return_to),
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
    return RedirectResponse(
        url=_append_notice(f"/ui/submissions/{submission_id}", "Submission cancelled."),
        status_code=303,
    )


@router.post("/ui/submissions/{submission_id}/purge", response_model=None)
def submission_purge(
    submission_id: str,
    request: Request,
    return_to: str | None = Form(None),
) -> RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    purge_submission_record(
        request.app.state.storage,
        submission_id=submission_id,
        principal=principal.as_auth_principal(),
    )
    return RedirectResponse(
        url=_append_notice(_safe_return_to(return_to), "Submission purged."),
        status_code=303,
    )


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
    q: str | None = Query(None),
) -> HTMLResponse | RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/ui/login", status_code=303)
    try:
        require_ui_admin(request)
    except HTTPException:
        return RedirectResponse(url="/ui/submissions", status_code=303)
    inventory = request.app.state.inventory
    search_query = (q or "").strip()
    try:
        nodes = inventory.list_nodes(include_allocs=True)
    except Exception as exc:
        return _render(
            request,
            "nodes.html",
            {
                "nodes": [],
                "filters": {"q": search_query},
                "error": str(exc),
                "page_palette_commands": _nodes_palette_commands(),
            },
            status_code=502,
        )
    filtered = []
    for node in nodes:
        view = _node_view(node)
        if search_query and not _node_matches_query(view, search_query):
            continue
        filtered.append(view)
    return _render(
        request,
        "nodes.html",
        {
            "nodes": filtered,
            "filters": {"q": search_query},
            "error": None,
            "quick_command": _inventory_command(),
            "page_palette_commands": _nodes_palette_commands(),
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
    return_to: str,
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
            "return_to": return_to,
            "page_palette_commands": _submission_detail_palette_commands(
                submission_id=detail["id"],
                return_to=return_to,
                job=job,
                task=task or "",
                index=index,
                stderr=stderr,
            ),
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
    page_palette_commands = list(context.get("page_palette_commands") or [])
    merged = {
        "request": request,
        "principal": principal,
        "palette_commands": _global_palette_commands(principal) + page_palette_commands,
        **context,
    }
    return templates.TemplateResponse(
        request=request,
        name=template,
        context=merged,
        status_code=status_code,
    )


def _safe_return_to(value: str | None) -> str:
    if isinstance(value, str) and value.startswith("/ui/submissions"):
        return value
    return "/ui/submissions"


def _append_notice(url: str, message: str, kind: str = "success") -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["notice"] = message
    query["notice_kind"] = kind
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def _submission_list_return_to(*, status_filter: str, q: str) -> str:
    params = {"status": status_filter}
    if q:
        params["q"] = q
    return urlunsplit(("", "", "/ui/submissions", urlencode(params), ""))


def _contains_query(values: list[object], query: str) -> bool:
    needle = query.casefold()
    return any(needle in str(value or "").casefold() for value in values)


def _submission_matches_query(record: dict[str, Any], query: str) -> bool:
    return _contains_query(
        [
            record.get("id"),
            record.get("project_name"),
            record.get("experiment"),
            record.get("user"),
            record.get("namespace"),
        ],
        query,
    )


def _node_matches_query(record: dict[str, Any], query: str) -> bool:
    return _contains_query(
        [
            record.get("name"),
            record.get("id"),
            record.get("status"),
            record.get("node_class"),
            record.get("device_type"),
            record.get("alloc_count"),
            record.get("alloc_summary"),
        ],
        query,
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
    submit_request = (
        record.get("submit_request") if isinstance(record.get("submit_request"), dict) else {}
    )
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
        "artifact_url": _link_entry_view(record.get("artifact_url")),
        "submit_image": record.get("submit_image") or "-",
        "submit_request": submit_request,
        "submit_request_view": _submit_request_view(submit_request),
        "args": args,
        "args_view": [_arg_view(arg, idx) for idx, arg in enumerate(args, start=1)],
        "jobs": jobs,
        "job_entries": _job_entries_view(jobs),
        "result_location": _link_entry_view(record.get("result_location")),
        "result_artifacts": _artifact_rows_view(result_artifacts),
        "error_message": record.get("error_message") or "",
        "blocked_reason": record.get("blocked_reason") or "",
        "can_cancel": is_cancellable(record.get("status")),
        "can_purge": is_purgeable(record.get("status")),
    }


def _submit_request_view(submit_request: dict[str, Any]) -> dict[str, Any]:
    command_preview = submit_request.get("command_preview")
    options = submit_request.get("options") if isinstance(submit_request.get("options"), dict) else {}
    summary_order = [
        "experiment",
        "num_supernodes",
        "priority",
        "federation",
        "image",
        "submit_image",
    ]
    detail_order = [
        "artifact_store",
        "timeout",
        "stream",
        "destroy",
        "auto_supernodes",
        "allow_oversubscribe",
        "push",
        "platform",
        "context",
        "repo_config",
        "verbose",
        "supernodes",
        "net",
    ]
    summary_items = _request_items(options, summary_order)
    detail_items = _request_items(options, detail_order)
    return {
        "path_input": submit_request.get("path_input") or "",
        "project_root": submit_request.get("project_root") or "",
        "cwd": submit_request.get("cwd") or "",
        "command_preview": command_preview if isinstance(command_preview, str) else "",
        "summary_items": summary_items,
        "detail_items": detail_items,
    }


def _request_items(options: dict[str, Any], order: list[str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for key in order:
        if key not in options:
            continue
        items.append(
            {
                "label": key.replace("_", " "),
                "value": _request_value(options[key]),
            }
        )
    return items


def _request_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _link_entry_view(value: Any) -> dict[str, str] | None:
    if not isinstance(value, str) or not value or value == "-":
        return None
    label = _artifact_name_from_url(value) or value
    return {
        "url": value,
        "label": label,
        "type": _artifact_type(label),
        "signed": "yes" if _is_presigned_url(value) else "no",
    }


def _artifact_rows_view(artifacts: list[Any]) -> dict[str, list[dict[str, str]]]:
    rows = [_artifact_view(item, idx) for idx, item in enumerate(artifacts, start=1)]
    primary = [row for row in rows if row["priority"] == "primary"]
    secondary = [row for row in rows if row["priority"] != "primary"]
    return {"primary": primary, "secondary": secondary}


def _artifact_view(item: Any, index: int) -> dict[str, str]:
    if isinstance(item, dict):
        url = str(item.get("url") or item.get("href") or item.get("path") or item.get("name") or "-")
        label = str(item.get("name") or item.get("filename") or _artifact_name_from_url(url) or f"artifact-{index}")
    else:
        url = str(item)
        label = _artifact_name_from_url(url) or f"artifact-{index}"
    artifact_type = _artifact_type(label)
    return {
        "label": label,
        "url": url,
        "type": artifact_type,
        "signed": "yes" if _is_presigned_url(url) else "no",
        "priority": "primary" if _is_primary_artifact(label) else "secondary",
    }


def _artifact_name_from_url(url: str) -> str:
    trimmed = url.split("?", 1)[0].rstrip("/")
    if not trimmed:
        return ""
    name = trimmed.rsplit("/", 1)[-1]
    return name or trimmed


def _artifact_type(name: str) -> str:
    lower = name.lower()
    if lower.endswith((".json",)):
        return "json"
    if lower.endswith((".csv", ".tsv", ".parquet")):
        return "table"
    if lower.endswith((".zip", ".tar", ".tar.gz", ".tgz")):
        return "archive"
    if lower.endswith((".png", ".jpg", ".jpeg", ".svg", ".pdf")):
        return "report"
    if lower.endswith((".pt", ".pth", ".bin", ".onnx", ".ckpt", ".npz", ".npy")):
        return "model"
    if lower.endswith((".log", ".txt")):
        return "log"
    return "artifact"


def _is_primary_artifact(name: str) -> bool:
    lower = name.lower()
    primary_markers = (
        "result",
        "summary",
        "metric",
        "report",
        "model",
        "final",
        "output",
    )
    return any(marker in lower for marker in primary_markers)


def _is_presigned_url(url: str) -> bool:
    lower = url.lower()
    return "x-amz-signature=" in lower or "x-amz-algorithm=" in lower


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
    return {
        "active": "fedctl submit ls --active",
        "completed": "fedctl submit ls --completed",
        "failed": "fedctl submit ls --failed",
        "cancelled": "fedctl submit ls --cancelled",
        "all": "fedctl submit ls --all",
    }.get(status_filter, "fedctl submit ls --active")


def _inventory_command() -> str:
    return "fedctl submit inventory"


def _palette_command(
    *,
    command_id: str,
    label: str,
    group: str,
    href: str,
    keywords: list[str],
) -> dict[str, Any]:
    return {
        "id": command_id,
        "label": label,
        "group": group,
        "href": href,
        "keywords": keywords,
    }


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "item"


def _help_command_anchor(name: str) -> str:
    return f"command-{_slug(name)}"


def _global_palette_commands(principal: Any) -> list[dict[str, Any]]:
    if principal is None:
        return []
    commands = [
        _palette_command(
            command_id="go-submissions",
            label="Go to Submissions",
            group="Navigation",
            href="/ui/submissions",
            keywords=["queue", "runs", "dashboard", "home"],
        ),
        _palette_command(
            command_id="go-help",
            label="Go to Help",
            group="Navigation",
            href="/ui/help",
            keywords=["docs", "guide", "reference", "commands"],
        ),
    ]
    if getattr(principal, "role", None) == "admin":
        commands.append(
            _palette_command(
                command_id="go-nodes",
                label="Go to Nodes",
                group="Navigation",
                href="/ui/nodes",
                keywords=["inventory", "cluster", "capacity", "operators"],
            )
        )
    return commands


def _submissions_palette_commands() -> list[dict[str, Any]]:
    return [
        _palette_command(
            command_id=f"view-submissions-{status_filter}",
            label=f"View {status_filter.capitalize()}",
            group="Submissions",
            href=f"/ui/submissions?status={status_filter}",
            keywords=["submissions", "filter", "queue", status_filter],
        )
        for status_filter in _STATUS_FILTERS
    ]


def _nodes_palette_commands() -> list[dict[str, Any]]:
    return [
        _palette_command(
            command_id="open-inventory",
            label="Open Inventory",
            group="Inventory",
            href="/ui/nodes",
            keywords=["nodes", "cluster", "capacity", "inventory"],
        ),
        _palette_command(
            command_id="clear-node-search",
            label="Clear node search",
            group="Inventory",
            href="/ui/nodes",
            keywords=["nodes", "search", "reset", "clear"],
        ),
    ]


def _help_palette_commands(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    palette_commands = [
        _palette_command(
            command_id="jump-quickstart",
            label="Jump to Quick start",
            group="Help",
            href="/ui/help#quickstart",
            keywords=["help", "guide", "start", "workflow"],
        ),
        _palette_command(
            command_id="jump-reference",
            label="Jump to Command reference",
            group="Help",
            href="/ui/help#reference",
            keywords=["help", "commands", "reference", "docs"],
        ),
    ]
    for command in commands:
        name = str(command.get("name") or "").strip()
        if not name:
            continue
        palette_commands.append(
            _palette_command(
                command_id=f"jump-{_help_command_anchor(name)}",
                label=f"Jump to {name}",
                group="Help",
                href=f"/ui/help#{_help_command_anchor(name)}",
                keywords=["help", "command", "reference", name],
            )
        )
    return palette_commands


def _submission_detail_href(
    submission_id: str,
    *,
    return_to: str,
    job: str,
    task: str,
    index: int,
    stderr: bool,
    fragment: str | None = None,
) -> str:
    params: dict[str, str] = {
        "return_to": return_to,
        "job": job,
        "index": str(index),
        "stderr": "true" if stderr else "false",
    }
    if task:
        params["task"] = task
    return urlunsplit(
        (
            "",
            "",
            f"/ui/submissions/{submission_id}",
            urlencode(params),
            fragment or "",
        )
    )


def _submission_detail_palette_commands(
    *,
    submission_id: str,
    return_to: str,
    job: str,
    task: str,
    index: int,
    stderr: bool,
) -> list[dict[str, Any]]:
    return [
        _palette_command(
            command_id="detail-overview",
            label="Show Overview",
            group="Submission",
            href=_submission_detail_href(
                submission_id,
                return_to=return_to,
                job=job,
                task=task,
                index=index,
                stderr=stderr,
                fragment="tab-overview",
            ),
            keywords=["submission", "overview", "summary"],
        ),
        _palette_command(
            command_id="detail-request",
            label="Show Request",
            group="Submission",
            href=_submission_detail_href(
                submission_id,
                return_to=return_to,
                job=job,
                task=task,
                index=index,
                stderr=stderr,
                fragment="tab-request",
            ),
            keywords=["submission", "request", "command", "options"],
        ),
        _palette_command(
            command_id="detail-logs",
            label="Show Logs",
            group="Submission",
            href=_submission_detail_href(
                submission_id,
                return_to=return_to,
                job=job,
                task=task,
                index=index,
                stderr=stderr,
                fragment="tab-logs",
            ),
            keywords=["submission", "logs", "stderr", "stdout"],
        ),
        _palette_command(
            command_id="detail-jobs",
            label="Show Jobs",
            group="Submission",
            href=_submission_detail_href(
                submission_id,
                return_to=return_to,
                job=job,
                task=task,
                index=index,
                stderr=stderr,
                fragment="tab-jobs",
            ),
            keywords=["submission", "jobs", "nomad", "mapping"],
        ),
        _palette_command(
            command_id="detail-back",
            label="Back to submissions",
            group="Submission",
            href=return_to,
            keywords=["submissions", "back", "list", "return"],
        ),
    ]


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
