from __future__ import annotations

from pathlib import Path
import os
import platform


def user_config_dir() -> Path:
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA not set on Windows")
        return Path(appdata) / "fedctl"

    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "fedctl"
    return Path.home() / ".config" / "fedctl"


def config_path() -> Path:
    return user_config_dir() / "config.toml"
