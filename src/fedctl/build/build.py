from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import BuildError


def build_image(
    *,
    image: str,
    dockerfile_path: Path,
    context_dir: Path,
    no_cache: bool = False,
    platform: str | None = None,
    quiet: bool = False,
) -> None:
    cmd = ["docker", "build", "-t", image, "-f", str(dockerfile_path)]
    if no_cache:
        cmd.append("--no-cache")
    # Avoid docker's quiet mode here. On the Raspberry Pi submit nodes we have
    # repeatedly seen `docker build --quiet` hang after the inner RUN step
    # completed, which breaks both `fedctl build` and `fedctl submit run`.
    # Keeping stdout attached is noisier but reliable.
    if platform:
        cmd.extend(["--platform", platform])
    cmd.append(str(context_dir))

    try:
        result = subprocess.run(cmd, check=False)
    except FileNotFoundError as exc:
        raise BuildError("Docker is not installed or not on PATH.") from exc

    if result.returncode != 0:
        raise BuildError(f"Docker build failed with exit code {result.returncode}.")


def image_exists(image: str) -> bool:
    cmd = ["docker", "image", "inspect", image]
    try:
        result = subprocess.run(cmd, check=False, capture_output=True)
    except FileNotFoundError:
        return False
    return result.returncode == 0


def pull_image(image: str) -> bool:
    cmd = ["docker", "pull", image]
    try:
        result = subprocess.run(cmd, check=False)
    except FileNotFoundError:
        return False
    return result.returncode == 0
