from __future__ import annotations

from pathlib import Path

from fedctl.commands.deploy import _repo_deploy_config
from fedctl.config.io import ensure_config_exists, load_raw_toml, save_raw_toml
from fedctl.config.repo import (
    get_cluster_image_registry,
    get_image_registry,
    load_repo_config,
    resolve_repo_config,
    resolve_repo_config_path,
    rewrite_image_registry,
)


def _use_tmp_xdg(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


def _set_default_profile_repo_config(path: Path) -> None:
    doc = load_raw_toml()
    doc["profiles"]["default"]["repo_config"] = str(path)
    save_raw_toml(doc)


def test_resolve_repo_config_path_prefers_explicit(tmp_path: Path, monkeypatch) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    ensure_config_exists()

    project_cfg = tmp_path / "proj" / ".fedctl" / "fedctl.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text("submit:\n  image: project/image:latest\n", encoding="utf-8")

    profile_cfg = tmp_path / "profile-fedctl.yaml"
    profile_cfg.write_text("submit:\n  image: profile/image:latest\n", encoding="utf-8")
    _set_default_profile_repo_config(profile_cfg)

    explicit_cfg = tmp_path / "explicit-fedctl.yaml"
    explicit_cfg.write_text("submit:\n  image: explicit/image:latest\n", encoding="utf-8")

    resolved = resolve_repo_config_path(
        repo_config=str(explicit_cfg),
        project_root=tmp_path / "proj",
        include_project_local=True,
        include_profile=True,
    )
    assert resolved == explicit_cfg.resolve()


def test_resolve_repo_config_path_uses_project_before_profile(
    tmp_path: Path, monkeypatch
) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    ensure_config_exists()

    project_cfg = tmp_path / "proj" / ".fedctl" / "fedctl.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text("submit:\n  image: project/image:latest\n", encoding="utf-8")

    profile_cfg = tmp_path / "profile-fedctl.yaml"
    profile_cfg.write_text("submit:\n  image: profile/image:latest\n", encoding="utf-8")
    _set_default_profile_repo_config(profile_cfg)

    resolved = resolve_repo_config_path(
        project_root=tmp_path / "proj",
        include_project_local=True,
        include_profile=True,
    )
    assert resolved == project_cfg.resolve()


def test_resolve_repo_config_path_uses_profile_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    ensure_config_exists()

    profile_cfg = tmp_path / "profile-fedctl.yaml"
    profile_cfg.write_text("submit:\n  image: profile/image:latest\n", encoding="utf-8")
    _set_default_profile_repo_config(profile_cfg)

    resolved = resolve_repo_config_path(
        include_profile=True,
    )
    assert resolved == profile_cfg.resolve()


def test_explicit_missing_repo_config_disables_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    ensure_config_exists()

    profile_cfg = tmp_path / "profile-fedctl.yaml"
    profile_cfg.write_text("submit:\n  image: profile/image:latest\n", encoding="utf-8")
    _set_default_profile_repo_config(profile_cfg)

    missing_cfg = tmp_path / "missing-fedctl.yaml"
    resolved = resolve_repo_config(
        repo_config=str(missing_cfg),
        include_profile=True,
    )
    assert resolved.path is None
    assert resolved.data == {}


def test_cluster_image_registry_prefers_submit_service_section() -> None:
    repo_cfg = {
        "image_registry": "100.108.13.23:5000",
        "submit-service": {"image_registry": "192.168.8.101:5000"},
    }

    assert get_image_registry(repo_cfg) == "100.108.13.23:5000"
    assert get_cluster_image_registry(repo_cfg) == "192.168.8.101:5000"


def test_rewrite_image_registry_only_rewrites_matching_source() -> None:
    image = "100.108.13.23:5000/demo-superexec:abc123"

    assert (
        rewrite_image_registry(
            image,
            source_registry="100.108.13.23:5000",
            target_registry="192.168.8.101:5000",
        )
        == "192.168.8.101:5000/demo-superexec:abc123"
    )
    assert (
        rewrite_image_registry(
            "docker.io/library/python:3.12",
            source_registry="100.108.13.23:5000",
            target_registry="192.168.8.101:5000",
        )
        == "docker.io/library/python:3.12"
    )


def test_load_repo_config_preserves_superexec_env_map(tmp_path: Path) -> None:
    repo_cfg = tmp_path / "fedctl.yaml"
    repo_cfg.write_text(
        "deploy:\n"
        "  superexec:\n"
        "    env:\n"
        "      WANDB_PROJECT: fedctl\n"
        "      WANDB_ENTITY: samueljie\n",
        encoding="utf-8",
    )

    loaded = load_repo_config(config_path=repo_cfg)

    assert loaded["deploy"]["superexec"]["env"] == {
        "WANDB_PROJECT": "fedctl",
        "WANDB_ENTITY": "samueljie",
    }


def test_repo_deploy_config_extracts_superexec_env_map() -> None:
    repo_defaults = _repo_deploy_config(
        {
            "deploy": {
                "superexec": {
                    "env": {
                        "WANDB_PROJECT": "fedctl",
                        "WANDB_ENTITY": "samueljie",
                        "EMPTY": "",
                    }
                }
            }
        }
    )

    assert repo_defaults.superexec_env == {
        "WANDB_PROJECT": "fedctl",
        "WANDB_ENTITY": "samueljie",
    }
