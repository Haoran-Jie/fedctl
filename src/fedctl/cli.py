"""CLI entrypoint for fedctl."""

import typer
from pathlib import Path
import tomlkit
from rich import print
from rich.table import Table

from fedctl.commands.address import run_address
from fedctl.commands.build import run_build
from fedctl.commands.configure import run_configure
from fedctl.commands.run import run_run
from fedctl.commands.destroy import run_destroy
from fedctl.commands.status import run_status
from fedctl.commands.register import run_register
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
    table.add_column("Repo config")
    table.add_column("Access mode")
    for name, p in cfg.profiles.items():
        marker = "*" if name == cfg.active_profile else ""
        repo_cfg = _format_repo_config(p.repo_config)
        table.add_row(
            f"{name}{marker}",
            p.endpoint,
            str(p.namespace),
            repo_cfg,
            p.access_mode,
        )
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
    repo_config: str = typer.Option(None, "--repo-config"),
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
    if repo_config is not None:
        p["repo_config"] = str(Path(repo_config).expanduser().resolve())
    if tls_ca is not None:
        p["tls_ca"] = tls_ca
    if tailscale_subnet_cidr is not None:
        p["tailscale"]["subnet_cidr"] = tailscale_subnet_cidr

    doc["profiles"][name] = p
    save_raw_toml(doc)
    print(f"Added profile: [bold]{name}[/bold]")


@profile_app.command("set")
def profile_set(
    name: str,
    endpoint: str | None = typer.Option(None, "--endpoint"),
    namespace: str | None = typer.Option(None, "--namespace"),
    repo_config: str | None = typer.Option(None, "--repo-config"),
    access_mode: str | None = typer.Option(None, "--access-mode"),
    tls_ca: str | None = typer.Option(None, "--tls-ca"),
    tls_skip_verify: bool | None = typer.Option(None, "--tls-skip-verify"),
    tailscale_subnet_cidr: str | None = typer.Option(None, "--tailscale-subnet-cidr"),
    clear_namespace: bool = typer.Option(False, "--clear-namespace"),
    clear_repo_config: bool = typer.Option(False, "--clear-repo-config"),
    clear_tls_ca: bool = typer.Option(False, "--clear-tls-ca"),
    clear_tailscale_subnet: bool = typer.Option(False, "--clear-tailscale-subnet"),
) -> None:
    doc = load_raw_toml()
    profiles = doc.get("profiles", {})
    if name not in profiles:
        raise typer.BadParameter(f"Unknown profile '{name}'.")

    p = profiles[name]
    if endpoint is not None:
        p["endpoint"] = endpoint
    if access_mode is not None:
        p["access_mode"] = access_mode
    if tls_skip_verify is not None:
        p["tls_skip_verify"] = tls_skip_verify

    if clear_namespace:
        p.pop("namespace", None)
    elif namespace is not None:
        p["namespace"] = namespace

    if clear_repo_config:
        p.pop("repo_config", None)
    elif repo_config is not None:
        p["repo_config"] = str(Path(repo_config).expanduser().resolve())

    if clear_tls_ca:
        p.pop("tls_ca", None)
    elif tls_ca is not None:
        p["tls_ca"] = tls_ca

    if "tailscale" not in p:
        p["tailscale"] = tomlkit.table()
    ts = p["tailscale"]
    if clear_tailscale_subnet:
        ts.pop("subnet_cidr", None)
    elif tailscale_subnet_cidr is not None:
        ts["subnet_cidr"] = tailscale_subnet_cidr

    save_raw_toml(doc)
    print(f"Updated profile: [bold]{name}[/bold]")


