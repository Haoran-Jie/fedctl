from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from fedctl.config.io import load_config
from fedctl.config.merge import get_effective_config
from fedctl.deploy import naming
from fedctl.deploy.errors import DeployError
from fedctl.deploy.render import RenderedJobs, render_deploy
from fedctl.deploy.resolve import wait_for_superlink
from fedctl.deploy.spec import default_deploy_spec
from fedctl.deploy.submit import submit_jobs
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError
from fedctl.state.errors import StateError
from fedctl.state.manifest import DeploymentManifest, SuperlinkManifest, new_deployment_id
from fedctl.state.store import write_manifest

console = Console()


def run_deploy(
    *,
    dry_run: bool = False,
    out: str | None = None,
    fmt: str = "json",
    num_supernodes: int = 2,
    timeout_seconds: int = 120,
    no_wait: bool = False,
    profile: str | None = None,
    endpoint: str | None = None,
    namespace: str | None = None,
    token: str | None = None,
    tls_ca: str | None = None,
    tls_skip_verify: bool | None = None,
) -> int:
    if fmt != "json":
        console.print(f"[red]✗ Unsupported format:[/red] {fmt}")
        return 1

    if out and not dry_run:
        console.print("[red]✗ --out is only supported with --dry-run.[/red]")
        return 1

    spec = default_deploy_spec(num_supernodes=num_supernodes)
    try:
        rendered = render_deploy(spec)
    except Exception as exc:
        console.print(f"[red]✗ Render error:[/red] {exc}")
        return 1

    if out:
        _write_rendered(Path(out), rendered)
        console.print(f"[green]✓ Rendered jobs to:[/green] {out}")
        return 0

    if dry_run:
        bundle = _bundle_json(rendered)
        print(json.dumps(bundle, indent=2, sort_keys=True))
        return 0

    cfg = load_config()
    try:
        eff = get_effective_config(
            cfg,
            profile_name=profile,
            endpoint=endpoint,
            namespace=namespace,
            token=token,
            tls_ca=tls_ca,
            tls_skip_verify=tls_skip_verify,
        )
    except ValueError as exc:
        console.print(f"[red]✗ Config error:[/red] {exc}")
        return 1

    client = NomadClient(eff)
    try:
        submit_jobs(client, rendered)
        if no_wait:
            console.print("[green]✓ Submitted jobs.[/green] Skipping wait/manifest.")
            return 0

        superlink_alloc = wait_for_superlink(
            client, timeout_seconds=timeout_seconds
        )
        manifest = _build_manifest(rendered, superlink_alloc)
        path = write_manifest(manifest, namespace=namespace or "default")
        console.print(f"[green]✓ Deployment ready.[/green] Manifest: {path}")
        return 0

    except DeployError as exc:
        console.print(f"[red]✗ Deploy error:[/red] {exc}")
        return 1

    except StateError as exc:
        console.print(f"[red]✗ Manifest error:[/red] {exc}")
        return 1

    except NomadTLSError as exc:
        console.print(f"[red]✗ TLS error:[/red] {exc}")
        return 2

    except NomadHTTPError as exc:
        console.print(f"[red]✗ HTTP error:[/red] {exc}")
        if getattr(exc, "status_code", None) == 403:
            console.print("[yellow]Hint:[/yellow] Token/ACL invalid or missing permissions.")
        return 3

    except NomadConnectionError as exc:
        console.print(f"[red]✗ Connection error:[/red] {exc}")
        console.print(
            "[yellow]Hint:[/yellow] Check endpoint reachability (LAN/Tailscale/SSH tunnel)."
        )
        return 4

    finally:
        client.close()


def _bundle_json(rendered: RenderedJobs) -> dict[str, object]:
    return {
        naming.job_superlink(): rendered.superlink,
        naming.job_supernodes(): rendered.supernodes,
        naming.job_superexec_serverapp(): rendered.superexec_serverapp,
        "superexec-clientapps": rendered.superexec_clientapps,
    }


def _write_rendered(out_dir: Path, rendered: RenderedJobs) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_job(out_dir / f"{naming.job_superlink()}.json", rendered.superlink)
    _write_job(out_dir / f"{naming.job_supernodes()}.json", rendered.supernodes)
    _write_job(out_dir / f"{naming.job_superexec_serverapp()}.json", rendered.superexec_serverapp)
    for job in rendered.superexec_clientapps:
        name = job.get("Job", {}).get("Name")
        if isinstance(name, str) and name:
            _write_job(out_dir / f"{name}.json", job)


def _write_job(path: Path, job: dict[str, object]) -> None:
    path.write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")


def _build_manifest(
    rendered: RenderedJobs,
    superlink_alloc: object,
) -> DeploymentManifest:
    from fedctl.deploy.resolve import SuperlinkAllocation

    if not isinstance(superlink_alloc, SuperlinkAllocation):
        raise DeployError("Unexpected SuperLink allocation result.")

    jobs = {
        "superlink": naming.job_superlink(),
        "supernodes": naming.job_supernodes(),
        "superexec-serverapp": naming.job_superexec_serverapp(),
        "superexec-clientapps": [
            naming.job_superexec_clientapp(i)
            for i in range(1, len(rendered.superexec_clientapps) + 1)
        ],
    }
    superlink = SuperlinkManifest(
        alloc_id=superlink_alloc.alloc_id,
        node_id=superlink_alloc.node_id,
        ports=superlink_alloc.ports,
    )
    return DeploymentManifest(
        schema_version=1,
        deployment_id=new_deployment_id(),
        jobs=jobs,
        superlink=superlink,
    )
