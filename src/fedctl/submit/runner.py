from __future__ import annotations

import atexit
import argparse
import hashlib
import json
import os
import signal
import tarfile
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import httpx
import logging

from fedctl.commands.run import resolve_run_experiment_name, run_run
from fedctl.deploy import naming
from fedctl.deploy.plan import parse_supernodes
from fedctl.constants import DEFAULT_FLWR_VERSION
from fedctl.nomad.client import NomadClient
from fedctl.project.flwr_inspect import inspect_flwr_project
from fedctl.submit.artifact import upload_artifact, ArtifactUploadError
from fedctl.util.console import console

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="fedctl submit runner")
    parser.add_argument("--path", default=".", help="Path to a Flower project")
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Expected project directory name inside the workspace",
    )
    parser.add_argument("--exp", dest="experiment")
    parser.add_argument(
        "--experiment-config",
        default=None,
        help="Path to a Flower run-config TOML, relative to the extracted project if needed",
    )
    parser.add_argument("--run-config-override", action="append")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--flwr-version", default=DEFAULT_FLWR_VERSION)
    parser.add_argument("--image")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--platform")
    parser.add_argument("--context")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--num-supernodes", type=int, default=2)
    parser.add_argument(
        "--no-auto-supernodes", action="store_true", help="Disable auto supernode count"
    )
    parser.add_argument("--supernodes", action="append")
    parser.add_argument("--net", action="append")
    parser.add_argument("--allow-oversubscribe", dest="allow_oversubscribe", action="store_true")
    parser.add_argument(
        "--no-allow-oversubscribe", dest="allow_oversubscribe", action="store_false"
    )
    parser.set_defaults(allow_oversubscribe=None)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--federation", default="remote-deployment")
    parser.add_argument("--no-stream", dest="stream", action="store_false")
    parser.add_argument("--no-destroy", dest="destroy", action="store_false")
    parser.set_defaults(destroy=True)
    args = parser.parse_args(argv)

    endpoint = os.environ.get("FEDCTL_ENDPOINT")
    namespace = os.environ.get("FEDCTL_NAMESPACE")
    profile = os.environ.get("FEDCTL_PROFILE")
    token = os.environ.get("NOMAD_TOKEN")
    submission_id = os.environ.get("SUBMIT_SUBMISSION_ID")
    submit_service_endpoint = os.environ.get("SUBMIT_SERVICE_ENDPOINT")
    submit_service_token = os.environ.get("SUBMIT_SERVICE_TOKEN")
    result_store = os.environ.get("FEDCTL_RESULT_STORE")
    if submission_id:
        os.environ["FEDCTL_SUBMISSION_ID"] = submission_id

    project_path = _resolve_project_path(Path(args.path), args.project_dir)
    project_info = inspect_flwr_project(project_path)
    effective_experiment = resolve_run_experiment_name(
        project_name=project_info.project_name,
        experiment=args.experiment,
    )
    effective_num_supernodes = _effective_num_supernodes(
        configured_num_supernodes=args.num_supernodes,
        supernodes=args.supernodes,
        auto_supernodes=not args.no_auto_supernodes,
        project_info=project_info,
    )
    _report_jobs(
        submission_id=submission_id,
        submit_service_endpoint=submit_service_endpoint,
        submit_service_token=submit_service_token,
        experiment=effective_experiment,
        num_supernodes=effective_num_supernodes,
        supernodes=args.supernodes,
    )
    uploader = _ResultUploader(
        submission_id=submission_id,
        submit_service_endpoint=submit_service_endpoint,
        submit_service_token=submit_service_token,
        result_store=result_store,
        experiment=effective_experiment,
        endpoint=endpoint,
        namespace=namespace,
        token=token,
    )
    if uploader.enabled:
        uploader.start()
        logger.info("result uploader started (store=%s, submission=%s)", result_store, submission_id)
    log_archiver = _LogArchiver(
        submission_id=submission_id,
        submit_service_endpoint=submit_service_endpoint,
        submit_service_token=submit_service_token,
        result_store=result_store,
        experiment=effective_experiment,
        num_supernodes=effective_num_supernodes,
        supernodes=args.supernodes,
        endpoint=endpoint,
        namespace=namespace,
        token=token,
    )
    if log_archiver.enabled:
        logger.info("log archiver enabled (final sweep only, submission=%s)", submission_id)
        log_archiver.start()

    cleanup = _once(
        _combine_pre_cleanup(
            uploader.final_sweep if uploader.enabled else None,
            log_archiver.final_sweep if log_archiver.enabled else None,
        )
    )
    if cleanup is not None:
        atexit.register(cleanup)

    try:
        with _shutdown_on_signal():
            return run_run(
                path=str(project_path),
                experiment_config=args.experiment_config,
                run_config_overrides=args.run_config_override,
                seed=args.seed,
                flwr_version=args.flwr_version,
                image=args.image,
                no_cache=args.no_cache,
                platform=args.platform,
                context=args.context,
                push=args.push,
                num_supernodes=effective_num_supernodes,
                auto_supernodes=not args.no_auto_supernodes,
                supernodes=args.supernodes,
                net=args.net,
                allow_oversubscribe=args.allow_oversubscribe,
                experiment=effective_experiment,
                timeout_seconds=args.timeout,
                federation=args.federation,
                stream=args.stream,
                profile=profile,
                endpoint=endpoint,
                namespace=namespace,
                token=token,
                pre_cleanup=cleanup,
                destroy=args.destroy,
            )
    finally:
        if uploader.enabled:
            uploader.stop()
        if log_archiver.enabled:
            log_archiver.stop()


