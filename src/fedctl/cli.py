"""CLI entrypoint for fedctl."""

import typer
from rich import print
from rich.table import Table

from fedctl.commands.deploy import run_deploy
from fedctl.commands.discover import run_discover
from fedctl.commands.doctor import run_doctor
from fedctl.commands.inspect import run_inspect
from fedctl.commands.local import run_local_down, run_local_status, run_local_up
from fedctl.commands.ping import run_ping
from fedctl.config.io import load_config, load_raw_toml, save_raw_toml
from fedctl.config.merge import get_effective_config

app = typer.Typer(add_completion=False, help="fedctl CLI")

config_app = typer.Typer(help="Manage fedctl configuration")
profile_app = typer.Typer(help="Manage profiles")
local_app = typer.Typer(help="Local Nomad harness")
app.add_typer(config_app, name="config")
app.add_typer(profile_app, name="profile")
app.add_typer(local_app, name="local")


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


@app.command()
def doctor(
    profile: str = typer.Option(None, "--profile"),
    endpoint: str = typer.Option(None, "--endpoint"),
    namespace: str = typer.Option(None, "--namespace"),
    token: str = typer.Option(None, "--token"),
    tls_ca: str = typer.Option(None, "--tls-ca"),
    tls_skip_verify: bool = typer.Option(None, "--tls-skip-verify"),
) -> None:
    """Check connectivity/auth/TLS to Nomad."""
    raise SystemExit(
        run_doctor(
            profile=profile,
            endpoint=endpoint,
            namespace=namespace,
            token=token,
            tls_ca=tls_ca,
            tls_skip_verify=tls_skip_verify,
        )
    )


@app.command()
def ping(
    profile: str = typer.Option(None, "--profile"),
    endpoint: str = typer.Option(None, "--endpoint"),
    namespace: str = typer.Option(None, "--namespace"),
    token: str = typer.Option(None, "--token"),
    tls_ca: str = typer.Option(None, "--tls-ca"),
    tls_skip_verify: bool = typer.Option(None, "--tls-skip-verify"),
) -> None:
    """Quick connectivity check to Nomad (/v1/status/leader)."""
    raise SystemExit(
        run_ping(
            profile=profile,
            endpoint=endpoint,
            namespace=namespace,
            token=token,
            tls_ca=tls_ca,
            tls_skip_verify=tls_skip_verify,
        )
    )


@app.command()
def discover(
    profile: str = typer.Option(None, "--profile"),
    endpoint: str = typer.Option(None, "--endpoint"),
    namespace: str = typer.Option(None, "--namespace"),
    token: str = typer.Option(None, "--token"),
    tls_ca: str = typer.Option(None, "--tls-ca"),
    tls_skip_verify: bool = typer.Option(None, "--tls-skip-verify"),
    wide: bool = typer.Option(False, "--wide"),
    json_output: bool = typer.Option(False, "--json"),
    device: str = typer.Option(None, "--device"),
    status: str = typer.Option(None, "--status"),
    node_class: str = typer.Option(None, "--class"),
    ) -> None:
        """List Nomad nodes and their labels."""
        raise SystemExit(
            run_discover(
            profile=profile,
            endpoint=endpoint,
            namespace=namespace,
            token=token,
            tls_ca=tls_ca,
            tls_skip_verify=tls_skip_verify,
            wide=wide,
            json_output=json_output,
            device=device,
            status=status,
            node_class=node_class,
            )
        )


@app.command()
def deploy(
    dry_run: bool = typer.Option(False, "--dry-run"),
    out: str | None = typer.Option(None, "--out"),
    format: str = typer.Option("json", "--format"),
    num_supernodes: int = typer.Option(2, "--num-supernodes"),
) -> None:
    """Render Nomad job specs (dry-run only)."""
    raise SystemExit(
        run_deploy(
            dry_run=dry_run,
            out=out,
            fmt=format,
            num_supernodes=num_supernodes,
        )
    )


@app.command()
def inspect(
    path: str = typer.Argument(".", help="Path to a Flower project (dir or pyproject.toml).")
) -> None:
    """Inspect a Flower project for fedctl metadata."""
    raise SystemExit(run_inspect(path))


@local_app.command("up")
def local_up(
    server: str = typer.Option(..., "--server"),
    client: list[str] = typer.Option([], "--client", "-c"),
    wipe: bool = typer.Option(False, "--wipe"),
    wait_seconds: int = typer.Option(30, "--wait-seconds"),
    expected_nodes: int | None = typer.Option(None, "--expected-nodes"),
    endpoint: str = typer.Option("http://127.0.0.1:4646", "--endpoint"),
) -> None:
    """Start a local Nomad harness from HCL configs."""
    if not client:
        raise typer.BadParameter("At least one --client is required.")
    raise SystemExit(
        run_local_up(
            server_config=server,
            client_configs=client,
            wipe=wipe,
            wait_seconds=wait_seconds,
            expected_nodes=expected_nodes,
            endpoint=endpoint,
        )
    )


@local_app.command("down")
def local_down(
    wipe: bool = typer.Option(False, "--wipe"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Stop the local Nomad harness."""
    raise SystemExit(run_local_down(wipe=wipe, force=force))


@local_app.command("status")
def local_status() -> None:
    """Show local harness status."""
    raise SystemExit(run_local_status())
