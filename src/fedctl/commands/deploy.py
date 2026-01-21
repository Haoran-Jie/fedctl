from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from fedctl.config.io import load_config
from fedctl.config.repo import load_repo_config
from fedctl.config.merge import get_effective_config
from fedctl.deploy import naming
from fedctl.deploy.errors import DeployError
from fedctl.deploy.render import RenderedJobs, render_deploy
from fedctl.deploy.plan import parse_supernodes, plan_supernodes
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
    supernodes: list[str] | None = None,
    allow_oversubscribe: bool | None = None,
    repo_config: str | None = None,
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

    repo_cfg = {}
    repo_deploy = {}
    repo_supernodes = {}
    repo_placement = {}
    repo_resources = {}
    repo_supernode_resources = {}
    repo_allow_oversubscribe = None
    if repo_config:
        repo_cfg = load_repo_config(config_path=Path(repo_config))
        repo_deploy = (
            repo_cfg.get("deploy", {}) if isinstance(repo_cfg.get("deploy"), dict) else {}
        )
        repo_supernodes = (
            repo_deploy.get("supernodes", {})
            if isinstance(repo_deploy.get("supernodes"), dict)
            else {}
        )
        repo_placement = (
            repo_deploy.get("placement", {})
            if isinstance(repo_deploy.get("placement"), dict)
            else {}
        )
        repo_resources = (
            repo_deploy.get("resources", {})
            if isinstance(repo_deploy.get("resources"), dict)
            else {}
        )
        repo_supernode_resources = (
            repo_resources.get("supernode", {})
            if isinstance(repo_resources.get("supernode"), dict)
            else {}
        )
        repo_allow_oversubscribe = repo_placement.get("allow_oversubscribe")

    supernodes = supernodes or []
    supernodes_by_type = None
    if supernodes:
        if num_supernodes != 2:
            console.print(
                "[red]✗ Cannot combine --num-supernodes with --supernodes.[/red]"
            )
            return 1
        try:
            supernodes_by_type = parse_supernodes(supernodes)
        except ValueError as exc:
            console.print(f"[red]✗ Invalid --supernodes:[/red] {exc}")
            return 1

    if not supernodes_by_type and repo_supernodes:
        supernodes_by_type = {
            str(k): int(v) for k, v in repo_supernodes.items() if int(v) >= 0
        }

    if allow_oversubscribe is None:
        allow_oversubscribe = bool(repo_allow_oversubscribe)

    if dry_run and supernodes_by_type and not allow_oversubscribe:
        console.print(
            "[red]✗ Non-oversubscribed placement requires live inventory (no dry-run).[/red]"
        )
        return 1

    default_resources = None
    resources_by_type = None
    if repo_supernode_resources:
        default_cfg = repo_supernode_resources.get("default")
        if isinstance(default_cfg, dict):
            cpu = int(default_cfg.get("cpu", 0) or 0)
            mem = int(default_cfg.get("mem", 0) or 0)
            if cpu > 0 and mem > 0:
                default_resources = {"cpu": cpu, "mem": mem}
        resources_by_type = {}
        for key, val in repo_supernode_resources.items():
            if key == "default" or not isinstance(val, dict):
                continue
            cpu = int(val.get("cpu", 0) or 0)
            mem = int(val.get("mem", 0) or 0)
            if cpu > 0 and mem > 0:
                resources_by_type[str(key)] = {"cpu": cpu, "mem": mem}
        if not resources_by_type:
            resources_by_type = None

    if dry_run:
        exp_name = normalize_experiment_name(experiment or "experiment")
        spec = default_deploy_spec(
            num_supernodes=num_supernodes,
            image=image,
            namespace=namespace or "default",
            experiment=exp_name,
            supernodes_by_type=supernodes_by_type,
            allow_oversubscribe=allow_oversubscribe,
            resources_by_type=resources_by_type,
            default_resources=default_resources,
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

    if not eff.namespace:
        console.print("[red]✗ Namespace is required.[/red] Use --namespace or set profile.")
        return 1

    exp_name = normalize_experiment_name(experiment or "experiment")
    if not repo_config:
        profile_cfg = cfg.profiles.get(eff.profile_name)
        if profile_cfg and profile_cfg.repo_config:
            repo_cfg = load_repo_config(config_path=Path(profile_cfg.repo_config))
            repo_deploy = (
                repo_cfg.get("deploy", {})
                if isinstance(repo_cfg.get("deploy"), dict)
                else {}
            )
            repo_supernodes = (
                repo_deploy.get("supernodes", {})
                if isinstance(repo_deploy.get("supernodes"), dict)
                else {}
            )
            repo_placement = (
                repo_deploy.get("placement", {})
                if isinstance(repo_deploy.get("placement"), dict)
                else {}
            )
            repo_resources = (
                repo_deploy.get("resources", {})
                if isinstance(repo_deploy.get("resources"), dict)
                else {}
            )
            repo_supernode_resources = (
                repo_resources.get("supernode", {})
                if isinstance(repo_resources.get("supernode"), dict)
                else {}
            )
            repo_allow_oversubscribe = repo_placement.get("allow_oversubscribe")
    client = NomadClient(eff)
    try:
        if not eff.nomad_token and client.acl_enabled():
            console.print("[red]✗ Nomad token is required when ACLs are enabled.[/red]")
            console.print("[yellow]Hint:[/yellow] Set NOMAD_TOKEN or configure a profile token.")
            return 1

        placements = None
        if supernodes_by_type:
            nodes = None if allow_oversubscribe else client.nodes()
            try:
                placements = plan_supernodes(
                    counts=supernodes_by_type,
                    allow_oversubscribe=allow_oversubscribe,
                    nodes=nodes if isinstance(nodes, list) else None,
                )
            except ValueError as exc:
                console.print(f"[red]✗ Placement error:[/red] {exc}")
                return 1

        spec = default_deploy_spec(
            num_supernodes=num_supernodes,
            image=image,
            namespace=eff.namespace,
            experiment=exp_name,
            supernodes_by_type=supernodes_by_type,
            allow_oversubscribe=allow_oversubscribe,
            placements=placements,
            resources_by_type=resources_by_type,
            default_resources=default_resources,
        )
        try:
            rendered = render_deploy(spec)
        except Exception as exc:
            console.print(f"[red]✗ Render error:[/red] {exc}")
            return 1

        submit_jobs(client, rendered)
        if no_wait:
            console.print("[green]✓ Submitted jobs.[/green] Skipping wait/manifest.")
            return 0

        superlink_alloc = wait_for_superlink(
            client,
            job_name=rendered.superlink["Job"]["Name"],
            timeout_seconds=timeout_seconds,
        )
        manifest = _build_manifest(
            rendered,
            superlink_alloc,
            supernodes_by_type=supernodes_by_type,
            allow_oversubscribe=allow_oversubscribe,
            placements=placements,
        )
        path = write_manifest(
            manifest,
            namespace=eff.namespace,
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
    *,
    supernodes_by_type: dict[str, int] | None,
    allow_oversubscribe: bool,
    placements: list[object] | None,
) -> DeploymentManifest:
    from fedctl.deploy.resolve import SuperlinkAllocation
    from fedctl.state.manifest import (
        SupernodePlacementManifest,
        SupernodesManifest,
    )

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
    supernodes_manifest = None
    if placements is not None:
        placement_entries = []
        for placement in placements:
            device_type = getattr(placement, "device_type", None)
            instance_idx = getattr(placement, "instance_idx", None)
            node_id = getattr(placement, "node_id", None)
            if isinstance(instance_idx, int):
                placement_entries.append(
                    SupernodePlacementManifest(
                        device_type=device_type if isinstance(device_type, str) else None,
                        instance_idx=instance_idx,
                        node_id=node_id if isinstance(node_id, str) else None,
                    )
                )
        supernodes_manifest = SupernodesManifest(
            requested_by_type=supernodes_by_type,
            allow_oversubscribe=allow_oversubscribe,
            placements=placement_entries,
        )

    return DeploymentManifest(
        schema_version=1,
        deployment_id=new_deployment_id(),
        experiment=experiment or "experiment",
        jobs=jobs,
        superlink=superlink,
        supernodes=supernodes_manifest,
    )