def _effective_num_supernodes(
    *,
    configured_num_supernodes: int,
    supernodes: list[str] | None,
    auto_supernodes: bool,
    project_info: object,
) -> int:
    if supernodes or not auto_supernodes:
        return configured_num_supernodes
    inferred = getattr(project_info, "local_sim_num_supernodes", None)
    if isinstance(inferred, int) and inferred > 0:
        return inferred
    return configured_num_supernodes


def _resolve_project_path(path: Path, project_dir: str | None) -> Path:
    if project_dir:
        candidate = path.parent / project_dir
        if candidate.exists():
            return candidate

    if path.exists():
        if path.is_dir():
            resolved = _find_project_dir(path)
            return resolved if resolved else path
        return path.parent

    base = path.parent
    extracted = _extract_archives_to_temp(base)
    if extracted and extracted.exists():
        if project_dir:
            candidate = extracted / project_dir
            if candidate.exists():
                return candidate
        resolved = _find_project_dir(extracted)
        return resolved if resolved else extracted

    # Fall back to the first directory inside the artifact destination.
    if base.exists():
        resolved = _find_project_dir(base)
        if resolved:
            return resolved
    return path


def _extract_archives_to_temp(base: Path) -> Path | None:
    if not base.exists():
        return None
    archive = None
    for entry in base.iterdir():
        if entry.is_file() and entry.name.endswith((".tar.gz", ".tgz", ".tar")):
            archive = entry
            break
    if not archive:
        return None
    temp_dir = Path(tempfile.mkdtemp(prefix="fedctl-submit-"))
    try:
        with tarfile.open(archive) as tar:
            tar.extractall(path=temp_dir)
    except tarfile.TarError:
        return None

    # If the archive contains a single top-level dir, use it.
    entries = [p for p in temp_dir.iterdir() if p.is_dir()]
    if len(entries) == 1:
        return entries[0]
    return temp_dir


def _find_project_dir(base: Path) -> Path | None:
    pyproject = base / "pyproject.toml"
    if pyproject.exists():
        return base
    candidates = []
    for entry in base.iterdir():
        if entry.is_dir() and (entry / "pyproject.toml").exists():
            candidates.append(entry)
    if len(candidates) == 1:
        return candidates[0]
    return None


