from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from fedctl.config.io import load_config
from fedctl.config.repo import (
    get_cluster_image_registry,
    get_image_registry,
    get_repo_config_label,
    rewrite_image_registry,
    resolve_repo_config,
)
from fedctl.config.merge import get_effective_config
from fedctl.build.errors import BuildError
from fedctl.build.build import build_image, image_exists
from fedctl.build.push import push_image
from fedctl.build.dockerfile import render_supernode_dockerfile
from fedctl.build.tagging import supernode_netem_image_tag
import tempfile
from fedctl.build.state import load_latest_build
from fedctl.constants import DEFAULT_FLWR_VERSION
from fedctl.deploy import naming
from fedctl.deploy.errors import DeployError
from fedctl.deploy.render import RenderedJobs, render_deploy
from fedctl.deploy.network import NetworkPlan, parse_net_assignments, plan_network
from fedctl.deploy.plan import SupernodePlacement, parse_supernodes, plan_supernodes
from fedctl.deploy.resolve import wait_for_superlink, wait_for_supernodes
from fedctl.deploy.spec import default_deploy_spec, normalize_experiment_name
from fedctl.deploy.submit import (
    submit_jobs,
    submit_superexec_jobs,
    submit_superlink_job,
    submit_supernodes_job,
)
from fedctl.nomad.client import NomadClient
from fedctl.nomad.errors import NomadConnectionError, NomadHTTPError, NomadTLSError
from fedctl.state.errors import StateError
from fedctl.state.manifest import DeploymentManifest, SuperlinkManifest, new_deployment_id
from fedctl.state.store import write_manifest
from fedctl.project.errors import ProjectError
from fedctl.project.flwr_inspect import inspect_flwr_project
from fedctl.util.console import console
from datetime import datetime, timezone


@dataclass(frozen=True)
class _RepoDeployConfig:
    supernodes: dict[str, object]
    supernode_resources: dict[str, object]
    superexec_clientapp_resources: dict[str, object]
    superexec_serverapp_resources: dict[str, object]
    superlink_resources: dict[str, object]
    superexec_env: dict[str, str]
    network_profiles: dict[str, object]
    network_ingress_profiles: dict[str, object]
    network_egress_profiles: dict[str, object]
    network_default: str | None
    network_default_assignment: list[str] | None
    network_interface: str | None
    network_image: str | None
    network_apply: dict[str, object]
    allow_oversubscribe: object
    spread_across_hosts: object
    prefer_spread_across_hosts: object


