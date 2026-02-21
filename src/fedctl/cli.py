"""CLI entrypoint for fedctl."""

import os
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
from fedctl.commands.logs import run_logs
from fedctl.commands.ping import run_ping
from fedctl.commands.submit import (
    run_submit,
    run_submit_logs,
    run_submit_ls,
    run_submit_purge,
    run_submit_results,
    run_submit_status,
    run_submit_inventory,
)
from fedctl.config.io import load_config, load_raw_toml, save_raw_toml
from fedctl.config.merge import get_effective_config

app = typer.Typer(add_completion=False, help="fedctl CLI")

_SHOW_ADMIN_HELP = os.getenv("FEDCTL_SHOW_ADMIN_HELP", "").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def _admin_hidden() -> bool:
    return not _SHOW_ADMIN_HELP


config_app = typer.Typer(help="Manage fedctl configuration")
profile_app = typer.Typer(help="Manage profiles")
local_app = typer.Typer(help="Local Nomad harness")
submit_app = typer.Typer(help="Submit jobs to Nomad")
app.add_typer(config_app, name="config", hidden=_admin_hidden())
app.add_typer(profile_app, name="profile", hidden=_admin_hidden())
app.add_typer(local_app, name="local", hidden=_admin_hidden())
app.add_typer(submit_app, name="submit")


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
    tailscale_subnet_cidr: str = typer.Option(None, "--tailscale-subnet-cidr"),
) -> None:
    doc = load_raw_toml()
    if "profiles" not in doc:
        doc["profiles"] = {}
    if name in doc["profiles"]:
        raise typer.BadParameter(f"Profile '{name}' already exists.")

    p = {
        "endpoint": endpoint,
        "access_mode": access_mode,
        "tailscale": {},
    }

    if namespace is not None:
        p["namespace"] = namespace
    if repo_config is not None:
        p["repo_config"] = str(Path(repo_config).expanduser().resolve())
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
    tailscale_subnet_cidr: str | None = typer.Option(None, "--tailscale-subnet-cidr"),
    clear_namespace: bool = typer.Option(False, "--clear-namespace"),
    clear_repo_config: bool = typer.Option(False, "--clear-repo-config"),
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

    if clear_namespace:
        p.pop("namespace", None)
    elif namespace is not None:
        p["namespace"] = namespace

    if clear_repo_config:
        p.pop("repo_config", None)
    elif repo_config is not None:
        p["repo_config"] = str(Path(repo_config).expanduser().resolve())

    if "tailscale" not in p:
        p["tailscale"] = tomlkit.table()
    ts = p["tailscale"]
    if clear_tailscale_subnet:
        ts.pop("subnet_cidr", None)
    elif tailscale_subnet_cidr is not None:
        ts["subnet_cidr"] = tailscale_subnet_cidr

    save_raw_toml(doc)
    print(f"Updated profile: [bold]{name}[/bold]")


