from __future__ import annotations

from pathlib import Path

from fedctl.commands.deploy import _deploy_config_defaults, _runtime_superexec_env
from fedctl.config.io import ensure_config_exists, load_raw_toml, save_raw_toml
from fedctl.config.deploy import (
    get_cluster_image_registry,
    get_image_registry,
    get_deploy_config_label,
    get_deploy_network_profile_label,
    load_deploy_config,
    resolve_deploy_config,
    resolve_deploy_config_path,
    rewrite_image_registry,
)


def _use_tmp_xdg(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))


def _set_default_profile_deploy_config(path: Path) -> None:
    doc = load_raw_toml()
    doc["profiles"]["default"]["deploy_config"] = str(path)
    save_raw_toml(doc)


def test_resolve_deploy_config_path_prefers_explicit(tmp_path: Path, monkeypatch) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    ensure_config_exists()

    project_cfg = tmp_path / "proj" / ".fedctl" / "fedctl.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text("submit:\n  image: project/image:latest\n", encoding="utf-8")

    profile_cfg = tmp_path / "profile-fedctl.yaml"
    profile_cfg.write_text("submit:\n  image: profile/image:latest\n", encoding="utf-8")
    _set_default_profile_deploy_config(profile_cfg)

    explicit_cfg = tmp_path / "explicit-fedctl.yaml"
    explicit_cfg.write_text("submit:\n  image: explicit/image:latest\n", encoding="utf-8")

    resolved = resolve_deploy_config_path(
        deploy_config=str(explicit_cfg),
        project_root=tmp_path / "proj",
        include_project_local=True,
        include_profile=True,
    )
    assert resolved == explicit_cfg.resolve()


def test_resolve_deploy_config_path_uses_project_before_profile(
    tmp_path: Path, monkeypatch
) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    ensure_config_exists()

    project_cfg = tmp_path / "proj" / ".fedctl" / "fedctl.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text("submit:\n  image: project/image:latest\n", encoding="utf-8")

    profile_cfg = tmp_path / "profile-fedctl.yaml"
    profile_cfg.write_text("submit:\n  image: profile/image:latest\n", encoding="utf-8")
    _set_default_profile_deploy_config(profile_cfg)

    resolved = resolve_deploy_config_path(
        project_root=tmp_path / "proj",
        include_project_local=True,
        include_profile=True,
    )
    assert resolved == project_cfg.resolve()


def test_resolve_deploy_config_path_uses_profile_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    ensure_config_exists()

    profile_cfg = tmp_path / "profile-fedctl.yaml"
    profile_cfg.write_text("submit:\n  image: profile/image:latest\n", encoding="utf-8")
    _set_default_profile_deploy_config(profile_cfg)

    resolved = resolve_deploy_config_path(
        include_profile=True,
    )
    assert resolved == profile_cfg.resolve()


def test_explicit_missing_deploy_config_disables_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    _use_tmp_xdg(monkeypatch, tmp_path)
    ensure_config_exists()

    profile_cfg = tmp_path / "profile-fedctl.yaml"
    profile_cfg.write_text("submit:\n  image: profile/image:latest\n", encoding="utf-8")
    _set_default_profile_deploy_config(profile_cfg)

    missing_cfg = tmp_path / "missing-fedctl.yaml"
    resolved = resolve_deploy_config(
        deploy_config=str(missing_cfg),
        include_profile=True,
    )
    assert resolved.path is None
    assert resolved.data == {}


def test_cluster_image_registry_defaults_to_image_registry() -> None:
    deploy_cfg = {"deploy": {"image_registry": "100.108.13.23:5000"}}

    assert get_image_registry(deploy_cfg) == "100.108.13.23:5000"
    assert get_cluster_image_registry(deploy_cfg) == "100.108.13.23:5000"


def test_image_registry_accepts_legacy_top_level_key() -> None:
    deploy_cfg = {"image_registry": "100.108.13.23:5000"}

    assert get_image_registry(deploy_cfg) == "100.108.13.23:5000"