_RUNTIME_SUPEREXEC_ENV_KEYS = (
    "FEDCTL_ATTEMPT_STARTED_AT",
    "FEDCTL_EXPERIMENT_CONFIG",
    "FEDCTL_REPO_CONFIG_LABEL",
    "FEDCTL_SUBMISSION_ID",
)

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
    flwr_version: str = DEFAULT_FLWR_VERSION,
    experiment: str | None = None,
    timeout_seconds: int = 120,
    no_wait: bool = False,
    profile: str | None = None,
    endpoint: str | None = None,
    namespace: str | None = None,
    token: str | None = None,
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

    repo_resolution = resolve_repo_config(
        repo_config=repo_config,
        profile_name=profile,
        include_profile=True,
    )
    repo_cfg = repo_resolution.data
    external_registry = get_image_registry(repo_cfg)
    internal_registry = get_cluster_image_registry(repo_cfg)
    cluster_image = rewrite_image_registry(
        image,
        source_registry=external_registry,
        target_registry=internal_registry,
    )
    repo_defaults = _repo_deploy_config(repo_cfg)
    repo_supernodes = repo_defaults.supernodes
    repo_supernode_resources = repo_defaults.supernode_resources
    repo_superexec_clientapp_resources = repo_defaults.superexec_clientapp_resources
    repo_superexec_serverapp_resources = repo_defaults.superexec_serverapp_resources
    repo_superlink_resources = repo_defaults.superlink_resources
    repo_superexec_env = repo_defaults.superexec_env
    runtime_superexec_env = _runtime_superexec_env(
        repo_config_label=get_repo_config_label(repo_cfg, path=repo_resolution.path)
    )
    if runtime_superexec_env:
        repo_superexec_env = {**repo_superexec_env, **runtime_superexec_env}
    repo_network_profiles = repo_defaults.network_profiles
    repo_network_ingress_profiles = repo_defaults.network_ingress_profiles
    repo_network_egress_profiles = repo_defaults.network_egress_profiles
    repo_network_default = repo_defaults.network_default
    repo_network_default_assignment = repo_defaults.network_default_assignment
    repo_network_interface = repo_defaults.network_interface
    repo_network_image = repo_defaults.network_image
    repo_network_apply = repo_defaults.network_apply
    repo_allow_oversubscribe = repo_defaults.allow_oversubscribe
    repo_spread_across_hosts = repo_defaults.spread_across_hosts
    repo_prefer_spread_across_hosts = repo_defaults.prefer_spread_across_hosts

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
        if not _has_untyped_net(net) and not (
            not net and _has_untyped_net(repo_network_default_assignment)
        ):
            supernodes_by_type = {
                str(k): int(v) for k, v in repo_supernodes.items() if int(v) >= 0
            }

    if allow_oversubscribe is None:
        allow_oversubscribe = bool(repo_allow_oversubscribe)
    spread_across_hosts = bool(repo_spread_across_hosts)
    prefer_spread_across_hosts = bool(repo_prefer_spread_across_hosts)

    netem_serverapp = True
    netem_clientapp = True
    if isinstance(repo_network_apply, dict):
        if "superexec_serverapp" in repo_network_apply:
            netem_serverapp = bool(repo_network_apply.get("superexec_serverapp"))
        if "superexec_clientapp" in repo_network_apply:
            netem_clientapp = bool(repo_network_apply.get("superexec_clientapp"))

    if dry_run and supernodes_by_type and (
        not allow_oversubscribe or spread_across_hosts or prefer_spread_across_hosts
    ):
        console.print(
            "[red]✗ Host-pinned placement requires live inventory (no dry-run).[/red]"
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
    superexec_clientapp_resources = _normalize_single_resource(
        repo_superexec_clientapp_resources,
        default_cpu=1000,
        default_mem=1024,
    )
    superexec_serverapp_resources = _normalize_single_resource(
        repo_superexec_serverapp_resources,
        default_cpu=1000,
        default_mem=1024,
    )
    superlink_resources = _normalize_single_resource(
        repo_superlink_resources,
        default_cpu=500,
        default_mem=256,
    )

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
                repo_network_ingress_profiles=repo_network_ingress_profiles,
                repo_network_egress_profiles=repo_network_egress_profiles,
                repo_network_default=repo_network_default,
                repo_network_default_assignment=repo_network_default_assignment,
                repo_network_interface=repo_network_interface,
            )
        except ValueError as exc:
            console.print(f"[red]✗ Invalid network configuration:[/red] {exc}")
            return 1
        spec = default_deploy_spec(
            num_supernodes=num_supernodes,
            image=cluster_image,
            flwr_version=flwr_version,
            namespace=namespace or "default",
            experiment=exp_name,
            supernodes_by_type=supernodes_by_type,
            allow_oversubscribe=allow_oversubscribe,
            prefer_spread_across_hosts=prefer_spread_across_hosts,
            placements=placements,
            network_plan=network_plan,
            netem_image=repo_network_image if isinstance(repo_network_image, str) else None,
            resources_by_type=resources_by_type,
            default_resources=default_resources,
            superlink_resources=superlink_resources,
            superexec_serverapp_resources=superexec_serverapp_resources,
            superexec_clientapp_resources=superexec_clientapp_resources,
            netem_serverapp=netem_serverapp,
            netem_clientapp=netem_clientapp,
            superexec_env=repo_superexec_env,
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
        )
    except ValueError as exc:
        console.print(f"[red]✗ Config error:[/red] {exc}")
        return 1

    if not eff.namespace:
        console.print("[red]✗ Namespace is required.[/red] Use --namespace or set profile.")
        return 1

    exp_name = _resolve_experiment_name(experiment)
    client = NomadClient(eff)
    try:
        if not eff.nomad_token and client.acl_enabled():
            console.print("[red]✗ Nomad token is required when ACLs are enabled.[/red]")
            console.print("[yellow]Hint:[/yellow] Set NOMAD_TOKEN or configure a profile token.")
            return 1

        placements = None
        if supernodes_by_type:
            needs_inventory = spread_across_hosts or not allow_oversubscribe or prefer_spread_across_hosts
            nodes = client.nodes(detailed=True) if needs_inventory else None
            try:
                placements = plan_supernodes(
                    counts=supernodes_by_type,
                    allow_oversubscribe=allow_oversubscribe,
                    spread_across_hosts=spread_across_hosts,
                    prefer_spread_across_hosts=prefer_spread_across_hosts,
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
                repo_network_ingress_profiles=repo_network_ingress_profiles,
                repo_network_egress_profiles=repo_network_egress_profiles,
                repo_network_default=repo_network_default,
                repo_network_default_assignment=repo_network_default_assignment,
                repo_network_interface=repo_network_interface,
            )
        except ValueError as exc:
            console.print(f"[red]✗ Invalid network configuration:[/red] {exc}")
            return 1
        if network_plan is not None and not repo_network_image:
            console.print("[red]✗ Netem image is required when network emulation is enabled.[/red]")
            console.print("[yellow]Hint:[/yellow] Set deploy.network.image in repo config.")
            return 1
        if placements is None:
            placements = network_placements

        supernode_image = None
        if network_plan is not None:
            has_profiles = any(
                isinstance(values, dict) and values
                for values in (
                    *network_plan.profiles.values(),
                    *network_plan.ingress_profiles.values(),
                    *network_plan.egress_profiles.values(),
                )
            )
            if has_profiles:
                supernode_image_external = supernode_netem_image_tag(
                    flwr_version, registry=external_registry
                )
                if not image_exists(supernode_image_external):
                    console.print(
                        f"[blue]Building supernode netem image:[/blue] {supernode_image_external}"
                    )
                    dockerfile = render_supernode_dockerfile(flwr_version)
                    with tempfile.TemporaryDirectory() as tmp_dir:
                        dockerfile_path = Path(tmp_dir) / "Dockerfile"
                        dockerfile_path.write_text(dockerfile, encoding="utf-8")
                        build_image(
                            image=supernode_image_external,
                            dockerfile_path=dockerfile_path,
                            context_dir=Path(tmp_dir),
                            no_cache=False,
                            platform=None,
                            quiet=True,
                        )
                else:
                    console.print(
                        "[green]✓ Using cached supernode netem image:[/green] "
                        f"{supernode_image_external}"
                    )
                if external_registry:
                    console.print(
                        f"Pushing supernode netem image: {supernode_image_external}"
                    )
                    push_image(supernode_image_external)
                    console.print(
                        "[green]✓ Pushed supernode netem image:[/green] "
                        f"{supernode_image_external}"
                    )
                supernode_image = rewrite_image_registry(
                    supernode_image_external,
                    source_registry=external_registry,
                    target_registry=internal_registry,
                )
        if network_plan is not None and not has_profiles:
            console.print(
                "[yellow]Note:[/yellow] Network profiles are empty; netem will be disabled."
            )

        spec = default_deploy_spec(
            num_supernodes=num_supernodes,
            image=cluster_image,
            flwr_version=flwr_version,
            namespace=eff.namespace,
            experiment=exp_name,
            supernodes_by_type=supernodes_by_type,
            allow_oversubscribe=allow_oversubscribe,
            prefer_spread_across_hosts=prefer_spread_across_hosts,
            placements=placements,
            network_plan=network_plan,
            netem_image=repo_network_image if isinstance(repo_network_image, str) else None,
            supernode_image=supernode_image,
            resources_by_type=resources_by_type,
            default_resources=default_resources,
            superlink_resources=superlink_resources,
            superexec_serverapp_resources=superexec_serverapp_resources,
            superexec_clientapp_resources=superexec_clientapp_resources,
            netem_serverapp=netem_serverapp,
            netem_clientapp=netem_clientapp,
            superexec_env=repo_superexec_env,
        )
        try:
            rendered = render_deploy(spec)
        except Exception as exc:
            console.print(f"[red]✗ Render error:[/red] {exc}")
            return 1

        if no_wait:
            submit_jobs(client, rendered)
            console.print("[green]✓ Submitted jobs.[/green] Skipping wait/manifest.")
            return 0

        superlink_job_name = submit_superlink_job(client, rendered)
        superlink_alloc = wait_for_superlink(
            client,
            job_name=superlink_job_name or rendered.superlink["Job"]["Name"],
            timeout_seconds=timeout_seconds,
        )

        supernodes_job_name = submit_supernodes_job(client, rendered)
        wait_for_supernodes(
            client,
            job_name=supernodes_job_name or rendered.supernodes["Job"]["Name"],
            expected_allocs=len(rendered.superexec_clientapps),
            timeout_seconds=timeout_seconds,
        )

        submit_superexec_jobs(client, rendered)
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
        console.print("[green]✓ Deployment ready.[/green]")
        console.print(f"[cyan]Manifest:[/cyan] {path}")
        return 0

    except DeployError as exc:
        console.print(f"[red]✗ Deploy error:[/red] {exc}")
        return 1

    except BuildError as exc:
        console.print(f"[red]✗ Build error:[/red] {exc}")
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


