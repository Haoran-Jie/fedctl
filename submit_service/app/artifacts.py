from __future__ import annotations

from pathlib import Path


def validate_artifact_url(url: str) -> str:
    if not url:
        raise ValueError("artifact_url is required")
    if "://" not in url:
        raise ValueError("artifact_url must include a scheme (e.g., s3:// or https://)")
    return url


def store_uploaded_file(data: bytes, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest
