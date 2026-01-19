from __future__ import annotations

from pathlib import Path

from rich.console import Console

from fedctl.project.errors import ProjectError
from fedctl.project.flwr_inspect import format_project_info, inspect_flwr_project

console = Console()


def run_inspect(path: str | None = None) -> int:
    target = Path(path or ".")
    try:
        info = inspect_flwr_project(target)
    except ProjectError as exc:
        console.print(f"[red]✗ Project error:[/red] {exc}")
        return exc.exit_code

    console.print(format_project_info(info))
    return 0
