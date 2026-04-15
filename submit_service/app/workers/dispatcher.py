from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import threading
import time
from typing import Any
import logging

from ..config import SubmitConfig
from ..config import load_repo_config_data
from ..nomad_client import NomadClient, NomadError
from ..nomad_inventory import NomadInventory
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
        self._inventory = NomadInventory(cfg)
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
        self._reconcile_running()
        queued = self._storage.list_dispatch_candidates(
            limit=50,
            statuses=["queued", "blocked"],
            default_priority=self._cfg.default_priority,
        )
        inventory_nodes, inventory_error = _inventory_snapshot(self._inventory)
        free_nodes = _node_free_resources(inventory_nodes) if inventory_nodes else []
        running = self._storage.list_submissions(limit=200, statuses=["running"])
        for submission in running:
            reserved, reason = _reserve_running_submission_capacity(
                submission,
                free_nodes,
                inventory_error,
                inventory_nodes,
            )
            if not reserved:
                logger.warning(
                    "active submission capacity reservation incomplete: submission=%s reason=%s",
                    submission.get("id"),
                    reason,
                )
        for submission in queued:
            status = submission.get("status")
            candidate_nodes = [dict(node) for node in free_nodes]
            ok, reason = _reserve_submission_capacity(
                submission,
                candidate_nodes,
                inventory_error,
            )
            if not ok:
                if status != "blocked" or submission.get("blocked_reason") != reason:
                    self._storage.update_submission(
                        submission["id"],
                        {
                            "status": "blocked",
                            "blocked_reason": reason,
                            "error_message": None,
                        },
                    )
                continue
            if status == "blocked":
                self._storage.update_submission(
                    submission["id"],
                    {"status": "queued", "blocked_reason": None, "error_message": None},
                )
            result = dispatch_submission(self._storage, submission, self._cfg)
            if result.submitted:
                free_nodes = candidate_nodes
        self._purge_completed_jobs()

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
                if not allocs:
                    try:
                        client.job(nomad_job_id)
                    except NomadError as exc:
                        if _nomad_error_status(exc) == 404:
                            self._storage.set_status(
                                submission["id"],
                                "failed",
                                finished_at=utcnow(),
                                error_message="Nomad job missing",
                            )
                    continue
            except NomadError as exc:
                if _nomad_error_status(exc) == 404:
                    self._storage.set_status(
                        submission["id"],
                        "failed",
                        finished_at=utcnow(),
                        error_message="Nomad job missing",
                    )
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

    def _purge_completed_jobs(self) -> None:
        delay_s = max(0, int(self._cfg.autopurge_completed_after_s))
        if delay_s <= 0 or not self._cfg.nomad_endpoint:
            return
        now = utcnow()
        completed = self._storage.list_submissions(limit=200, statuses=["completed"])
        for submission in completed:
            nomad_job_id = submission.get("nomad_job_id")
            if not isinstance(nomad_job_id, str) or not nomad_job_id:
                continue
            finished_at = _parse_dt(submission.get("finished_at"))
            if finished_at is None:
                continue
            age_s = (now - finished_at).total_seconds()
            if age_s < delay_s:
                continue
            client = NomadClient(
                self._cfg.nomad_endpoint,
                token=self._cfg.nomad_token,
                namespace=submission.get("namespace") or self._cfg.nomad_namespace,
                tls_ca=self._cfg.nomad_tls_ca,
                tls_skip_verify=self._cfg.nomad_tls_skip_verify,
            )
            try:
                client.stop_job(nomad_job_id, purge=True)
            except NomadError as exc:
                logger.warning(
                    "completed job purge failed: submission=%s job=%s err=%s",
                    submission.get("id"),
                    nomad_job_id,
                    exc,
                )
                continue
            finally:
                client.close()
            self._storage.update_submission(
                submission["id"],
                {"nomad_job_id": None},
            )
            logger.info(
                "purged completed submission job: submission=%s job=%s",
                submission.get("id"),
                nomad_job_id,
            )


def _build_nomad_job(submission: dict[str, Any], cfg: SubmitConfig) -> dict[str, Any]:
    from fedctl.submit.render import SubmitJobSpec, render_submit_job

    priority = submission.get("priority") or cfg.default_priority
    env = dict(submission.get("env") or {})
    env["SUBMIT_SUBMISSION_ID"] = submission["id"]
    if cfg.service_endpoint:
        env["SUBMIT_SERVICE_ENDPOINT"] = cfg.service_endpoint
    report_token = _select_report_token(cfg)
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


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _nomad_error_status(exc: NomadError) -> int | None:
    message = str(exc)
    prefix = "Nomad error "
    if not message.startswith(prefix):
        return None
    status_text, _, _ = message[len(prefix) :].partition(":")
    try:
        return int(status_text)
    except ValueError:
        return None


