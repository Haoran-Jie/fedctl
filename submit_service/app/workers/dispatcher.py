from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import threading
import time
from typing import Any

from ..config import SubmitConfig
from ..nomad_client import NomadClient, NomadError
from ..storage import Storage, utcnow


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


def _build_nomad_job(submission: dict[str, Any], cfg: SubmitConfig) -> dict[str, Any]:
    from fedctl.submit.render import SubmitJobSpec, render_submit_job

    priority = submission.get("priority") or cfg.default_priority
    spec = SubmitJobSpec(
        job_name=submission["id"],
        node_class=submission["node_class"],
        image=submission["submit_image"],
        artifact_url=submission["artifact_url"],
        namespace=submission.get("namespace") or cfg.nomad_namespace or "default",
        args=submission.get("args") or [],
        env=submission.get("env") or {},
        priority=priority,
        datacenter=cfg.datacenter,
        docker_socket=cfg.docker_socket,
    )
    return render_submit_job(spec)
