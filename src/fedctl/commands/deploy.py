from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from fedctl.config.io import load_config
from fedctl.config.repo import load_repo_config, get_image_registry
from fedctl.config.merge import get_effective_config
from fedctl.build.errors import BuildError
from fedctl.build.build import build_image, image_exists
from fedctl.build.dockerfile import render_supernode_dockerfile
from fedctl.build.tagging import supernode_netem_image_tag
import tempfile
from fedctl.build.state import load_latest_build
from fedctl.deploy import naming
from fedctl.deploy.errors import DeployError
from fedctl.deploy.render import RenderedJobs, render_deploy
from fedctl.deploy.network import NetworkPlan, parse_net_assignments, plan_network
from fedctl.deploy.plan import SupernodePlacement, parse_supernodes, plan_supernodes
from fedctl.deploy.resolve import wait_for_superlink
from fedctl.deploy.spec import default_deploy_spec, normalize_experiment_name
from fedctl.deploy.submit import submit_jobs
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError
from fedctl.state.errors import StateError
from fedctl.state.manifest import DeploymentManifest, SuperlinkManifest, new_deployment_id
from fedctl.state.store import write_manifest
from fedctl.project.errors import ProjectError
from fedctl.project.flwr_inspect import inspect_flwr_project
from datetime import datetime, timezone

console = Console()