def _format_repo_config(value: str | None) -> str:
    if not value:
        return "-"
    path = Path(value)
    display = str(path)
    try:
        cwd = Path.cwd()
        if path.is_absolute() and str(path).startswith(str(cwd)):
            display = f"./{path.relative_to(cwd)}"
        else:
            home = Path.home()
            if path.is_absolute() and str(path).startswith(str(home)):
                display = f"~/{path.relative_to(home)}"
    except ValueError:
        pass
    if not path.exists():
        display = f"{display} (missing)"
    return display


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
    supernodes: list[str] = typer.Option(None, "--supernodes"),
    allow_oversubscribe: bool | None = typer.Option(
        None, "--allow-oversubscribe/--no-allow-oversubscribe"
    ),
    repo_config: str | None = typer.Option(None, "--repo-config"),
    image: str | None = typer.Option(None, "--image"),
    exp: str | None = typer.Option(None, "--exp"),
    timeout: int = typer.Option(120, "--timeout"),
    no_wait: bool = typer.Option(False, "--no-wait"),
    profile: str | None = typer.Option(None, "--profile"),
    endpoint: str | None = typer.Option(None, "--endpoint"),
    namespace: str | None = typer.Option(None, "--namespace"),
    token: str | None = typer.Option(None, "--token"),
    tls_ca: str | None = typer.Option(None, "--tls-ca"),
    tls_skip_verify: bool | None = typer.Option(None, "--tls-skip-verify"),
) -> None:
    """Deploy Flower jobs to Nomad (or render with --dry-run)."""
    raise SystemExit(
        run_deploy(
            dry_run=dry_run,
            out=out,
            fmt=format,
            num_supernodes=num_supernodes,
            supernodes=supernodes,
            allow_oversubscribe=allow_oversubscribe,
            repo_config=repo_config,
            image=image,
            experiment=exp,
            timeout_seconds=timeout,
            no_wait=no_wait,
            profile=profile,
            endpoint=endpoint,
            namespace=namespace,
            token=token,
            tls_ca=tls_ca,
            tls_skip_verify=tls_skip_verify,
        )
    )


