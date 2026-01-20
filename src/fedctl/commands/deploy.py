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
from fedctl.deploy.spec import default_deploy_spec, normalize_experiment_name
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
    image: str | None = None,
    experiment: str | None = None,
    timeout_seconds: int = 120,
    no_wait: bool = False,
    profile: str | None = None,
    endpoint: str | None = None,
    namespace: str | None = None,
    token: str | None = None,
    tls_ca: str | None = None,
    tls_skip_verify: bool | None = None,
) -> int:
    if not image:
        console.print("[red]✗ No SuperExec image specified.[/red]")
        console.print("[yellow]Hint:[/yellow] Run `fedctl build` and deploy with --image.")
        return 1

    if fmt != "json":
        console.print(f"[red]✗ Unsupported format:[/red] {fmt}")
        return 1

    if out and not dry_run:
        console.print("[red]✗ --out is only supported with --dry-run.[/red]")
        return 1

    if dry_run:
        exp_name = normalize_experiment_name(experiment or "experiment")
        spec = default_deploy_spec(
            num_supernodes=num_supernodes,
            image=image,
            namespace=namespace or "default",
            experiment=exp_name,
        )
        try:
            rendered = render_deploy(spec)
        except Exception as exc:
            console.print(f"[red]✗ Render error:[/red] {exc}")
            return 1

        if out:
            _write_rendered(Path(out), rendered)
            console.print(f"[green]✓ Rendered jobs to:[/green] {out}")
            return 0

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

    exp_name = normalize_experiment_name(experiment or "experiment")
    spec = default_deploy_spec(
        num_supernodes=num_supernodes,
        image=image,
        namespace=eff.namespace or "default",
        experiment=exp_name,
    )
    try:
        rendered = render_deploy(spec)
    except Exception as exc:
        console.print(f"[red]✗ Render error:[/red] {exc}")
        return 1

    client = NomadClient(eff)
    try:
        submit_jobs(client, rendered)
        if no_wait:
            console.print("[green]✓ Submitted jobs.[/green] Skipping wait/manifest.")
            return 0

        superlink_alloc = wait_for_superlink(
            client,
            job_name=rendered.superlink["Job"]["Name"],
            timeout_seconds=timeout_seconds,
        )
        manifest = _build_manifest(rendered, superlink_alloc)
        path = write_manifest(
            manifest,
            namespace=eff.namespace or "default",
            experiment=exp_name,
        )
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
        rendered.superlink["Job"]["Name"]: rendered.superlink,
        rendered.supernodes["Job"]["Name"]: rendered.supernodes,
        rendered.superexec_serverapp["Job"]["Name"]: rendered.superexec_serverapp,
        "superexec-clientapps": rendered.superexec_clientapps,
    }


def _write_rendered(out_dir: Path, rendered: RenderedJobs) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_job(out_dir / f"{rendered.superlink['Job']['Name']}.json", rendered.superlink)
    _write_job(out_dir / f"{rendered.supernodes['Job']['Name']}.json", rendered.supernodes)
    _write_job(
        out_dir / f"{rendered.superexec_serverapp['Job']['Name']}.json",
        rendered.superexec_serverapp,
    )
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
        "superlink": rendered.superlink["Job"]["Name"],
        "supernodes": rendered.supernodes["Job"]["Name"],
        "superexec-serverapp": rendered.superexec_serverapp["Job"]["Name"],
        "superexec-clientapps": [
            job["Job"]["Name"]
            for job in rendered.superexec_clientapps
            if isinstance(job.get("Job", {}).get("Name"), str)
        ],
    }
    superlink = SuperlinkManifest(
        alloc_id=superlink_alloc.alloc_id,
        node_id=superlink_alloc.node_id,
        ports=superlink_alloc.ports,
    )
    superlink_name = rendered.superlink.get("Job", {}).get("Name", "")
    experiment = (
        superlink_name[: -len("-superlink")] if superlink_name.endswith("-superlink") else ""
    )
    return DeploymentManifest(
        schema_version=1,
        deployment_id=new_deployment_id(),
        experiment=experiment or "experiment",
        jobs=jobs,
        superlink=superlink,
    )
