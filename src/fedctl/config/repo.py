from __future__ import annotations

from pathlib import Path

from .deploy import (
    ResolvedDeployConfig,
    SubmitDeployConfig,
    get_cluster_image_registry,
    get_deploy_config_label,
    get_deploy_network_profile_label,
    get_image_registry,
    load_deploy_config,
    parse_submit_deploy_config,
    resolve_deploy_config,
    resolve_deploy_config_path,
    rewrite_image_registry,
)

ResolvedRepoConfig = ResolvedDeployConfig
SubmitRepoConfig = SubmitDeployConfig


def load_repo_config(
    base: Path | None = None, config_path: Path | None = None
) -> dict[str, object]:
    return load_deploy_config(base=base, config_path=config_path)


def resolve_repo_config(
    *,
    repo_config: str | Path | None = None,
    project_root: Path | None = None,
    profile_name: str | None = None,
    include_project_local: bool = False,
    include_profile: bool = False,
) -> ResolvedDeployConfig:
    return resolve_deploy_config(
        deploy_config=repo_config,
        project_root=project_root,
        profile_name=profile_name,
        include_project_local=include_project_local,
        include_profile=include_profile,
    )


def resolve_repo_config_path(
    *,
    repo_config: str | Path | None = None,
    project_root: Path | None = None,
    profile_name: str | None = None,
    include_project_local: bool = False,
    include_profile: bool = False,
) -> Path | None:
    return resolve_deploy_config_path(
        deploy_config=repo_config,
        project_root=project_root,
        profile_name=profile_name,
        include_project_local=include_project_local,
        include_profile=include_profile,
    )


def parse_submit_repo_config(repo_cfg: dict[str, object]) -> SubmitDeployConfig:
    return parse_submit_deploy_config(repo_cfg)


def get_repo_config_label(
    repo_cfg: dict[str, object], *, path: Path | None = None
) -> str:
    return get_deploy_config_label(repo_cfg, path=path)


def get_repo_network_profile_label(repo_cfg: dict[str, object]) -> str | None:
    return get_deploy_network_profile_label(repo_cfg)