def run_deploy(
    *,
    dry_run: bool = False,
    out: str | None = None,
    fmt: str = "json",
    num_supernodes: int | None = None,
    supernodes: list[str] | None = None,
    net: list[str] | None = None,
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
        try:
            latest = load_latest_build()
        except BuildError as exc:
            console.print(f"[red]✗ Latest build not available:[/red] {exc}")
            console.print("[yellow]Hint:[/yellow] Run `fedctl build` or pass --image.")
            return 1
        image = latest.image
        console.print(f"[green]✓ Using latest build image:[/green] {image}")

    if fmt != "json":
        console.print(f"[red]✗ Unsupported format:[/red] {fmt}")
        return 1

    if out and not dry_run:
        console.print("[red]✗ --out is only supported with --dry-run.[/red]")
        return 1
    if dry_run and not out:
        out = "rendered"

    repo_cfg = {}
    repo_deploy = {}
    repo_supernodes = {}
    repo_placement = {}
    repo_resources = {}
    repo_supernode_resources = {}
    repo_network = {}
    repo_network_profiles = {}
    repo_network_default = None
    repo_network_scope = None
    repo_network_image = None
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
        repo_network = (
            repo_deploy.get("network", {}) if isinstance(repo_deploy.get("network"), dict) else {}
        )
        repo_network_profiles = (
            repo_network.get("profiles", {})
            if isinstance(repo_network.get("profiles"), dict)
            else {}
        )
        repo_network_default = repo_network.get("default_profile")
        repo_network_scope = repo_network.get("scope")
        repo_network_image = repo_network.get("image")
        repo_allow_oversubscribe = repo_placement.get("allow_oversubscribe")
    else:
        try:
            cfg = load_config()
            profile_name = profile or cfg.active_profile
            profile_cfg = cfg.profiles.get(profile_name)
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
                repo_network = (
                    repo_deploy.get("network", {})
                    if isinstance(repo_deploy.get("network"), dict)
                    else {}
                )
                repo_network_profiles = (
                    repo_network.get("profiles", {})
                    if isinstance(repo_network.get("profiles"), dict)
                    else {}
                )
                repo_network_default = repo_network.get("default_profile")
                repo_network_scope = repo_network.get("scope")
                repo_network_image = repo_network.get("image")
                repo_allow_oversubscribe = repo_placement.get("allow_oversubscribe")
        except Exception:
            pass

    supernodes = supernodes or []
    supernodes_by_type = None
    if supernodes:
        if num_supernodes is not None:
            console.print(
                "[red]✗ Cannot combine --num-supernodes with --supernodes.[/red]"
            )
            return 1
        try:
            supernodes_by_type = parse_supernodes(supernodes)
        except ValueError as exc:
            console.print(f"[red]✗ Invalid --supernodes:[/red] {exc}")
            return 1

    if not supernodes_by_type and repo_supernodes and num_supernodes is None:
        if not _has_untyped_net(net):
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

    if num_supernodes is None:
        num_supernodes = 2

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
        exp_name = _resolve_experiment_name(experiment)
        placements = None
        try:
            network_plan, placements = _resolve_network_plan(
                net=net,
                placements=placements,
                supernodes_by_type=supernodes_by_type,
                num_supernodes=num_supernodes,
                repo_network_profiles=repo_network_profiles,
                repo_network_default=repo_network_default,
                repo_network_scope=repo_network_scope,
            )
        except ValueError as exc:
            console.print(f"[red]✗ Invalid --net:[/red] {exc}")
            return 1
        spec = default_deploy_spec(
            num_supernodes=num_supernodes,
            image=image,
            namespace=namespace or "default",
            experiment=exp_name,
            supernodes_by_type=supernodes_by_type,
            allow_oversubscribe=allow_oversubscribe,
            placements=placements,
            network_plan=network_plan,
            netem_image=repo_network_image if isinstance(repo_network_image, str) else None,
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

    exp_name = _resolve_experiment_name(experiment)
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
            repo_network = (
                repo_deploy.get("network", {})
                if isinstance(repo_deploy.get("network"), dict)
                else {}
            )
            repo_network_profiles = (
                repo_network.get("profiles", {})
                if isinstance(repo_network.get("profiles"), dict)
                else {}
            )
            repo_network_default = repo_network.get("default_profile")
            repo_network_scope = repo_network.get("scope")
            repo_network_image = repo_network.get("image")
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

        try:
            network_plan, network_placements = _resolve_network_plan(
                net=net,
                placements=placements,
                supernodes_by_type=supernodes_by_type,
                num_supernodes=num_supernodes,
                repo_network_profiles=repo_network_profiles,
                repo_network_default=repo_network_default,
                repo_network_scope=repo_network_scope,
            )
        except ValueError as exc:
            console.print(f"[red]✗ Invalid --net:[/red] {exc}")
            return 1
        if network_plan is not None and not repo_network_image:
            console.print("[red]✗ Netem image is required when using --net.[/red]")
            console.print("[yellow]Hint:[/yellow] Set deploy.network.image in repo config.")
            return 1
        if placements is None:
            placements = network_placements

        supernode_image = None
        registry = get_image_registry(repo_cfg)
        if network_plan is not None:
            has_profiles = any(
                isinstance(values, dict) and values
                for values in network_plan.profiles.values()
            )
            if has_profiles:
                flwr_version = "1.23.0"
                supernode_image = supernode_netem_image_tag(flwr_version, registry=registry)
                if not image_exists(supernode_image):
                    console.print(
                        f"[blue]Building supernode netem image:[/blue] {supernode_image}"
                    )
                    dockerfile = render_supernode_dockerfile(flwr_version)
                    with tempfile.TemporaryDirectory() as tmp_dir:
                        dockerfile_path = Path(tmp_dir) / "Dockerfile"
                        dockerfile_path.write_text(dockerfile, encoding="utf-8")
                        build_image(
                            image=supernode_image,
                            dockerfile_path=dockerfile_path,
                            context_dir=Path(tmp_dir),
                            no_cache=False,
                            platform=None,
                            quiet=True,
                        )
                else:
                    console.print(
                        f"[green]✓ Using cached supernode netem image:[/green] {supernode_image}"
                    )
        if network_plan is not None and not has_profiles:
            console.print(
                "[yellow]Note:[/yellow] Network profiles are empty; netem will be disabled."
            )

        spec = default_deploy_spec(
            num_supernodes=num_supernodes,
            image=image,
            namespace=eff.namespace,
            experiment=exp_name,
            supernodes_by_type=supernodes_by_type,
            allow_oversubscribe=allow_oversubscribe,
            placements=placements,
            network_plan=network_plan,
            netem_image=repo_network_image if isinstance(repo_network_image, str) else None,
            supernode_image=supernode_image,
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
            network_plan=network_plan,
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


def _resolve_network_plan(
    *,
    net: list[str] | None,
    placements: list[SupernodePlacement] | None,
    supernodes_by_type: dict[str, int] | None,
    num_supernodes: int,
    repo_network_profiles: dict[str, dict[str, float | int]],
    repo_network_default: str | None,
    repo_network_scope: str | None,
) -> tuple[NetworkPlan | None, list[SupernodePlacement] | None]:
    net_values = net or []
    if not net_values:
        return None, placements
    try:
        assignments = parse_net_assignments(net_values)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    placements_for_network = placements
    if placements_for_network is None:
        if supernodes_by_type:
            placements_for_network = plan_supernodes(
                counts=supernodes_by_type,
                allow_oversubscribe=True,
                nodes=None,
            )
        else:
            placements_for_network = [
                SupernodePlacement(device_type=None, instance_idx=idx, node_id=None)
                for idx in range(1, num_supernodes + 1)
            ]

    plan = plan_network(
        assignments=assignments,
        placements=placements_for_network,
        default_profile=repo_network_default,
        profiles=repo_network_profiles,
        scope=repo_network_scope,
    )
    return plan, placements_for_network


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
    network_plan: NetworkPlan | None,
) -> DeploymentManifest:
    from fedctl.deploy.resolve import SuperlinkAllocation
    from fedctl.state.manifest import (
        SupernodePlacementManifest,
        SupernodesManifest,
        SupernodesNetworkManifest,
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
        network_manifest = None
        if network_plan is not None:
            network_manifest = SupernodesNetworkManifest(
                scope=network_plan.scope,
                default_profile=network_plan.default_profile,
                profiles=network_plan.profiles,
                assignments=network_plan.assignments,
            )
        supernodes_manifest = SupernodesManifest(
            requested_by_type=supernodes_by_type,
            allow_oversubscribe=allow_oversubscribe,
            placements=placement_entries,
            network=network_manifest,
        )

    return DeploymentManifest(
        schema_version=2,
        deployment_id=new_deployment_id(),
        experiment=experiment or "experiment",
        jobs=jobs,
        superlink=superlink,
        supernodes=supernodes_manifest,
    )


def _has_untyped_net(net: list[str] | None) -> bool:
    net_values = net or []
    if not net_values:
        return False
    try:
        assignments = parse_net_assignments(net_values)
    except ValueError:
        return False
    return any(assignment.device_type is None for assignment in assignments)


def _resolve_experiment_name(value: str | None) -> str:
    if value:
        return normalize_experiment_name(value)
    try:
        info = inspect_flwr_project(Path.cwd())
        project_name = info.project_name or "project"
        return normalize_experiment_name(f"{project_name}-{_timestamp_compact()}")
    except ProjectError:
        return normalize_experiment_name("experiment")


def _timestamp_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
