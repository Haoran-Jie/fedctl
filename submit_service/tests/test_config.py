from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from submit_service.app import config as config_mod


def _clear_env(monkeypatch) -> None:
    for key in (
        "SUBMIT_REPO_CONFIG",
        "SUBMIT_DB_URL",
        "FEDCTL_SUBMIT_TOKENS",
        "FEDCTL_SUBMIT_TOKEN_MAP",
        "FEDCTL_SUBMIT_ALLOW_UNAUTH",
        "SUBMIT_SERVICE_ENDPOINT",
        "SUBMIT_NOMAD_ENDPOINT",
        "SUBMIT_NOMAD_TOKEN",
        "SUBMIT_NOMAD_NAMESPACE",
        "SUBMIT_NOMAD_TLS_CA",
        "SUBMIT_NOMAD_TLS_SKIP_VERIFY",
        "SUBMIT_DISPATCH_MODE",
        "SUBMIT_DISPATCH_INTERVAL",
        "SUBMIT_DATACENTER",
        "SUBMIT_DEFAULT_PRIORITY",
        "SUBMIT_NOMAD_INV_TTL",
        "SUBMIT_AUTOPURGE_COMPLETED_AFTER",
        "SUBMIT_DOCKER_SOCKET",
        "SUBMIT_UI_ENABLED",
        "SUBMIT_UI_SESSION_SECRET",
        "SUBMIT_UI_COOKIE_NAME",
        "SUBMIT_UI_COOKIE_SECURE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_load_config_prefers_fedctl_local_yaml(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    fedctl_dir = tmp_path / ".fedctl"
    fedctl_dir.mkdir(parents=True)
    (fedctl_dir / "fedctl.yaml").write_text(
        "submit-service:\n"
        "  nomad_endpoint: http://from-fedctl:4646\n",
        encoding="utf-8",
    )
    (fedctl_dir / "fedctl_local.yaml").write_text(
        "submit-service:\n"
        "  nomad_endpoint: http://from-local:4646\n",
        encoding="utf-8",
    )

    cfg = config_mod.load_config()
    assert cfg.nomad_endpoint == "http://from-local:4646"


def test_load_config_falls_back_to_fedctl_yaml(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    fedctl_dir = tmp_path / ".fedctl"
    fedctl_dir.mkdir(parents=True)
    (fedctl_dir / "fedctl.yaml").write_text(
        "submit-service:\n"
        "  nomad_endpoint: http://from-fedctl:4646\n",
        encoding="utf-8",
    )

    cfg = config_mod.load_config()
    assert cfg.nomad_endpoint == "http://from-fedctl:4646"


def test_submit_repo_config_env_overrides_default_fallback(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    fedctl_dir = tmp_path / ".fedctl"
    fedctl_dir.mkdir(parents=True)
    (fedctl_dir / "fedctl.yaml").write_text(
        "submit-service:\n"
        "  nomad_endpoint: http://from-fedctl:4646\n",
        encoding="utf-8",
    )
    (fedctl_dir / "fedctl_local.yaml").write_text(
        "submit-service:\n"
        "  nomad_endpoint: http://from-local:4646\n",
        encoding="utf-8",
    )
    explicit = tmp_path / "explicit.yaml"
    explicit.write_text(
        "submit-service:\n"
        "  nomad_endpoint: http://from-explicit:4646\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SUBMIT_REPO_CONFIG", str(explicit))

    cfg = config_mod.load_config()
    assert cfg.nomad_endpoint == "http://from-explicit:4646"


def test_load_config_parses_autopurge_completed_after_env(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUBMIT_AUTOPURGE_COMPLETED_AFTER", "60")

    cfg = config_mod.load_config()
    assert cfg.autopurge_completed_after_s == 60


def test_load_config_parses_ui_env(tmp_path, monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUBMIT_UI_ENABLED", "true")
    monkeypatch.setenv("SUBMIT_UI_SESSION_SECRET", "secret")
    monkeypatch.setenv("SUBMIT_UI_COOKIE_NAME", "fedctl_ui")
    monkeypatch.setenv("SUBMIT_UI_COOKIE_SECURE", "true")

    cfg = config_mod.load_config()
    assert cfg.ui_enabled is True
    assert cfg.ui_session_secret == "secret"
    assert cfg.ui_cookie_name == "fedctl_ui"
    assert cfg.ui_cookie_secure is True
