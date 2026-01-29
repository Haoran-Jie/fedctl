from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import threading
import time
from typing import Any
import logging

from ..config import SubmitConfig
from ..nomad_client import NomadClient, NomadError
from ..storage import Storage, utcnow

logger = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    submitted: bool
    error: str | None = None


def dispatch_submission(
    storage: Storage,
    submission: dict[str, Any],
    cfg: SubmitConfig,
) -> DispatchResult:
    if not cfg.nomad_endpoint:
        storage.set_status(
            submission["id"],
            "failed",
            finished_at=utcnow(),
            error_message="SUBMIT_NOMAD_ENDPOINT not configured",
        )
        return DispatchResult(False, "SUBMIT_NOMAD_ENDPOINT not configured")

    try:
        job = _build_nomad_job(submission, cfg)
    except Exception as exc:
        storage.set_status(
            submission["id"],
            "failed",
            finished_at=utcnow(),
            error_message=f"Job render failed: {exc}",
        )
        return DispatchResult(False, str(exc))

    client = NomadClient(
        cfg.nomad_endpoint,
        token=cfg.nomad_token,
        namespace=submission.get("namespace") or cfg.nomad_namespace,
        tls_ca=cfg.nomad_tls_ca,
        tls_skip_verify=cfg.nomad_tls_skip_verify,
    )
    try:
        client.submit_job(job)
        storage.update_submission(
            submission["id"],
            {
                "status": "running",
                "started_at": utcnow().isoformat(),
                "nomad_job_id": submission["id"],
            },
        )
        return DispatchResult(True)
    except NomadError as exc:
        storage.set_status(
            submission["id"],
            "failed",
            finished_at=utcnow(),
            error_message=f"Nomad submit failed: {exc}",
        )
        return DispatchResult(False, str(exc))
    finally:
        client.close()


class Dispatcher:
    def __init__(self, storage: Storage, cfg: SubmitConfig) -> None:
        self._storage = storage
        self._cfg = cfg
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self._cfg.dispatch_interval)

    def run_once(self) -> None:
        queued = self._storage.list_submissions(limit=50)
        for submission in queued:
            if submission.get("status") != "queued":
                continue
            dispatch_submission(self._storage, submission, self._cfg)
        self._reconcile_running()

    def _reconcile_running(self) -> None:
        if not self._cfg.nomad_endpoint:
            return
        running = self._storage.list_submissions(limit=50)
        for submission in running:
            if submission.get("status") != "running":
                continue
            nomad_job_id = submission.get("nomad_job_id") or submission.get("id")
            if not nomad_job_id:
                continue
            client = NomadClient(
                self._cfg.nomad_endpoint,
                token=self._cfg.nomad_token,
                namespace=submission.get("namespace") or self._cfg.nomad_namespace,
                tls_ca=self._cfg.nomad_tls_ca,
                tls_skip_verify=self._cfg.nomad_tls_skip_verify,
            )
            try:
                allocs = client.job_allocations(nomad_job_id)
            except NomadError:
                continue
            finally:
                client.close()
            alloc = _latest_alloc(allocs)
            status = _alloc_status(alloc)
            if status == "complete":
                self._storage.set_status(
                    submission["id"],
                    "completed",
                    finished_at=utcnow(),
                )
            elif status in {"failed", "lost"}:
                self._storage.set_status(
                    submission["id"],
                    "failed",
                    finished_at=utcnow(),
                    error_message=f"Nomad allocation {status}",
                )


def _build_nomad_job(submission: dict[str, Any], cfg: SubmitConfig) -> dict[str, Any]:
    from fedctl.submit.render import SubmitJobSpec, render_submit_job

    priority = submission.get("priority") or cfg.default_priority
    env = dict(submission.get("env") or {})
    env["SUBMIT_SUBMISSION_ID"] = submission["id"]
    if cfg.service_endpoint:
        env["SUBMIT_SERVICE_ENDPOINT"] = cfg.service_endpoint
    report_token = _select_report_token(cfg.tokens)
    if cfg.service_endpoint:
        logger.info(
            "submit-service runner reporting configured: endpoint=%s token=%s",
            cfg.service_endpoint,
            "set" if report_token else "empty",
        )
    if report_token:
        env["SUBMIT_SERVICE_TOKEN"] = report_token
    spec = SubmitJobSpec(
        job_name=submission["id"],
        node_class=submission["node_class"],
        image=submission["submit_image"],
        artifact_url=submission["artifact_url"],
        namespace=submission.get("namespace") or cfg.nomad_namespace or "default",
        args=submission.get("args") or [],
        env=env,
        priority=priority,
        datacenter=cfg.datacenter,
        docker_socket=cfg.docker_socket,
    )
    return render_submit_job(spec)


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


def _alloc_status(alloc: dict[str, Any] | None) -> str | None:
    if not isinstance(alloc, dict):
        return None
    status = alloc.get("ClientStatus")
    return status if isinstance(status, str) else None


def _select_report_token(tokens: set[str]) -> str | None:
    if not tokens:
        return None
    return sorted(tokens)[0]