def _report_jobs(
    *,
    submission_id: str | None,
    submit_service_endpoint: str | None,
    submit_service_token: str | None,
    experiment: str | None,
    num_supernodes: int,
    supernodes: list[str] | None,
) -> None:
    if not submission_id or not submit_service_endpoint or not experiment:
        return
    jobs = _build_jobs_report(
        experiment=experiment,
        num_supernodes=num_supernodes,
        supernodes=supernodes,
    )
    if not jobs:
        return
    url = submit_service_endpoint.rstrip("/") + f"/v1/submissions/{submission_id}/jobs"
    headers = {}
    if submit_service_token:
        headers["Authorization"] = f"Bearer {submit_service_token}"
    try:
        response = httpx.post(url, json={"jobs": jobs}, headers=headers, timeout=10.0)
    except httpx.HTTPError as exc:
        logger.warning("submit-service job report failed: %s", exc)
        console.print(f"[yellow]Warning:[/yellow] Job mapping report failed: {exc}")
        return
    if response.status_code >= 400:
        logger.warning(
            "submit-service job report failed: status=%s body=%s",
            response.status_code,
            response.text[:200],
        )
        console.print(
            f"[yellow]Warning:[/yellow] Job mapping report failed: {response.status_code}"
        )
        return
    logger.info("submit-service job report ok: submission_id=%s", submission_id)
    console.print("[green]✓ Reported submission job mapping to submit service[/green]")


def _build_jobs_report(
    *, experiment: str, num_supernodes: int, supernodes: list[str] | None
) -> dict[str, object]:
    placements = _supernode_placements_for_report(
        num_supernodes=num_supernodes, supernodes=supernodes
    )
    tasks = [_supernode_task_name(p["device_type"], p["instance_idx"]) for p in placements]
    clientapps = [
        naming.job_superexec_clientapp(
            experiment, p["instance_idx"], p["device_type"]
        )
        for p in placements
    ]
    superlink_job = naming.job_superlink(experiment)
    supernodes_job = naming.job_supernodes(experiment)
    serverapp_job = naming.job_superexec_serverapp(experiment)
    return {
        "superlink": {
            "job_id": superlink_job,
            "task": superlink_job,
            "targets": [
                {
                    "index": 1,
                    "job_id": superlink_job,
                    "task": superlink_job,
                }
            ],
        },
        "supernodes": {
            "job_id": supernodes_job,
            "tasks": tasks,
            "targets": [
                {
                    "index": idx,
                    "job_id": supernodes_job,
                    "task": task,
                }
                for idx, task in enumerate(tasks, start=1)
            ],
        },
        "superexec_serverapp": {
            "job_id": serverapp_job,
            "task": serverapp_job,
            "targets": [
                {
                    "index": 1,
                    "job_id": serverapp_job,
                    "task": serverapp_job,
                }
            ],
        },
        "superexec_clientapps": {
            "job_ids": clientapps,
            "targets": [
                {
                    "index": idx,
                    "job_id": job_id,
                    "task": job_id,
                }
                for idx, job_id in enumerate(clientapps, start=1)
            ],
        },
    }


def _supernode_placements_for_report(
    *, num_supernodes: int, supernodes: list[str] | None
) -> list[dict[str, object]]:
    placements: list[dict[str, object]] = []
    if supernodes:
        counts = parse_supernodes(supernodes)
        for device_type, count in counts.items():
            for idx in range(1, count + 1):
                placements.append(
                    {"device_type": device_type, "instance_idx": idx}
                )
        return placements
    for idx in range(1, max(num_supernodes, 0) + 1):
        placements.append({"device_type": None, "instance_idx": idx})
    return placements


def _supernode_task_name(device_type: str | None, instance_idx: int) -> str:
    group_suffix = f"{device_type}-{instance_idx}" if device_type else str(instance_idx)
    return f"supernode-{group_suffix}"


