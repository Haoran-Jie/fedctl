from __future__ import annotations

import subprocess

from .errors import BuildError


def push_image(image: str) -> None:
    try:
        result = subprocess.run(
            ["docker", "push", image],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise BuildError("Docker is not installed or not on PATH.") from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout
        if detail:
            tail = detail[-800:]
            raise BuildError(
                f"Docker push failed with exit code {result.returncode}: {tail}"
            )
        raise BuildError(f"Docker push failed with exit code {result.returncode}.")
