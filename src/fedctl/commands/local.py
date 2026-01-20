from __future__ import annotations

import json
import os
import shutil
import subprocess
import signal
import time
from pathlib import Path
from typing import Iterable, Optional, Tuple

from rich.console import Console

from fedctl.config.schema import EffectiveConfig
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError
from fedctl.util.console import print_table
from fedctl.config.merge import get_effective_config
from fedctl.config.io import load_config

console = Console()


def _cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "fedctl"
    return Path.home() / ".cache" / "fedctl"


def _local_root() -> Path:
    return _cache_dir() / "local"


def _state_path() -> Path:
    return _local_root() / "state.json"


def _logs_dir() -> Path:
    return _local_root() / "logs"


def _data_dir() -> Path:
    return _local_root() / "data"


def _write_state(state: dict) -> None:
    _local_root().mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps(state, indent=2))


def _read_state() -> dict:
    return json.loads(_state_path().read_text())


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _terminate_pid(pid: int, force: bool) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return

    deadline = time.time() + 5
    while time.time() < deadline:
        if not _is_pid_alive(pid):
            return
        time.sleep(0.2)

    if force and _is_pid_alive(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def _wait_for_ready(
    client: NomadClient, expected_nodes: int, timeout_seconds: int
) -> Optional[Tuple[str, int]]:
    deadline = time.time() + timeout_seconds
    last_error: Optional[str] = None

    while time.time() < deadline:
        try:
            leader = client.status_leader()
            nodes = client.nodes()
            print(nodes)
            count = len(nodes) if isinstance(nodes, list) else 0
            if leader and count >= expected_nodes:
                return leader, count
        except (NomadConnectionError, NomadHTTPError, NomadTLSError) as e:
            print(e)
            last_error = str(e)
        time.sleep(1)

    if last_error:
        console.print(f"[yellow]Last error while waiting:[/yellow] {last_error}")
    return None


def run_local_up(
    server_config: str,
    client_configs: Iterable[str],
    wipe: bool = False,
    wait_seconds: int = 30,
    expected_nodes: Optional[int] = None,
    endpoint: str = "http://127.0.0.1:4646",
) -> int:
    client_list = list(client_configs)
    if _state_path().exists():
        console.print(
            "[red]✗ Local harness already running.[/red] Run `fedctl local down` first."
        )
        return 1

    if shutil.which("nomad") is None:
        console.print("[red]✗ `nomad` binary not found in PATH.[/red]")
        return 2

    if wipe and _data_dir().exists():
        shutil.rmtree(_data_dir())

    _logs_dir().mkdir(parents=True, exist_ok=True)
    _data_dir().mkdir(parents=True, exist_ok=True)

    agents = []

    server_log = _logs_dir() / "server.log"
    try:
        logf = server_log.open("ab")
        proc = subprocess.Popen(
            ["nomad", "agent", f"-config={server_config}"],
            stdout=logf,
            stderr=logf,
            start_new_session=True,
        )
        logf.close()
    except Exception as e:
        console.print(f"[red]✗ Failed to start server agent:[/red] {e}")
        return 3

    agents.append(
        {
            "role": "server",
            "config": str(Path(server_config).resolve()),
            "pid": proc.pid,
            "log": str(server_log),
        }
    )

    for idx, cfg in enumerate(client_list, start=1):
        log_path = _logs_dir() / f"client{idx}.log"
        try:
            logf = log_path.open("ab")
            proc = subprocess.Popen(
                ["nomad", "agent", f"-config={cfg}"],
                stdout=logf,
                stderr=logf,
                start_new_session=True,
            )
            logf.close()
        except Exception as e:
            console.print(f"[red]✗ Failed to start client agent:[/red] {e}")
            for agent in agents:
                pid = agent.get("pid")
                if isinstance(pid, int):
                    _terminate_pid(pid, force=True)
            return 3

        agents.append(
            {
                "role": "client",
                "config": str(Path(cfg).resolve()),
                "pid": proc.pid,
                "log": str(log_path),
            }
        )

    state = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agents": agents,
    }
    _write_state(state)

    expected = expected_nodes if expected_nodes is not None else len(client_list)
    if expected == 0:
        expected = 1
        
    cfg = load_config()
    eff = get_effective_config(cfg=cfg)

    client = NomadClient(eff)
    try:
        ready = _wait_for_ready(client, expected, wait_seconds)
        if not ready:
            console.print("[red]✗ Local Nomad did not become ready in time.[/red]")
            run_local_down(wipe=wipe, force=True)
            return 4

        leader, count = ready
        console.print(f"[green]✓[/green] Local Nomad ready. Leader: {leader}")
        console.print(f"[green]✓[/green] Nodes visible: {count}")
        console.print(f"[green]i[/green] Logs: {_logs_dir()}")
        return 0
    finally:
        client.close()


def run_local_down(wipe: bool = False, force: bool = False) -> int:
    if not _state_path().exists():
        console.print("[yellow]![/yellow] No local harness state found.")
        return 1

    state = _read_state()
    for agent in state.get("agents", []):
        pid = agent.get("pid")
        if isinstance(pid, int):
            _terminate_pid(pid, force=force)

    try:
        _state_path().unlink()
    except OSError:
        pass

    if wipe:
        shutil.rmtree(_local_root(), ignore_errors=True)

    console.print("[green]✓[/green] Local harness stopped.")
    return 0


def run_local_status() -> int:
    if not _state_path().exists():
        console.print("[yellow]![/yellow] No local harness state found.")
        return 1

    state = _read_state()
    rows = []
    for agent in state.get("agents", []):
        pid = agent.get("pid")
        alive = _is_pid_alive(pid) if isinstance(pid, int) else False
        rows.append(
            [
                agent.get("role", ""),
                str(pid) if pid is not None else "",
                "yes" if alive else "no",
                agent.get("log", ""),
            ]
        )

    print_table("Local Nomad", ["Role", "PID", "Alive", "Log"], rows)
    return 0
