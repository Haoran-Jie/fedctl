"""Generic Flower ServerApp that dispatches by method."""

from __future__ import annotations

from flwr.app import Context
from flwr.serverapp import Grid, ServerApp

from fedctl_research.config import get_method_name
from fedctl_research.methods.registry import resolve_method

app = ServerApp()


@app.main()
def main(grid: Grid, context: Context) -> None:
    method = resolve_method(get_method_name(context.run_config))
    method.run_server(grid, context)