def _repo_deploy_config(repo_cfg: dict[str, object]) -> _RepoDeployConfig:
    deploy = _as_dict(repo_cfg.get("deploy"))
    supernodes = _as_dict(deploy.get("supernodes"))
    placement = _as_dict(deploy.get("placement"))
    resources = _as_dict(deploy.get("resources"))
    superexec = _as_dict(deploy.get("superexec"))
    superexec_env = _as_string_dict(_as_dict(superexec.get("env")))
    supernode_resources = _as_dict(resources.get("supernode"))
    superexec_clientapp_resources = _as_dict(resources.get("superexec_clientapp"))
    superexec_serverapp_resources = _as_dict(resources.get("superexec_serverapp"))
    superlink_resources = _as_dict(resources.get("superlink"))
    network = _as_dict(deploy.get("network"))
    network_profiles = _as_dict(network.get("profiles"))
    network_ingress_profiles = _as_dict(network.get("ingress_profiles"))
    network_egress_profiles = _as_dict(network.get("egress_profiles"))
    network_apply = _as_dict(network.get("apply"))
    return _RepoDeployConfig(
        supernodes=supernodes,
        supernode_resources=supernode_resources,
        superexec_clientapp_resources=superexec_clientapp_resources,
        superexec_serverapp_resources=superexec_serverapp_resources,
        superlink_resources=superlink_resources,
        superexec_env=superexec_env,
        network_profiles=network_profiles,
        network_ingress_profiles=network_ingress_profiles,
        network_egress_profiles=network_egress_profiles,
        network_default=_as_optional_str(network.get("default_profile")),
        network_default_assignment=_as_optional_str_list(network.get("default_assignment")),
        network_interface=_as_optional_str(network.get("interface")),
        network_image=_as_optional_str(network.get("image")),
        network_apply=network_apply,
        allow_oversubscribe=placement.get("allow_oversubscribe"),
        spread_across_hosts=placement.get("spread_across_hosts"),
        prefer_spread_across_hosts=placement.get("prefer_spread_across_hosts"),
    )


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _as_optional_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _as_optional_str_list(value: object) -> list[str] | None:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else None
    if isinstance(value, list):
        result = [str(item).strip() for item in value if str(item).strip()]
        return result or None
    return None


