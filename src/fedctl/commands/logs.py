from __future__ import annotations

from rich.console import Console
from rich.text import Text

from fedctl.config.io import load_config
from fedctl.config.merge import get_effective_config
from fedctl.deploy import naming
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError

console = Console()


def run_logs(
    *,
    experiment: str | None,
    component: str = "all",
    stderr: bool = True,
) -> int:
    if not experiment:
        console.print("[red]✗ Missing experiment name.[/red]")
        return 1

    cfg = load_config()
    try:
        eff = get_effective_config(cfg)
    except ValueError as exc:
        console.print(f"[red]✗ Config error:[/red] {exc}")
        return 1

    components = _normalize_components(component)
    if not components:
        console.print(f"[red]✗ Unknown component:[/red] {component}")
        return 1

    client = NomadClient(eff)
    missing = False
    try:
        for comp in components:
            job_name = _job_name(comp, experiment)
            allocs = client.job_allocations(job_name)
            running = _running_allocs(allocs)
            if not running:
                console.print(f"[red]✗ No active allocations for {job_name}.[/red]")
                missing = True
                continue

            if comp == "superlink":
                running = running[:1]

            for alloc in running:
                alloc_id = _alloc_id(alloc)
                if not alloc_id:
                    continue
                task = _primary_task_name(alloc, comp, job_name)
                if not task:
                    console.print(
                        f"[red]✗ No task found for allocation {alloc_id}.[/red]"
                    )
                    missing = True
                    continue
                stream_label = "stderr" if stderr else "stdout"
                header = f"{job_name} alloc {alloc_id} task {task} ({stream_label})"
                console.print(f"[bold]{header}[/bold]")
                logs = client.alloc_logs(alloc_id, task, stderr=stderr)
                rendered = Text.from_ansi(logs)
                console.print(rendered, end="" if logs.endswith("\n") else "\n")
        return 1 if missing else 0

    except NomadTLSError as exc:
        console.print(f"[red]✗ TLS error:[/red] {exc}")
        return 2

    except NomadHTTPError as exc:
        console.print(f"[red]✗ HTTP error:[/red] {exc}")
        if getattr(exc, "status_code", None) == 403:
            console.print("[yellow]Hint:[/yellow] Token/ACL invalid or missing permissions.")
        return 3

    except NomadConnectionError as exc:
        console.print(f"[red]✗ Connection error:[/red] {exc}")
        console.print(
            "[yellow]Hint:[/yellow] Check endpoint reachability (LAN/Tailscale/SSH tunnel)."
        )
        return 4

    finally:
        client.close()


def _normalize_components(component: str) -> list[str]:
    value = component.strip().lower()
    if value in {"all", "both"}:
        return ["superlink", "supernodes"]
    if value in {"superlink", "supernodes"}:
        return [value]
    return []


def _job_name(component: str, experiment: str) -> str:
    if component == "superlink":
        return naming.job_superlink(experiment)
    return naming.job_supernodes(experiment)


def _running_allocs(allocs: object) -> list[dict[str, object]]:
    if not isinstance(allocs, list):
        return []
    candidates: list[dict[str, object]] = []
    for alloc in allocs:
        if not isinstance(alloc, dict):
            continue
        if alloc.get("ClientStatus") != "running":
            continue
        if alloc.get("DesiredStatus") != "run":
            continue
        candidates.append(alloc)
    candidates.sort(key=_alloc_sort_key, reverse=True)
    return candidates


def _alloc_sort_key(alloc: dict[str, object]) -> int:
    for key in ("ModifyTime", "CreateTime"):
        value = alloc.get(key)
        if isinstance(value, int):
            return value
    return 0


def _alloc_id(alloc: dict[str, object]) -> str | None:
    alloc_id = alloc.get("ID")
    return alloc_id if isinstance(alloc_id, str) else None


def _primary_task_name(
    alloc: dict[str, object],
    component: str,
    job_name: str,
) -> str | None:
    if component == "superlink":
        return job_name
    task_states = alloc.get("TaskStates")
    if not isinstance(task_states, dict):
        return None
    for name in task_states:
        if name != "netem":
            return name
    return None
