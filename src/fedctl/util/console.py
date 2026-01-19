from __future__ import annotations

from typing import Iterable, Sequence

from rich.console import Console
from rich.table import Table

console = Console()


def print_table(title: str, columns: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    table = Table(title=title)
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*[str(cell) for cell in row])
    console.print(table)