@app.command()
def build(
    path: str = typer.Argument(".", help="Path to a Flower project (dir or pyproject.toml)."),
    flwr_version: str = typer.Option("1.23.0", "--flwr-version"),
    image: str | None = typer.Option(None, "--image"),
    no_cache: bool = typer.Option(False, "--no-cache"),
    platform: str | None = typer.Option(None, "--platform"),
    context: str | None = typer.Option(None, "--context"),
    push: bool = typer.Option(False, "--push"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Build a SuperExec Docker image for a Flower project."""
    raise SystemExit(
        run_build(
            path=path,
            flwr_version=flwr_version,
            image=image,
            no_cache=no_cache,
            platform=platform,
            context=context,
            push=push,
            verbose=verbose,
        )
    )


@app.command()
def address(
    namespace: str | None = typer.Option(None, "--namespace"),
    exp: str | None = typer.Option(None, "--exp"),
    format: str = typer.Option("plain", "--format"),
    profile: str | None = typer.Option(None, "--profile"),
    endpoint: str | None = typer.Option(None, "--endpoint"),
    token: str | None = typer.Option(None, "--token"),
    tls_ca: str | None = typer.Option(None, "--tls-ca"),
    tls_skip_verify: bool | None = typer.Option(None, "--tls-skip-verify"),
) -> None:
    """Resolve the SuperLink control address."""
    raise SystemExit(
        run_address(
            namespace=namespace,
            experiment=exp,
            fmt=format,
            profile=profile,
            endpoint=endpoint,
            token=token,
            tls_ca=tls_ca,
            tls_skip_verify=tls_skip_verify,
        )
    )


@app.command()
def configure(
    path: str = typer.Argument(".", help="Path to a Flower project (dir or pyproject.toml)."),
    namespace: str | None = typer.Option(None, "--namespace"),
    exp: str | None = typer.Option(None, "--exp"),
    backup: bool = typer.Option(True, "--backup/--no-backup"),
    profile: str | None = typer.Option(None, "--profile"),
    endpoint: str | None = typer.Option(None, "--endpoint"),
    token: str | None = typer.Option(None, "--token"),
    tls_ca: str | None = typer.Option(None, "--tls-ca"),
    tls_skip_verify: bool | None = typer.Option(None, "--tls-skip-verify"),
) -> None:
    """Patch pyproject.toml with the resolved federation address."""
    raise SystemExit(
        run_configure(
            path=path,
            namespace=namespace,
            backup=backup,
            experiment=exp,
            profile=profile,
            endpoint=endpoint,
            token=token,
            tls_ca=tls_ca,
            tls_skip_verify=tls_skip_verify,
        )
    )


@app.command()
def run(
    path: str = typer.Argument(".", help="Path to a Flower project (dir or pyproject.toml)."),
    flwr_version: str = typer.Option("1.23.0", "--flwr-version"),
    image: str | None = typer.Option(None, "--image"),
    no_cache: bool = typer.Option(False, "--no-cache"),
    platform: str | None = typer.Option(None, "--platform"),
    context: str | None = typer.Option(None, "--context"),
    push: bool = typer.Option(False, "--push"),
    num_supernodes: int = typer.Option(2, "--num-supernodes"),
    auto_supernodes: bool = typer.Option(True, "--auto-supernodes/--no-auto-supernodes"),
    supernodes: list[str] = typer.Option(None, "--supernodes"),
    allow_oversubscribe: bool | None = typer.Option(
        None, "--allow-oversubscribe/--no-allow-oversubscribe"
    ),
    repo_config: str | None = typer.Option(None, "--repo-config"),
    exp: str | None = typer.Option(None, "--exp"),
    timeout: int = typer.Option(120, "--timeout"),
    no_wait: bool = typer.Option(False, "--no-wait"),
    namespace: str | None = typer.Option(None, "--namespace"),
    profile: str | None = typer.Option(None, "--profile"),
    endpoint: str | None = typer.Option(None, "--endpoint"),
    token: str | None = typer.Option(None, "--token"),
    tls_ca: str | None = typer.Option(None, "--tls-ca"),
    tls_skip_verify: bool | None = typer.Option(None, "--tls-skip-verify"),
    federation: str = typer.Option("remote-deployment", "--federation"),
    stream: bool = typer.Option(True, "--stream/--no-stream"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    """Build, deploy, configure, and run a Flower project."""
    raise SystemExit(
        run_run(
            path=path,
            flwr_version=flwr_version,
            image=image,
            no_cache=no_cache,
            platform=platform,
            context=context,
            push=push,
            num_supernodes=num_supernodes,
            auto_supernodes=auto_supernodes,
            supernodes=supernodes,
            allow_oversubscribe=allow_oversubscribe,
            repo_config=repo_config,
            experiment=exp,
            timeout_seconds=timeout,
            no_wait=no_wait,
            namespace=namespace,
            profile=profile,
            endpoint=endpoint,
            token=token,
            tls_ca=tls_ca,
            tls_skip_verify=tls_skip_verify,
            federation=federation,
            stream=stream,
            verbose=verbose,
        )
    )


@app.command()
def destroy(
    exp: str | None = typer.Argument(None, help="Experiment name."),
    namespace: str | None = typer.Option(None, "--namespace"),
    purge: bool = typer.Option(False, "--purge"),
    all: bool = typer.Option(False, "--all"),
    profile: str | None = typer.Option(None, "--profile"),
    endpoint: str | None = typer.Option(None, "--endpoint"),
    token: str | None = typer.Option(None, "--token"),
    tls_ca: str | None = typer.Option(None, "--tls-ca"),
    tls_skip_verify: bool | None = typer.Option(None, "--tls-skip-verify"),
) -> None:
    """Stop jobs for an experiment, optionally purging them."""
    raise SystemExit(
        run_destroy(
            experiment=exp,
            destroy_all=all,
            namespace=namespace,
            purge=purge,
            profile=profile,
            endpoint=endpoint,
            token=token,
            tls_ca=tls_ca,
            tls_skip_verify=tls_skip_verify,
        )
    )


@app.command()
def status(
    exp: str | None = typer.Argument(None, help="Experiment name."),
    all: bool = typer.Option(False, "--all"),
    namespace: str | None = typer.Option(None, "--namespace"),
    profile: str | None = typer.Option(None, "--profile"),
    endpoint: str | None = typer.Option(None, "--endpoint"),
    token: str | None = typer.Option(None, "--token"),
    tls_ca: str | None = typer.Option(None, "--tls-ca"),
    tls_skip_verify: bool | None = typer.Option(None, "--tls-skip-verify"),
) -> None:
    """Show allocation status for an experiment."""
    raise SystemExit(
        run_status(
            experiment=exp,
            show_all=all,
            namespace=namespace,
            profile=profile,
            endpoint=endpoint,
            token=token,
            tls_ca=tls_ca,
            tls_skip_verify=tls_skip_verify,
        )
    )


@app.command()
def register(
    username: str = typer.Argument(..., help="Username (also namespace by default)."),
    endpoint: str = typer.Option(..., "--endpoint"),
    bootstrap_token: str = typer.Option(..., "--bootstrap-token"),
    namespace: str | None = typer.Option(None, "--namespace"),
    profile: str | None = typer.Option(None, "--profile"),
    ttl: str | None = typer.Option(None, "--ttl"),
    force: bool = typer.Option(False, "--force"),
    tls_ca: str | None = typer.Option(None, "--tls-ca"),
    tls_skip_verify: bool = typer.Option(False, "--tls-skip-verify"),
) -> None:
    """Register a user namespace and scoped ACL token using a bootstrap token."""
    raise SystemExit(
        run_register(
            username=username,
            endpoint=endpoint,
            bootstrap_token=bootstrap_token,
            namespace=namespace,
            profile=profile,
            ttl=ttl,
            force=force,
            tls_ca=tls_ca,
            tls_skip_verify=tls_skip_verify,
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