def _select_report_token(cfg: SubmitConfig) -> str | None:
    admin_tokens = [
        token
        for token, identity in cfg.token_identities.items()
        if identity.role == "admin"
    ]
    if admin_tokens:
        return sorted(admin_tokens)[0]
    if cfg.tokens:
        return sorted(cfg.tokens)[0]
    return None


def _inventory_snapshot(
    inventory: NomadInventory,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        nodes = inventory.list_nodes(include_allocs=True)
        return nodes, None
    except Exception as exc:
        logger.warning("inventory fetch failed: %s", exc)
        return None, f"inventory unavailable: {exc}"


def _capacity_allows(
    submission: dict[str, Any],
    free_nodes: list[dict[str, Any]],
    inventory_error: str | None,
) -> tuple[bool, str | None]:
    candidate_nodes = [dict(node) for node in free_nodes]
    return _reserve_submission_capacity(submission, candidate_nodes, inventory_error)


def _reserve_running_submission_capacity(
    submission: dict[str, Any],
    free_nodes: list[dict[str, Any]],
    inventory_error: str | None,
    inventory_nodes: list[dict[str, Any]] | None,
) -> tuple[bool, str | None]:
    if _submission_uses_strict_queue_reservation(submission):
        return _reserve_submission_capacity(submission, free_nodes, inventory_error)
    pending_requirements = _pending_soft_submission_requirements(submission, inventory_nodes)
    if not pending_requirements:
        return True, None
    return _reserve_requirements(pending_requirements, free_nodes, inventory_error)


def _reserve_submission_capacity(
    submission: dict[str, Any],
    free_nodes: list[dict[str, Any]],
    inventory_error: str | None,
) -> tuple[bool, str | None]:
    return _reserve_requirements(_submission_requirements(submission), free_nodes, inventory_error)


def _reserve_requirements(
    requirements: list[dict[str, Any]],
    free_nodes: list[dict[str, Any]],
    inventory_error: str | None,
) -> tuple[bool, str | None]:
    if inventory_error:
        return False, inventory_error
    reasons: list[str] = []
    for req in requirements:
        ok, reason = _check_requirement(free_nodes, req)
        if not ok:
            if reason:
                reasons.append(reason)

    if reasons:
        return False, "; ".join(reasons)
    return True, None


def _submission_requirements(submission: dict[str, Any]) -> list[dict[str, Any]]:
    args = submission.get("args") or []
    if not isinstance(args, list):
        args = []
    parsed = _parse_runner_args(args)
    allow_oversubscribe = parsed.get("allow_oversubscribe")
    if allow_oversubscribe is None:
        allow_oversubscribe = _repo_allow_oversubscribe_default()

    supernodes = parsed.get("supernodes")
    num_supernodes = parsed.get("num_supernodes") or 0
    total_supernodes = (
        sum(supernodes.values()) if isinstance(supernodes, dict) else int(num_supernodes)
    )
    if total_supernodes <= 0:
        total_supernodes = 0

    supernode_resources = _repo_resource_overrides("supernode")
    default_supernode_res = supernode_resources.get("default", {"cpu": 500, "mem": 512})
    clientapp_resources = _repo_resource_overrides("superexec_clientapp")
    default_clientapp_res = clientapp_resources.get("default", {"cpu": 1000, "mem": 1024})
    superlink_res = _repo_default_resource("superlink", cpu=500, mem=256)
    serverapp_res = _repo_default_resource("superexec_serverapp", cpu=1000, mem=1024)

    requirements: list[dict[str, Any]] = []
    if isinstance(supernodes, dict) and supernodes:
        for device_type, count in supernodes.items():
            supernode_res = supernode_resources.get(device_type, default_supernode_res)
            clientapp_res = clientapp_resources.get(device_type, default_clientapp_res)
            requirements.append(
                {
                    "name": f"compute-node:{device_type}",
                    "node_class": "node",
                    "device_type": device_type,
                    "cpu": supernode_res.get("cpu", 500) + clientapp_res.get("cpu", 1000),
                    "mem": supernode_res.get("mem", 512) + clientapp_res.get("mem", 1024),
                    "count": count,
                    "strict": not allow_oversubscribe,
                }
            )
    elif total_supernodes > 0:
        supernode_res = default_supernode_res
        clientapp_res = default_clientapp_res
        requirements.append(
            {
                "name": "compute-node",
                "node_class": "node",
                "device_type": None,
                "cpu": supernode_res.get("cpu", 500) + clientapp_res.get("cpu", 1000),
                "mem": supernode_res.get("mem", 512) + clientapp_res.get("mem", 1024),
                "count": total_supernodes,
                "strict": not allow_oversubscribe,
            }
        )

    requirements.append(
        {
            "name": "superlink",
            "node_class": "link",
            "device_type": None,
            "cpu": superlink_res["cpu"],
            "mem": superlink_res["mem"],
            "count": 1,
            "strict": False,
        }
    )
    requirements.append(
        {
            "name": "superexec-serverapp",
            "node_class": "link",
            "device_type": None,
            "cpu": serverapp_res["cpu"],
            "mem": serverapp_res["mem"],
            "count": 1,
            "strict": False,
        }
    )
    requirements.append(
        {
            "name": "submit-runner",
            "node_class": "submit",
            "device_type": None,
            "cpu": 1000,
            "mem": 1024,
            "count": 1,
            "strict": False,
        }
    )
    return requirements


def _submission_uses_strict_queue_reservation(submission: dict[str, Any]) -> bool:
    args = submission.get("args") or []
    if not isinstance(args, list):
        args = []
    parsed = _parse_runner_args(args)
    allow_oversubscribe = parsed.get("allow_oversubscribe")
    if allow_oversubscribe is None:
        allow_oversubscribe = _repo_allow_oversubscribe_default()
    return not bool(allow_oversubscribe)


def _pending_soft_submission_requirements(
    submission: dict[str, Any],
    inventory_nodes: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not inventory_nodes:
        return _submission_requirements(submission)

    visible_job_ids = _visible_running_job_ids(inventory_nodes)
    jobs_by_group = _submission_job_ids_by_group(submission)
    submission_id = submission.get("id")
    requirements = _submission_requirements(submission)
    pending: list[dict[str, Any]] = []
    for req in requirements:
        if _requirement_is_visible(
            requirement=req,
            submission_id=submission_id if isinstance(submission_id, str) else None,
            jobs_by_group=jobs_by_group,
            visible_job_ids=visible_job_ids,
        ):
            continue
        pending.append(req)
    return pending


def _requirement_is_visible(
    *,
    requirement: dict[str, Any],
    submission_id: str | None,
    jobs_by_group: dict[str, set[str]],
    visible_job_ids: set[str],
) -> bool:
    name = str(requirement.get("name") or "")
    if name == "submit-runner":
        return bool(submission_id) and submission_id in visible_job_ids
    if name.startswith("compute-node"):
        return _group_jobs_visible(jobs_by_group, "supernodes", visible_job_ids) and _group_jobs_visible(
            jobs_by_group,
            "superexec_clientapps",
            visible_job_ids,
        )
    if name == "superlink":
        return _group_jobs_visible(jobs_by_group, "superlink", visible_job_ids)
    if name == "superexec-serverapp":
        return _group_jobs_visible(jobs_by_group, "superexec_serverapp", visible_job_ids)
    return False


def _group_jobs_visible(
    jobs_by_group: dict[str, set[str]],
    group: str,
    visible_job_ids: set[str],
) -> bool:
    job_ids = jobs_by_group.get(group, set())
    return bool(job_ids) and job_ids.issubset(visible_job_ids)


def _submission_job_ids_by_group(submission: dict[str, Any]) -> dict[str, set[str]]:
    jobs = submission.get("jobs")
    if not isinstance(jobs, dict):
        return {}
    result: dict[str, set[str]] = {}
    for group, payload in jobs.items():
        if not isinstance(group, str):
            continue
        job_ids = _job_ids_from_payload(payload)
        if job_ids:
            result[group] = job_ids
    return result


def _job_ids_from_payload(payload: object) -> set[str]:
    result: set[str] = set()
    if isinstance(payload, dict):
        job_id = payload.get("job_id")
        if isinstance(job_id, str) and job_id:
            result.add(job_id)
        targets = payload.get("targets")
        if isinstance(targets, list):
            for target in targets:
                if not isinstance(target, dict):
                    continue
                target_job_id = target.get("job_id")
                if isinstance(target_job_id, str) and target_job_id:
                    result.add(target_job_id)
    return result


def _visible_running_job_ids(inventory_nodes: list[dict[str, Any]]) -> set[str]:
    visible: set[str] = set()
    for node in inventory_nodes:
        allocations = node.get("allocations")
        if not isinstance(allocations, dict):
            continue
        running_jobs = allocations.get("running_jobs")
        if not isinstance(running_jobs, list):
            continue
        for job_id in running_jobs:
            if isinstance(job_id, str) and job_id:
                visible.add(job_id)
    return visible


def _check_requirement(
    nodes: list[dict[str, Any]],
    req: dict[str, Any],
) -> tuple[bool, str | None]:
    candidates = _filter_nodes(
        nodes,
        node_class=req["node_class"],
        device_type=req.get("device_type"),
    )
    count = int(req.get("count") or 0)
    if count <= 0:
        return True, None
    if not candidates:
        return False, f"{req['name']}: no matching nodes"

    cpu = int(req.get("cpu") or 0)
    mem = int(req.get("mem") or 0)
    strict = bool(req.get("strict"))

    if strict:
        ok = _reserve_strict(candidates, cpu=cpu, mem=mem, count=count)
        if not ok:
            return (
                False,
                f"{req['name']}: need {count}, have {len(_eligible_nodes(candidates, cpu, mem))}",
            )
        return True, None

    aggregate_cpu, aggregate_mem, has_totals = _aggregate_free(candidates)
    if not has_totals:
        return True, None
    if aggregate_cpu < cpu * count:
        return (
            False,
            f"{req['name']}: need cpu {cpu*count}, available {aggregate_cpu}",
        )
    if aggregate_mem < mem * count:
        return (
            False,
            f"{req['name']}: need mem {mem*count}, available {aggregate_mem}",
        )
    ok = _reserve_soft(candidates, cpu=cpu, mem=mem, count=count)
    if not ok:
        return (
            False,
            f"{req['name']}: insufficient per-node capacity",
        )
    return True, None


def _filter_nodes(
    nodes: list[dict[str, Any]],
    *,
    node_class: str,
    device_type: str | None,
) -> list[dict[str, Any]]:
    result = []
    for node in nodes:
        if node.get("status") != "ready":
            continue
        if node.get("node_class") != node_class:
            continue
        if device_type is not None and node.get("device_type") != device_type:
            continue
        result.append(node)
    return result


def _node_free_resources(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for node in nodes:
        resources = node.get("resources") if isinstance(node.get("resources"), dict) else {}
        total_cpu = resources.get("total_cpu")
        total_mem = resources.get("total_mem")
        used_cpu = resources.get("used_cpu") or 0
        used_mem = resources.get("used_mem") or 0
        free_cpu = None if total_cpu is None else max(int(total_cpu) - int(used_cpu), 0)
        free_mem = None if total_mem is None else max(int(total_mem) - int(used_mem), 0)
        result.append({**node, "free_cpu": free_cpu, "free_mem": free_mem})
    return result


def _eligible_nodes(
    nodes: list[dict[str, Any]],
    cpu: int,
    mem: int,
) -> list[dict[str, Any]]:
    return [
        n
        for n in nodes
        if _has_capacity(n.get("free_cpu"), n.get("free_mem"), cpu, mem)
    ]


def _reserve_strict(
    nodes: list[dict[str, Any]],
    *,
    cpu: int,
    mem: int,
    count: int,
) -> bool:
    candidates = sorted(
        _eligible_nodes(nodes, cpu, mem),
        key=_free_sort_key,
        reverse=True,
    )
    if len(candidates) < count:
        return False
    for idx in range(count):
        node = candidates[idx]
        _reserve_node_exclusive(node)
    return True


def _reserve_soft(
    nodes: list[dict[str, Any]],
    *,
    cpu: int,
    mem: int,
    count: int,
) -> bool:
    if count <= 0:
        return True
    for _ in range(count):
        candidates = [
            n for n in nodes if _has_capacity(n.get("free_cpu"), n.get("free_mem"), cpu, mem)
        ]
        if not candidates:
            return False
        candidates.sort(key=_free_sort_key, reverse=True)
        node = candidates[0]
        _decrement_node(node, cpu, mem)
    return True


def _decrement_node(node: dict[str, Any], cpu: int, mem: int) -> None:
    free_cpu = node.get("free_cpu")
    free_mem = node.get("free_mem")
    if free_cpu is not None:
        node["free_cpu"] = max(int(free_cpu) - cpu, 0)
    if free_mem is not None:
        node["free_mem"] = max(int(free_mem) - mem, 0)


def _reserve_node_exclusive(node: dict[str, Any]) -> None:
    node["free_cpu"] = 0
    node["free_mem"] = 0


def _free_sort_key(node: dict[str, Any]) -> tuple[int, int]:
    free_cpu = node.get("free_cpu")
    free_mem = node.get("free_mem")
    return (int(free_cpu) if free_cpu is not None else -1, int(free_mem) if free_mem is not None else -1)


def _has_capacity(
    free_cpu: int | None,
    free_mem: int | None,
    cpu: int,
    mem: int,
) -> bool:
    if free_cpu is not None and free_cpu < cpu:
        return False
    if free_mem is not None and free_mem < mem:
        return False
    return True


def _aggregate_free(
    nodes: list[dict[str, Any]],
) -> tuple[int, int, bool]:
    total_cpu = 0
    total_mem = 0
    has_totals = False
    for node in nodes:
        free_cpu = node.get("free_cpu")
        free_mem = node.get("free_mem")
        if free_cpu is not None:
            total_cpu += int(free_cpu)
            has_totals = True
        if free_mem is not None:
            total_mem += int(free_mem)
            has_totals = True
    return total_cpu, total_mem, has_totals


def _parse_runner_args(args: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {
        "num_supernodes": None,
        "supernodes": None,
        "allow_oversubscribe": None,
    }
    idx = 0
    supernodes_values: list[str] = []
    while idx < len(args):
        arg = args[idx]
        if arg == "--num-supernodes" and idx + 1 < len(args):
            parsed["num_supernodes"] = _parse_int(args[idx + 1])
            idx += 2
            continue
        if arg == "--supernodes" and idx + 1 < len(args):
            supernodes_values.append(args[idx + 1])
            idx += 2
            continue
        if arg == "--allow-oversubscribe":
            parsed["allow_oversubscribe"] = True
            idx += 1
            continue
        if arg == "--no-allow-oversubscribe":
            parsed["allow_oversubscribe"] = False
            idx += 1
            continue
        idx += 1

    if supernodes_values:
        parsed["supernodes"] = _parse_supernodes(supernodes_values)
    return parsed


def _parse_supernodes(values: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for raw in values:
        parts = [p for p in raw.split(",") if p]
        for part in parts:
            if "=" not in part:
                continue
            key, val = part.split("=", 1)
            key = key.strip()
            if not key:
                continue
            count = _parse_int(val)
            if count is None or count < 0:
                continue
            result[key] = result.get(key, 0) + count
    return result


def _parse_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _repo_resource_overrides(name: str) -> dict[str, dict[str, int]]:
    data = load_repo_config_data()
    deploy = data.get("deploy", {}) if isinstance(data.get("deploy"), dict) else {}
    resources = (
        deploy.get("resources", {})
        if isinstance(deploy.get("resources"), dict)
        else {}
    )
    raw = resources.get(name, {})
    cleaned: dict[str, dict[str, int]] = {}

    if isinstance(raw, dict):
        top_level_cpu = _parse_int(raw.get("cpu"))
        top_level_mem = _parse_int(raw.get("mem"))
        if top_level_cpu is not None or top_level_mem is not None:
            entry: dict[str, int] = {}
            if top_level_cpu is not None:
                entry["cpu"] = top_level_cpu
            if top_level_mem is not None:
                entry["mem"] = top_level_mem
            if entry:
                cleaned["default"] = entry

    if not isinstance(raw, dict):
        return cleaned

    for key, val in raw.items():
        if not isinstance(val, dict):
            continue
        cpu = _parse_int(val.get("cpu"))
        mem = _parse_int(val.get("mem"))
        entry: dict[str, int] = {}
        if cpu is not None:
            entry["cpu"] = cpu
        if mem is not None:
            entry["mem"] = mem
        if entry:
            cleaned[str(key)] = entry
    return cleaned


def _repo_default_resource(name: str, *, cpu: int, mem: int) -> dict[str, int]:
    overrides = _repo_resource_overrides(name)
    default_entry = overrides.get("default", {})
    return {
        "cpu": int(default_entry.get("cpu", cpu)),
        "mem": int(default_entry.get("mem", mem)),
    }


def _repo_allow_oversubscribe_default() -> bool:
    data = load_repo_config_data()
    deploy = data.get("deploy", {}) if isinstance(data.get("deploy"), dict) else {}
    placement = (
        deploy.get("placement", {})
        if isinstance(deploy.get("placement"), dict)
        else {}
    )
    value = placement.get("allow_oversubscribe")
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False
