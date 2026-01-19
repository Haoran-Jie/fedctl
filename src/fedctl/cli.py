"""CLI entrypoint for fedctl."""

import typer

app = typer.Typer(add_completion=False, help="fedctl CLI")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Entry point for the CLI."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()
