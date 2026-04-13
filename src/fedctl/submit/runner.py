from __future__ import annotations

import argparse
import os
import tarfile
import tempfile
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

import httpx
import logging

from fedctl.commands.run import run_run
from fedctl.deploy import naming
from fedctl.deploy.plan import parse_supernodes
from fedctl.constants import DEFAULT_FLWR_VERSION
from fedctl.nomad.client import NomadClient
from fedctl.submit.artifact import upload_artifact, ArtifactUploadError
from fedctl.util.console import console

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
_MAX_ARCHIVED_LOG_CHARS = 200_000


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
    parser.add_argument("--verbose", action="store_true")
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

    # _print_docker_info()
    project_path = _resolve_project_path(Path(args.path), args.project_dir)
    _report_jobs(
        submission_id=submission_id,
        submit_service_endpoint=submit_service_endpoint,
        submit_service_token=submit_service_token,
        experiment=args.experiment,
        num_supernodes=args.num_supernodes,
        supernodes=args.supernodes,
    )
    uploader = _ResultUploader(
        submission_id=submission_id,
        submit_service_endpoint=submit_service_endpoint,
        submit_service_token=submit_service_token,
        result_store=result_store,
        experiment=args.experiment,
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
        experiment=args.experiment,
        num_supernodes=args.num_supernodes,
        supernodes=args.supernodes,
        endpoint=endpoint,
        namespace=namespace,
        token=token,
    )
    if log_archiver.enabled:
        logger.info("log archiver enabled (submission=%s)", submission_id)

    exit_code = run_run(
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
        num_supernodes=args.num_supernodes,
        auto_supernodes=not args.no_auto_supernodes,
        supernodes=args.supernodes,
        net=args.net,
        allow_oversubscribe=args.allow_oversubscribe,
        experiment=args.experiment,
        timeout_seconds=args.timeout,
        federation=args.federation,
        stream=args.stream,
        verbose=args.verbose,
        profile=profile,
        endpoint=endpoint,
        namespace=namespace,
        token=token,
        pre_cleanup=_combine_pre_cleanup(
            uploader.final_sweep if uploader.enabled else None,
            log_archiver.final_sweep if log_archiver.enabled else None,
        ),
        destroy=args.destroy,
    )
    if uploader.enabled:
        uploader.stop()
    return exit_code


def _resolve_project_path(path: Path, project_dir: str | None) -> Path:
    # _print_tree(path.parent if path.parent != Path("") else Path("."), "workspace tree")

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
        # _print_tree(extracted, "extracted tree")
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


def _print_docker_info() -> None:
    docker_path = shutil.which("docker")
    console.print(f"[yellow]Debug:[/yellow] PATH={os.environ.get('PATH')}")
    if not docker_path:
        console.print("[yellow]Debug:[/yellow] docker not found on PATH")
        return
    console.print(f"[yellow]Debug:[/yellow] docker path: {docker_path}")


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


def _print_tree(base: Path, label: str, max_entries: int = 200) -> None:
    if not base.exists():
        console.print(f"[yellow]Debug:[/yellow] {label}: {base} does not exist")
        return
    lines = []
    for root, dirs, files in os.walk(base):
        dirs.sort()
        files.sort()
        rel_root = str(Path(root).relative_to(base)) or "."
        lines.append(f"{rel_root}/")
        for name in files:
            lines.append(f"  {name}")
        if len(lines) >= max_entries:
            lines.append("  ...")
            break
    console.print(f"[yellow]Debug:[/yellow] {label} {base}:\n" + "\n".join(lines))


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
        self._experiment = experiment
        self._num_supernodes = num_supernodes
        self._supernodes = supernodes
        self._endpoint = endpoint
        self._namespace = namespace
        self._token = token

    @property
    def enabled(self) -> bool:
        return bool(
            self._submission_id
            and self._submit_service_endpoint
            and self._experiment
            and self._endpoint
        )

    def final_sweep(self) -> None:
        if not self.enabled:
            return
        entries = self._collect()
        if not entries:
            logger.info("log archiver: no logs captured")
            return
        payload = {
            "logs_location": "inline://submit-service-db",
            "logs_archive": {
                "schema": "v1",
                "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "entries": entries,
            },
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
                return
            logger.info(
                "log archive report ok: submission_id=%s entries=%d",
                self._submission_id,
                len(entries),
            )
            console.print("[green]✓ Archived Nomad logs to submit service[/green]")
        except httpx.HTTPError as exc:
            logger.warning("log archive report failed: %s", exc)

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
                            content=_truncate_log_text(log_text),
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


def _truncate_log_text(text: str, *, max_chars: int = _MAX_ARCHIVED_LOG_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    keep = max_chars // 2
    return (
        text[:keep]
        + "\n\n...[log truncated for archive size]...\n\n"
        + text[-keep:]
    )


if __name__ == "__main__":
    raise SystemExit(main())
