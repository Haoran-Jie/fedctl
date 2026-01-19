from __future__ import annotations


class ProjectError(Exception):
    """User-facing project inspection errors."""

    def __init__(self, message: str, exit_code: int = 5) -> None:
        super().__init__(message)
        self.exit_code = exit_code
