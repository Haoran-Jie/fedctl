from __future__ import annotations

import os
from typing import Iterable, Sequence

from rich.console import Console
from rich.table import Table


def _is_truthy_env(name: str) -> bool:
    value = os.environ.get(name)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _force_color() -> bool:
    override = os.environ.get("FEDCTL_FORCE_COLOR")
    if override is not None:
        return override.strip().lower() in {"1", "true", "yes", "on"}
    cli_force = os.environ.get("CLICOLOR_FORCE")
    if cli_force is not None:
        return cli_force.strip() not in {"0", ""}
    return True


def _no_color() -> bool:
    return _is_truthy_env("FEDCTL_NO_COLOR") or "NO_COLOR" in os.environ


console = Console(force_terminal=_force_color(), no_color=_no_color())


def print_table(title: str, columns: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    table = Table(title=title)
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*[str(cell) for cell in row])
    console.print(table)