@submit_app.callback(invoke_without_command=True)
def submit(
    ctx: typer.Context,
) -> None:
    """Submit a project for queued execution."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


@submit_app.command("run")
def submit_run(
    path: str = typer.Argument(".", help="Path to a Flower project (dir or pyproject.toml)."),
    flwr_version: str = typer.Option("1.25.0", "--flwr-version"),
    image: str | None = typer.Option(None, "--image"),
    no_cache: bool = typer.Option(False, "--no-cache"),
    platform: str | None = typer.Option(None, "--platform"),
    context: str | None = typer.Option(None, "--context"),
    push: bool = typer.Option(True, "--push/--no-push"),
    num_supernodes: int = typer.Option(2, "--num-supernodes"),
    auto_supernodes: bool = typer.Option(True, "--auto-supernodes/--no-auto-supernodes"),
    supernodes: list[str] = typer.Option(None, "--supernodes"),
    net: list[str] = typer.Option(None, "--net"),
    allow_oversubscribe: bool | None = typer.Option(
        None, "--allow-oversubscribe/--no-allow-oversubscribe"
    ),
    repo_config: str | None = typer.Option(None, "--repo-config"),
    exp: str | None = typer.Option(None, "--exp"),
    timeout: int = typer.Option(120, "--timeout"),
    federation: str = typer.Option("remote-deployment", "--federation"),
    stream: bool = typer.Option(True, "--stream/--no-stream"),
    verbose: bool = typer.Option(False, "--verbose"),
    destroy: bool = typer.Option(True, "--destroy/--no-destroy"),
    submit_node_class: str | None = typer.Option(None, "--submit-node-class"),
    submit_image: str | None = typer.Option(None, "--submit-image"),
    artifact_store: str | None = typer.Option(None, "--artifact-store"),
    priority: int | None = typer.Option(None, "--priority"),
) -> None:
    """Submit a project for queued execution."""
    raise SystemExit(
        run_submit(
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
            net=net,
            allow_oversubscribe=allow_oversubscribe,
            repo_config=repo_config,
            experiment=exp,
            timeout_seconds=timeout,
            federation=federation,
            stream=stream,
            verbose=verbose,
            destroy=destroy,
            submit_node_class=submit_node_class,
            submit_image=submit_image,
            artifact_store=artifact_store,
            priority=priority,
        )
    )


@submit_app.command("status")
def submit_status(
    submission_id: str = typer.Argument(..., help="Submission ID."),
) -> None:
    """Show status for a submitted job."""
    raise SystemExit(run_submit_status(submission_id=submission_id))


@submit_app.command("logs")
def submit_logs(
    submission_id: str = typer.Argument(..., help="Submission ID."),
    job: str = typer.Option(
        "submit",
        "--job",
        help=(
            "Which job to read logs from. Common values: submit, superlink, "
            "supernodes, superexec_serverapp, superexec_clientapps."
        ),
    ),
    task: str | None = typer.Option(
        None,
        "--task",
        help=(
            "Nomad task name within the job. Examples: submit, superlink, "
            "superexec-serverapp, supernode-1, supernode-rpi-1. "
            "Required for job=supernodes."
        ),
    ),
    index: int = typer.Option(
        1,
        "--index",
        min=1,
        help=(
            "Job index for multi-job groups (e.g., superexec_clientapps). "
            "Example: --job superexec_clientapps --index 2"
        ),
    ),
    stderr: bool = typer.Option(False, "--stderr/--stdout", help="Show stderr or stdout."),
    follow: bool = typer.Option(False, "--follow", help="Stream logs."),
) -> None:
    """Fetch logs for a submitted job.

    Examples:
      fedctl submit logs <id>
      fedctl submit logs <id> --job superlink
      fedctl submit logs <id> --job supernodes --task supernode-1
      fedctl submit logs <id> --job superexec_clientapps --index 2
    """
    raise SystemExit(
        run_submit_logs(
            submission_id=submission_id,
            job=job,
            task=task,
            index=index,
            stderr=stderr,
            follow=follow,
        )
    )


@submit_app.command("ls")
def submit_ls(
    limit: int = typer.Option(20, "--limit"),
    active: bool = typer.Option(True, "--active/--all"),
) -> None:
    """List recent submissions."""
    raise SystemExit(run_submit_ls(limit=limit, active=active))


@submit_app.command("inventory")
def submit_inventory(
    include_allocs: bool = typer.Option(True, "--include-allocs"),
    detail: bool = typer.Option(False, "--detail"),
    json_output: bool = typer.Option(False, "--json"),
    status: str | None = typer.Option(None, "--status"),
    node_class: str | None = typer.Option(None, "--class"),
    device_type: str | None = typer.Option(None, "--device-type"),
) -> None:
    """Show Nomad node inventory via the submit service."""
    raise SystemExit(
        run_submit_inventory(
            include_allocs=include_allocs,
            detail=detail,
            json_output=json_output,
            status=status,
            node_class=node_class,
            device_type=device_type,
        )
    )


@submit_app.command("purge")
def submit_purge() -> None:
    """Clear submit-service and local submission history."""
    raise SystemExit(run_submit_purge())


@submit_app.command("results")
def submit_results(
    submission_id: str = typer.Argument(..., help="Submission ID."),
    download: bool = typer.Option(False, "--download/--no-download"),
    out: str | None = typer.Option(None, "--out"),
) -> None:
    """Show or download result artifacts for a submission."""
    raise SystemExit(
        run_submit_results(
            submission_id=submission_id,
            download=download,
            out=out,
        )
    )

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
    display = _truncate_path(display)
    if not path.exists():
        display = f"{display} (missing)"
    return display


def _truncate_path(value: str, max_len: int = 48) -> str:
    if len(value) <= max_len:
        return value
    keep = max_len - 3
    head = keep // 2
    tail = keep - head
    return f"{value[:head]}...{value[-tail:]}"


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


@app.command(hidden=_admin_hidden())
def doctor(
    profile: str = typer.Option(None, "--profile"),
    endpoint: str = typer.Option(None, "--endpoint"),
    namespace: str = typer.Option(None, "--namespace"),
    token: str = typer.Option(None, "--token"),
) -> None:
    """Check connectivity/auth/TLS to Nomad."""
    raise SystemExit(
        run_doctor(
            profile=profile,
            endpoint=endpoint,
            namespace=namespace,
            token=token,
        )
    )


@app.command(hidden=_admin_hidden())
def ping(
    profile: str = typer.Option(None, "--profile"),
    endpoint: str = typer.Option(None, "--endpoint"),
    namespace: str = typer.Option(None, "--namespace"),
    token: str = typer.Option(None, "--token"),
) -> None:
    """Quick connectivity check to Nomad (/v1/status/leader)."""
    raise SystemExit(
        run_ping(
            profile=profile,
            endpoint=endpoint,
            namespace=namespace,
            token=token,
        )
    )


@app.command(hidden=_admin_hidden())
def discover(
    wide: bool = typer.Option(False, "--wide"),
    json_output: bool = typer.Option(False, "--json"),
    device: str = typer.Option(None, "--device"),
    status: str = typer.Option(None, "--status"),
    node_class: str = typer.Option(None, "--class"),
) -> None:
    """List Nomad nodes and their labels."""
    raise SystemExit(
        run_discover(
            wide=wide,
            json_output=json_output,
            device=device,
            status=status,
            node_class=node_class,
        )
    )


@app.command(hidden=_admin_hidden())
def deploy(
    dry_run: bool = typer.Option(False, "--dry-run"),
    out: str | None = typer.Option(None, "--out"),
    format: str = typer.Option("json", "--format"),
    num_supernodes: int | None = typer.Option(None, "--num-supernodes"),
    supernodes: list[str] = typer.Option(None, "--supernodes"),
    net: list[str] = typer.Option(None, "--net"),
    allow_oversubscribe: bool | None = typer.Option(
        None, "--allow-oversubscribe/--no-allow-oversubscribe"
    ),
    repo_config: str | None = typer.Option(None, "--repo-config"),
    image: str | None = typer.Option(None, "--image"),
    exp: str | None = typer.Option(None, "--exp"),
    timeout: int = typer.Option(120, "--timeout"),
    no_wait: bool = typer.Option(False, "--no-wait"),
) -> None:
    """Deploy Flower jobs to Nomad (or render with --dry-run)."""
    raise SystemExit(
        run_deploy(
            dry_run=dry_run,
            out=out,
            fmt=format,
            num_supernodes=num_supernodes,
            supernodes=supernodes,
            net=net,
            allow_oversubscribe=allow_oversubscribe,
            repo_config=repo_config,
            image=image,
            experiment=exp,
            timeout_seconds=timeout,
            no_wait=no_wait,
        )
    )


@app.command(hidden=_admin_hidden())
def build(
    path: str = typer.Argument(".", help="Path to a Flower project (dir or pyproject.toml)."),
    flwr_version: str = typer.Option("1.25.0", "--flwr-version"),
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


@app.command(hidden=_admin_hidden())
def address(
    exp: str | None = typer.Option(None, "--exp"),
    format: str = typer.Option("plain", "--format"),
) -> None:
    """Resolve the SuperLink control address."""
    raise SystemExit(
        run_address(
            experiment=exp,
            fmt=format,
        )
    )


@app.command(hidden=_admin_hidden())
def configure(
    path: str = typer.Argument(".", help="Path to a Flower project (dir or pyproject.toml)."),
    exp: str | None = typer.Option(None, "--exp"),
    backup: bool = typer.Option(True, "--backup/--no-backup"),
) -> None:
    """Patch pyproject.toml with the resolved federation address."""
    raise SystemExit(
        run_configure(
            path=path,
            backup=backup,
            experiment=exp,
        )
    )


@app.command(hidden=_admin_hidden())
def run(
    path: str = typer.Argument(".", help="Path to a Flower project (dir or pyproject.toml)."),
    flwr_version: str = typer.Option("1.25.0", "--flwr-version"),
    image: str | None = typer.Option(None, "--image"),
    no_cache: bool = typer.Option(False, "--no-cache"),
    platform: str | None = typer.Option(None, "--platform"),
    context: str | None = typer.Option(None, "--context"),
    push: bool = typer.Option(False, "--push"),
    num_supernodes: int = typer.Option(2, "--num-supernodes"),
    auto_supernodes: bool = typer.Option(True, "--auto-supernodes/--no-auto-supernodes"),
    supernodes: list[str] = typer.Option(None, "--supernodes"),
    net: list[str] = typer.Option(None, "--net"),
    allow_oversubscribe: bool | None = typer.Option(
        None, "--allow-oversubscribe/--no-allow-oversubscribe"
    ),
    repo_config: str | None = typer.Option(None, "--repo-config"),
    exp: str | None = typer.Option(None, "--exp"),
    timeout: int = typer.Option(120, "--timeout"),
    no_wait: bool = typer.Option(False, "--no-wait"),
    federation: str = typer.Option("remote-deployment", "--federation"),
    stream: bool = typer.Option(True, "--stream/--no-stream"),
    verbose: bool = typer.Option(False, "--verbose"),
    destroy: bool = typer.Option(True, "--destroy/--no-destroy"),
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
            net=net,
            allow_oversubscribe=allow_oversubscribe,
            repo_config=repo_config,
            experiment=exp,
            timeout_seconds=timeout,
            no_wait=no_wait,
            federation=federation,
            stream=stream,
            verbose=verbose,
            destroy=destroy,
        )
    )


@app.command(hidden=_admin_hidden())
def destroy(
    exp: str | None = typer.Argument(None, help="Experiment name."),
    purge: bool = typer.Option(False, "--purge"),
    all: bool = typer.Option(False, "--all"),
    profile: str | None = typer.Option(None, "--profile"),
    endpoint: str | None = typer.Option(None, "--endpoint"),
    namespace: str | None = typer.Option(None, "--namespace"),
    token: str | None = typer.Option(None, "--token"),
) -> None:
    """Stop jobs for an experiment, optionally purging them."""
    raise SystemExit(
        run_destroy(
            experiment=exp,
            destroy_all=all,
            purge=purge,
            profile=profile,
            endpoint=endpoint,
            namespace=namespace,
            token=token,
        )
    )


@app.command(hidden=_admin_hidden())
def status(
    exp: str | None = typer.Argument(None, help="Experiment name."),
    all: bool = typer.Option(False, "--all"),
) -> None:
    """Show allocation status for an experiment."""
    raise SystemExit(
        run_status(
            experiment=exp,
            show_all=all,
        )
    )


@app.command(hidden=_admin_hidden())
def logs(
    exp: str | None = typer.Argument(None, help="Experiment name."),
    component: str = typer.Option("all", "--component"),
    stderr: bool = typer.Option(True, "--stderr/--stdout"),
) -> None:
    """Fetch active allocation logs for an experiment."""
    raise SystemExit(
        run_logs(
            experiment=exp,
            component=component,
            stderr=stderr,
        )
    )


@app.command(hidden=_admin_hidden())
def register(
    username: str = typer.Argument(..., help="Username (also namespace by default)."),
    endpoint: str = typer.Option(..., "--endpoint"),
    bootstrap_token: str = typer.Option(..., "--bootstrap-token"),
    namespace: str | None = typer.Option(None, "--namespace"),
    profile: str | None = typer.Option(None, "--profile"),
    ttl: str | None = typer.Option(None, "--ttl"),
    force: bool = typer.Option(False, "--force"),
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
        )
    )


@app.command(hidden=_admin_hidden())
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