def _combine_pre_cleanup(*hooks: Callable[[], None] | None) -> Callable[[], None] | None:
    active = [hook for hook in hooks if hook is not None]
    if not active:
        return None

    def _run() -> None:
        for hook in active:
            hook()

    return _run


def _once(hook: Callable[[], None] | None) -> Callable[[], None] | None:
    if hook is None:
        return None
    fired = False

    def _run() -> None:
        nonlocal fired
        if fired:
            return
        fired = True
        hook()

    return _run


@contextmanager
def _shutdown_on_signal():
    previous_handlers: dict[int, object] = {}

    def _raise_exit(signum, _frame) -> None:  # noqa: ANN001
        raise SystemExit(128 + signum)

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _raise_exit)
        yield
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


class _ResultUploader:
    def __init__(
        self,
        *,
        submission_id: str | None,
        submit_service_endpoint: str | None,
        submit_service_token: str | None,
        result_store: str | None,
        experiment: str | None,
        endpoint: str | None,
        namespace: str | None,
        token: str | None,
    ) -> None:
        self._submission_id = submission_id
        self._submit_service_endpoint = submit_service_endpoint
        self._submit_service_token = submit_service_token
        self._result_store = result_store
        self._experiment = experiment
        self._endpoint = endpoint
        self._namespace = namespace
        self._token = token
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._uploaded: set[str] = set()
        self._matched: set[str] = set()
        self._bundle_uploaded = False
        self._bundle_results = True

    @property
    def enabled(self) -> bool:
        return bool(self._submission_id and self._submit_service_endpoint and self._result_store and self._experiment)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        if self._bundle_results:
            logger.info("result uploader: mode=bundle (uploads once at final sweep)")
        else:
            logger.info("result uploader: mode=per-file (uploads as files appear)")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def final_sweep(self) -> None:
        try:
            logger.info("result uploader: final sweep started")
            self._check_and_upload(force=True)
            logger.info("result uploader: final sweep complete")
        except Exception as exc:
            logger.warning("final result sweep failed: %s", exc)

    def _run_loop(self) -> None:
        poll_interval = 10.0
        while not self._stop.is_set():
            try:
                self._check_and_upload()
            except Exception as exc:
                logger.warning("result uploader error: %s", exc)
            self._stop.wait(poll_interval)

    def _check_and_upload(self, *, force: bool = False) -> None:
        job_name = naming.job_superexec_serverapp(self._experiment or "experiment")
        alloc_id = _find_running_alloc(job_name, self._endpoint, self._namespace, self._token)
        if not alloc_id:
            logger.info("result uploader: no running alloc for %s", job_name)
            return
        logger.info("result uploader: scanning alloc %s", alloc_id)
        client = _nomad_client(self._endpoint, self._namespace, self._token)
        scanned = 0
        matched = 0
        try:
            for base in (".", "outputs", "local"):
                paths = _iter_files_recursive(client, alloc_id, base)
                logger.info("result uploader: base=%s files=%d", base, len(paths))
                scanned += len(paths)
                for path in paths:
                    logger.info("result uploader: found file %s", path)
                    if not _is_result_file(path):
                        continue
                    logger.info("result uploader: matched result file %s", path)
                    self._matched.add(path)
                    matched += 1
                    if self._bundle_results:
                        continue
                    key = path
                    if key in self._uploaded:
                        continue
                    content = client.alloc_fs_cat(alloc_id, path)
                    url = self._upload_bytes(os.path.basename(path), content)
                    if url:
                        logger.info("result uploader: uploaded %s -> %s", path, url)
                        self._uploaded.add(key)
                        self._report_result(url)
            if self._bundle_results and force:
                logger.info(
                    "result uploader: bundle requested (matched=%d scanned=%d)",
                    matched,
                    scanned,
                )
                self._upload_bundle(client, alloc_id)
        finally:
            client.close()

    def _upload_bytes(self, name: str, content: bytes) -> str | None:
        if not self._result_store:
            return None
        store = self._result_store.rstrip("/")
        if self._submission_id:
            store = f"{store}/results/{self._submission_id}"
        try:
            with tempfile.TemporaryDirectory(prefix="fedctl-results-") as tmp_dir:
                path = Path(tmp_dir) / name
                path.write_bytes(content)
                return upload_artifact(path, store)
        except (OSError, ArtifactUploadError) as exc:
            logger.warning("result upload failed: %s", exc)
            return None

    def _report_result(self, url: str) -> None:
        if not self._submit_service_endpoint or not self._submission_id:
            return
        headers = {}
        if self._submit_service_token:
            headers["Authorization"] = f"Bearer {self._submit_service_token}"
        payload = {
            "result_location": url,
            "artifacts": [url],
        }
        try:
            httpx.post(
                f"{self._submit_service_endpoint.rstrip('/')}/v1/submissions/{self._submission_id}/results",
                json=payload,
                headers=headers,
                timeout=10.0,
            )
        except httpx.HTTPError as exc:
            logger.warning("submit-service result report failed: %s", exc)
        else:
            logger.info("result uploader: reported %s to submit service", url)

    def _upload_bundle(self, client: NomadClient, alloc_id: str) -> None:
        if self._bundle_uploaded:
            logger.info("result uploader: bundle already uploaded; skipping")
            return
        if not self._matched:
            logger.info("result uploader: no matched results to bundle")
            return
        if not self._result_store:
            logger.info("result uploader: no result store configured for bundle upload")
            return
        bundle_name = _bundle_name(self._submission_id, self._experiment)
        logger.info("result uploader: bundling %d files into %s", len(self._matched), bundle_name)
        try:
            with tempfile.TemporaryDirectory(prefix="fedctl-results-bundle-") as tmp_dir:
                base_dir = Path(tmp_dir)
                for path in sorted(self._matched):
                    content = client.alloc_fs_cat(alloc_id, path)
                    dest = base_dir / Path(path)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(content)
                bundle_path = base_dir / bundle_name
                with tarfile.open(bundle_path, "w:gz") as tar:
                    for file_path in base_dir.rglob("*"):
                        if file_path == bundle_path or file_path.is_dir():
                            continue
                        tar.add(file_path, arcname=file_path.relative_to(base_dir))
                url = upload_artifact(bundle_path, self._result_store)
                self._bundle_uploaded = True
                logger.info("result uploader: uploaded bundle -> %s", url)
                self._report_result(url)
        except (OSError, ArtifactUploadError) as exc:
            logger.warning("result bundle upload failed: %s", exc)


