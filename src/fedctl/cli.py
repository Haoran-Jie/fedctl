"""CLI entrypoint for fedctl."""

import typer
from rich import print
from rich.table import Table

from fedctl.config.io import load_config, load_raw_toml, save_raw_toml
from fedctl.config.merge import get_effective_config

app = typer.Typer(add_completion=False, help="fedctl CLI")

config_app = typer.Typer(help="Manage fedctl configuration")
profile_app = typer.Typer(help="Manage profiles")
app.add_typer(config_app, name="config")
app.add_typer(profile_app, name="profile")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Entry point for the CLI."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@config_app.command("show")
def config_show() -> None:
    cfg = load_config()
    eff = get_effective_config(cfg)
    print(f"[bold]Active profile:[/bold] {cfg.active_profile}")
    table = Table(title="Effective Config")
    table.add_column("Key")
    table.add_column("Value")
    table.add_row("endpoint", eff.endpoint)
    table.add_row("namespace", str(eff.namespace))
    table.add_row("access_mode", eff.access_mode)
    table.add_row("tailscale.subnet_cidr", str(eff.tailscale_subnet_cidr))
    table.add_row("tls_ca", str(eff.tls_ca))
    table.add_row("tls_skip_verify", str(eff.tls_skip_verify))
    table.add_row("nomad_token", "set" if eff.nomad_token else "missing")
    print(table)


@profile_app.command("ls")
def profile_ls() -> None:
    cfg = load_config()
    table = Table(title="Profiles")
    table.add_column("Name")
    table.add_column("Endpoint")
    table.add_column("Namespace")
    table.add_column("Access mode")
    for name, p in cfg.profiles.items():
        marker = "*" if name == cfg.active_profile else ""
        table.add_row(f"{name}{marker}", p.endpoint, str(p.namespace), p.access_mode)
    print(table)


@profile_app.command("use")
def profile_use(name: str) -> None:
    doc = load_raw_toml()
    profiles = doc.get("profiles", {})
    if name not in profiles:
        raise typer.BadParameter(f"Unknown profile '{name}'.")
    doc["active_profile"] = name
    save_raw_toml(doc)
    print(f"Active profile set to: [bold]{name}[/bold]")


@profile_app.command("add")
def profile_add(
    name: str,
    endpoint: str = typer.Option(..., "--endpoint"),
    namespace: str = typer.Option(None, "--namespace"),
    access_mode: str = typer.Option("lan-only", "--access-mode"),
    tls_ca: str = typer.Option(None, "--tls-ca"),
    tls_skip_verify: bool = typer.Option(False, "--tls-skip-verify"),
    tailscale_subnet_cidr: str = typer.Option(None, "--tailscale-subnet-cidr"),
) -> None:
    doc = load_raw_toml()
    if "profiles" not in doc:
        doc["profiles"] = {}
    if name in doc["profiles"]:
        raise typer.BadParameter(f"Profile '{name}' already exists.")

    p = {
        "endpoint": endpoint,
        "tls_skip_verify": tls_skip_verify,
        "access_mode": access_mode,
        "tailscale": {},
    }

    if namespace is not None:
        p["namespace"] = namespace
    if tls_ca is not None:
        p["tls_ca"] = tls_ca
    if tailscale_subnet_cidr is not None:
        p["tailscale"]["subnet_cidr"] = tailscale_subnet_cidr

    doc["profiles"][name] = p
    save_raw_toml(doc)
    print(f"Added profile: [bold]{name}[/bold]")


@profile_app.command("rm")
def profile_rm(name: str) -> None:
    doc = load_raw_toml()
    profiles = doc.get("profiles", {})
    if name not in profiles:
        raise typer.BadParameter(f"Unknown profile '{name}'.")
    if doc.get("active_profile") == name:
        raise typer.BadParameter(
            "Cannot remove the active profile. Switch first with `fedctl profile use`."
        )
    del doc["profiles"][name]
    save_raw_toml(doc)
    print(f"Removed profile: [bold]{name}[/bold]")