def test_cluster_image_registry_accepts_legacy_submit_service_override() -> None:
    deploy_cfg = {
        "image_registry": "100.108.13.23:5000",
        "submit-service": {"image_registry": "192.168.8.101:5000"},
    }

    assert get_image_registry(deploy_cfg) == "100.108.13.23:5000"
    assert get_cluster_image_registry(deploy_cfg) == "192.168.8.101:5000"


def test_deploy_config_label_prefers_network_default_profile(tmp_path: Path) -> None:
    deploy_cfg = {
        "deploy": {
            "network": {
                "default_profile": "mild",
            }
        }
    }
    path = tmp_path / "main_network_heterogeneity_mild.yaml"

    assert get_deploy_network_profile_label(deploy_cfg) == "mild"
    assert get_deploy_config_label(deploy_cfg, path=path) == "mild"


def test_deploy_config_label_falls_back_to_path_stem(tmp_path: Path) -> None:
    path = tmp_path / "main_compute_heterogeneity.yaml"

    assert get_deploy_network_profile_label({}) is None
    assert get_deploy_config_label({}, path=path) == "main-compute-heterogeneity"


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


def test_load_deploy_config_preserves_superexec_env_map(tmp_path: Path) -> None:
    deploy_cfg = tmp_path / "fedctl.yaml"
    deploy_cfg.write_text(
        "deploy:\n"
        "  superexec:\n"
        "    env:\n"
        "      WANDB_PROJECT: fedctl\n"
        "      WANDB_ENTITY: samueljie\n",
        encoding="utf-8",
    )

    loaded = load_deploy_config(config_path=deploy_cfg)

    assert loaded["deploy"]["superexec"]["env"] == {
        "WANDB_PROJECT": "fedctl",
        "WANDB_ENTITY": "samueljie",
    }


def test_deploy_config_defaults_extracts_superexec_env_map() -> None:
    deploy_defaults = _deploy_config_defaults(
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

    assert deploy_defaults.superexec_env == {
        "WANDB_PROJECT": "fedctl",
        "WANDB_ENTITY": "samueljie",
    }


def test_runtime_superexec_env_prefers_resolved_deploy_config_label(monkeypatch) -> None:
    monkeypatch.setenv("FEDCTL_REPO_CONFIG_LABEL", "asym-down")
    monkeypatch.setenv("FEDCTL_EXPERIMENT_CONFIG", "configs/demo.toml")

    env = _runtime_superexec_env(deploy_config_label="mild")

    assert env["FEDCTL_DEPLOY_CONFIG_LABEL"] == "mild"
    assert env["FEDCTL_REPO_CONFIG_LABEL"] == "mild"
    assert env["FEDCTL_EXPERIMENT_CONFIG"] == "configs/demo.toml"


def test_deploy_config_defaults_extracts_spread_across_hosts() -> None:
    deploy_defaults = _deploy_config_defaults(
        {
            "deploy": {
                "placement": {
                    "allow_oversubscribe": True,
                    "spread_across_hosts": True,
                }
            }
        }
    )

    assert deploy_defaults.allow_oversubscribe is True
    assert deploy_defaults.spread_across_hosts is True


def test_deploy_config_defaults_extracts_prefer_spread_across_hosts() -> None:
    deploy_defaults = _deploy_config_defaults(
        {
            "deploy": {
                "placement": {
                    "allow_oversubscribe": True,
                    "spread_across_hosts": False,
                    "prefer_spread_across_hosts": True,
                }
            }
        }
    )

    assert deploy_defaults.allow_oversubscribe is True
    assert deploy_defaults.spread_across_hosts is False
    assert deploy_defaults.prefer_spread_across_hosts is True


def test_deploy_config_defaults_extracts_experiment_side_resource_overrides() -> None:
    deploy_defaults = _deploy_config_defaults(
        {
            "deploy": {
                "resources": {
                    "superexec_clientapp": {"cpu": 900, "mem": 768},
                    "superexec_serverapp": {"cpu": 1200, "mem": 1536},
                    "superlink": {"cpu": 600, "mem": 320},
                }
            }
        }
    )

    assert deploy_defaults.superexec_clientapp_resources == {"cpu": 900, "mem": 768}
    assert deploy_defaults.superexec_serverapp_resources == {"cpu": 1200, "mem": 1536}
    assert deploy_defaults.superlink_resources == {"cpu": 600, "mem": 320}