class _LogArchiver:
    def __init__(
        self,
        *,
        submission_id: str | None,
        submit_service_endpoint: str | None,
        submit_service_token: str | None,
        result_store: str | None,
        experiment: str | None,
        num_supernodes: int,
        supernodes: list[str] | None,
        endpoint: str | None,
        namespace: str | None,
        token: str | None,
    ) -> None:
        self._submission_id = submission_id
        self._submit_service_endpoint = submit_service_endpoint
        self._submit_service_token = submit_service_token
        self._result_store = result_store
        self._experiment = experiment
        self._num_supernodes = num_supernodes
        self._supernodes = supernodes
        self._endpoint = endpoint
        self._namespace = namespace
        self._token = token
        self._lock = threading.Lock()
        self._last_uploaded_signature: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(
            self._submission_id
            and self._submit_service_endpoint
            and self._result_store
            and self._experiment
            and self._endpoint
        )

    def start(self) -> None:
        logger.info(
            "log archiver ready (final sweep only, submission=%s)",
            self._submission_id,
        )

    def stop(self) -> None:
        return

    def final_sweep(self) -> None:
        if not self.enabled:
            return
        self._archive_current(force=True)

    def _archive_current(self, *, force: bool) -> None:
        if not self.enabled:
            return
        with self._lock:
            entries = self._collect()
            if not entries:
                logger.info("log archiver: no logs captured")
                return
            signature = _log_archive_signature(entries)
            if not force and signature == self._last_uploaded_signature:
                logger.info("log archiver: no log changes detected")
                return
            manifest_location = self._upload_archive(entries)
            if manifest_location and self._report(manifest_location):
                self._last_uploaded_signature = signature

    def _report(self, manifest_location: str) -> bool:
        payload = {
            "logs_location": manifest_location,
        }
        headers: dict[str, str] = {}
        if self._submit_service_token:
            headers["Authorization"] = f"Bearer {self._submit_service_token}"
        url = (
            self._submit_service_endpoint.rstrip("/")
            + f"/v1/submissions/{self._submission_id}/logs"
        )
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=20.0)
            if resp.status_code >= 400:
                logger.warning(
                    "log archive report failed: status=%s body=%s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
            logger.info(
                "log archive report ok: submission_id=%s location=%s",
                self._submission_id,
                manifest_location,
            )
            return True
        except httpx.HTTPError as exc:
            logger.warning("log archive report failed: %s", exc)
            return False

    def _upload_archive(self, entries: list[dict[str, object]]) -> str | None:
        uploaded_entries: list[dict[str, object]] = []
        for entry in entries:
            uploaded_entries.append(self._upload_entry(entry))
        manifest = {
            "schema": "v1-external",
            "submission_id": self._submission_id,
            "experiment": self._experiment,
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "entries": uploaded_entries,
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8")
        return self._upload_bytes("manifest.json", manifest_bytes)

    def _upload_entry(self, entry: dict[str, object]) -> dict[str, object]:
        uploaded = {
            key: value
            for key, value in entry.items()
            if key != "content"
        }
        content = entry.get("content")
        if not isinstance(content, str):
            return uploaded
        filename = _archive_object_name(entry)
        url = self._upload_bytes(filename, content.encode("utf-8"))
        if url is None:
            uploaded.pop("content", None)
            uploaded["error"] = "archive upload failed"
            return uploaded
        uploaded["url"] = url
        uploaded["size_bytes"] = len(content.encode("utf-8"))
        return uploaded

    def _upload_bytes(self, name: str, content: bytes) -> str | None:
        if not self._result_store or not self._submission_id:
            return None
        store = self._result_store.rstrip("/")
        store = f"{store}/logs/{self._submission_id}"
        try:
            with tempfile.TemporaryDirectory(prefix="fedctl-log-archive-") as tmp_dir:
                relative = Path(name)
                if str(relative.parent) not in {"", "."}:
                    store = f"{store}/{relative.parent.as_posix()}"
                path = Path(tmp_dir) / relative.name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                return upload_artifact(
                    path,
                    store,
                    presign_endpoint=(
                        self._submit_service_endpoint.rstrip("/") + "/v1/presign"
                        if self._submit_service_endpoint
                        else None
                    ),
                    presign_token=self._submit_service_token,
                )
        except (OSError, ArtifactUploadError) as exc:
            logger.warning("log archive upload failed for %s: %s", name, exc)
            return None

    def _collect(self) -> list[dict[str, object]]:
        targets = self._targets()
        if not targets:
            return []
        client = _nomad_client(self._endpoint, self._namespace, self._token)
        entries: list[dict[str, object]] = []
        try:
            for target in targets:
                job_id = target["job_id"]
                task = target["task"]
                try:
                    allocs = client.job_allocations(job_id)
                except Exception as exc:
                    logger.info("log archiver: allocations unavailable job=%s err=%s", job_id, exc)
                    entries.extend(
                        _archive_error_entries(
                            target=target,
                            job_id=job_id,
                            error=f"allocations unavailable: {exc}",
                        )
                    )
                    continue
                alloc = _latest_alloc_for_task(allocs, task)
                if not alloc:
                    entries.extend(
                        _archive_error_entries(
                            target=target,
                            job_id=job_id,
                            error="no matching allocation found",
                        )
                    )
                    continue
                alloc_id = alloc.get("ID")
                if not isinstance(alloc_id, str):
                    entries.extend(
                        _archive_error_entries(
                            target=target,
                            job_id=job_id,
                            error="allocation ID missing",
                        )
                    )
                    continue
                for stderr in (False, True):
                    try:
                        log_text = client.alloc_logs(
                            alloc_id,
                            task,
                            stderr=stderr,
                            follow=False,
                        )
                    except Exception as exc:
                        logger.info(
                            "log archiver: alloc logs unavailable job=%s task=%s stderr=%s err=%s",
                            job_id,
                            task,
                            stderr,
                            exc,
                        )
                        entries.append(
                            _archive_log_entry(
                                target=target,
                                job_id=job_id,
                                stderr=stderr,
                                alloc_id=alloc_id,
                                error=f"alloc logs unavailable: {exc}",
                            )
                        )
                        continue
                    entries.append(
                        _archive_log_entry(
                            target=target,
                            job_id=job_id,
                            stderr=stderr,
                            alloc_id=alloc_id,
                            content=log_text,
                        )
                    )
        finally:
            client.close()
        return entries

    def _targets(self) -> list[dict[str, object]]:
        if not self._submission_id or not self._experiment:
            return []
        jobs = _build_jobs_report(
            experiment=self._experiment,
            num_supernodes=self._num_supernodes,
            supernodes=self._supernodes,
        )
        targets: list[dict[str, object]] = [
            {
                "job": "submit",
                "index": 1,
                "job_id": self._submission_id,
                "task": "submit",
            }
        ]
        for job_name in ("superlink", "supernodes", "superexec_serverapp", "superexec_clientapps"):
            info = jobs.get(job_name)
            if not isinstance(info, dict):
                continue
            raw_targets = info.get("targets")
            if not isinstance(raw_targets, list):
                continue
            for target in raw_targets:
                if not isinstance(target, dict):
                    continue
                job_id = target.get("job_id")
                task = target.get("task")
                index = target.get("index")
                if not isinstance(job_id, str) or not isinstance(task, str) or not isinstance(index, int):
                    continue
                targets.append(
                    {
                        "job": job_name,
                        "index": index,
                        "job_id": job_id,
                        "task": task,
                    }
                )
        return targets


def _nomad_client(
    endpoint: str | None,
    namespace: str | None,
    token: str | None,
) -> NomadClient:
    from fedctl.config.schema import EffectiveConfig

    if not endpoint:
        raise RuntimeError("Nomad endpoint not configured")
    cfg = EffectiveConfig(
        profile_name="submit-runner",
        endpoint=endpoint,
        namespace=namespace,
        nomad_token=token,
    )
    return NomadClient(cfg)


def _find_running_alloc(
    job_name: str,
    endpoint: str | None,
    namespace: str | None,
    token: str | None,
) -> str | None:
    client = _nomad_client(endpoint, namespace, token)
    try:
        allocs = client.job_allocations(job_name)
    except Exception:
        return None
    finally:
        client.close()
    if not isinstance(allocs, list):
        return None
    for alloc in allocs:
        if not isinstance(alloc, dict):
            continue
        if alloc.get("ClientStatus") != "running":
            continue
        alloc_id = alloc.get("ID")
        if isinstance(alloc_id, str):
            return alloc_id
    return None


def _latest_alloc(allocs: object) -> dict[str, object] | None:
    if not isinstance(allocs, list) or not allocs:
        return None
    candidates = [alloc for alloc in allocs if isinstance(alloc, dict)]
    if not candidates:
        return None
    candidates.sort(key=_alloc_sort_key, reverse=True)
    return candidates[0]


def _archive_error_entries(
    *,
    target: dict[str, object],
    job_id: str,
    error: str,
) -> list[dict[str, object]]:
    return [
        _archive_log_entry(target=target, job_id=job_id, stderr=False, error=error),
        _archive_log_entry(target=target, job_id=job_id, stderr=True, error=error),
    ]


def _archive_log_entry(
    *,
    target: dict[str, object],
    job_id: str,
    stderr: bool,
    alloc_id: str | None = None,
    content: str | None = None,
    error: str | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "job": target["job"],
        "index": target["index"],
        "job_id": job_id,
        "task": target["task"],
        "stderr": stderr,
    }
    if alloc_id is not None:
        entry["alloc_id"] = alloc_id
    if content is not None:
        entry["content"] = content
    if error is not None:
        entry["error"] = error
    return entry


def _latest_alloc_for_task(allocs: object, task: str) -> dict[str, object] | None:
    alloc = _latest_matching_alloc(allocs, task)
    if alloc is not None:
        return alloc
    return _latest_alloc(allocs)


def _latest_matching_alloc(allocs: object, task: str) -> dict[str, object] | None:
    if not isinstance(allocs, list) or not allocs:
        return None
    candidates = [
        alloc
        for alloc in allocs
        if isinstance(alloc, dict) and _alloc_has_task(alloc, task)
    ]
    if not candidates:
        return None
    candidates.sort(key=_alloc_sort_key, reverse=True)
    return candidates[0]


def _alloc_has_task(alloc: dict[str, object], task: str) -> bool:
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


def _alloc_sort_key(alloc: dict[str, object]) -> int:
    for key in ("ModifyTime", "CreateTime"):
        value = alloc.get(key)
        if isinstance(value, int):
            return value
    return 0


def _iter_files(entries: object) -> list[dict[str, object]]:
    if isinstance(entries, list):
        raw = entries
    elif isinstance(entries, dict):
        raw = entries.get("Entries")
    else:
        return []
    if not isinstance(raw, list):
        return []
    items: list[dict[str, object]] = []
    for entry in raw:
        if isinstance(entry, dict):
            items.append(entry)
    return items


def _iter_files_recursive(
    client: NomadClient,
    alloc_id: str,
    base: str,
    *,
    max_depth: int = 6,
) -> list[str]:
    paths: list[str] = []
    if not base:
        return paths
    queue = [(base, 0)]
    seen: set[str] = set()
    while queue:
        current, depth = queue.pop(0)
        if current in seen or depth > max_depth:
            continue
        seen.add(current)
        try:
            entries = client.alloc_fs_ls(alloc_id, current)
        except Exception:
            continue
        items = _iter_files(entries)
        logger.info("result uploader: ls %s -> %d entries", current, len(items))
        for entry in items:
            name = entry.get("Name")
            if not isinstance(name, str) or not name:
                continue
            full = name if current == "." else f"{current.rstrip('/')}/{name}"
            if entry.get("IsDir"):
                queue.append((full, depth + 1))
            else:
                paths.append(full)
    return paths


def _is_result_file(name: str) -> bool:
    lowered = name.lower()
    for ext in (".pt", ".pth", ".ckpt", ".bin", ".tar", ".zip", ".json", ".jsonl"):
        if lowered.endswith(ext):
            return True
    return False


def _bundle_name(submission_id: str | None, experiment: str | None) -> str:
    base = submission_id or experiment or "results"
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in base)
    return f"{safe}-results.tar.gz"


def _archive_object_name(entry: dict[str, object]) -> str:
    job = _safe_path_token(entry.get("job"), default="job")
    index = entry.get("index")
    index_token = str(index) if isinstance(index, int) and not isinstance(index, bool) else "1"
    task = _safe_path_token(entry.get("task"), default="task")
    stream = "stderr" if bool(entry.get("stderr")) else "stdout"
    return f"{job}/{index_token}-{task}.{stream}.log"


def _safe_path_token(value: object, *, default: str) -> str:
    if not isinstance(value, str) or not value:
        return default
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value)
    return cleaned.strip("-") or default


def _log_archive_signature(entries: list[dict[str, object]]) -> str:
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
