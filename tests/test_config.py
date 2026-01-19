from pathlib import Path

from fedctl.config.io import load_config


def test_load_config_creates_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg = load_config()
    assert cfg.active_profile
    assert cfg.profiles