def _as_string_dict(value: dict[str, object]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or not key:
            continue
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            resolved[key] = text
    return resolved


def _normalize_single_resource(
    raw: dict[str, object],
    *,
    default_cpu: int,
    default_mem: int,
) -> dict[str, int]:
    source = raw
    nested_default = _as_dict(raw.get("default"))
    if nested_default:
        source = nested_default
    cpu = source.get("cpu", default_cpu)
    mem = source.get("mem", default_mem)
    return {"cpu": int(cpu), "mem": int(mem)}


def _runtime_superexec_env(*, repo_config_label: str | None = None) -> dict[str, str]:
    env: dict[str, str] = {}
    submission_id = os.environ.get("FEDCTL_SUBMISSION_ID") or os.environ.get(
        "SUBMIT_SUBMISSION_ID"
    )
    if submission_id:
        env["FEDCTL_SUBMISSION_ID"] = str(submission_id)
    for key in _RUNTIME_SUPEREXEC_ENV_KEYS:
        if key == "FEDCTL_SUBMISSION_ID":
            continue
        if key == "FEDCTL_REPO_CONFIG_LABEL" and repo_config_label:
            env[key] = repo_config_label
            continue
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _resolve_network_plan(
    *,
    net: list[str] | None,
    placements: list[SupernodePlacement] | None,
    supernodes_by_type: dict[str, int] | None,
    num_supernodes: int,
    repo_network_profiles: dict[str, object],
    repo_network_ingress_profiles: dict[str, object],
    repo_network_egress_profiles: dict[str, object],
    repo_network_default: str | None,
    repo_network_default_assignment: list[str] | None,
    repo_network_interface: str | None,
) -> tuple[NetworkPlan | None, list[SupernodePlacement] | None]:
    net_values = net or repo_network_default_assignment or []
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

    profiles = {k: v for k, v in repo_network_profiles.items() if isinstance(v, dict)}
    ingress_profiles = {
        k: v for k, v in repo_network_ingress_profiles.items() if isinstance(v, dict)
    }
    egress_profiles = {
        k: v for k, v in repo_network_egress_profiles.items() if isinstance(v, dict)
    }
    plan = plan_network(
        assignments=assignments,
        placements=placements_for_network,
        default_profile=repo_network_default,
        interface=repo_network_interface,
        profiles=profiles,
        ingress_profiles=ingress_profiles,
        egress_profiles=egress_profiles,
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
                default_profile=network_plan.default_profile,
                interface=network_plan.interface,
                profiles=network_plan.profiles,
                assignments=network_plan.assignments,
                ingress_profiles=network_plan.ingress_profiles,
                egress_profiles=network_plan.egress_profiles,
                ingress_assignments=network_plan.ingress_assignments,
                egress_assignments=network_plan.egress_assignments,
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
