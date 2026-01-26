from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
import os

import httpx


class ArtifactUploadError(RuntimeError):
    pass


def upload_artifact(archive_path: Path, artifact_store: str) -> str:
    if artifact_store.startswith(("http://", "https://")):
        return _upload_http(archive_path, artifact_store)
    if artifact_store.startswith("s3+presign://"):
        return _upload_s3_presign(archive_path, artifact_store)
    if artifact_store.startswith("s3://"):
        return _upload_s3(archive_path, artifact_store)
    raise ArtifactUploadError("Unsupported artifact_store; use http(s) or s3.")


def _upload_http(archive_path: Path, base_url: str) -> str:
    url = f"{base_url.rstrip('/')}/{archive_path.name}"
    try:
        with archive_path.open("rb") as handle:
            response = httpx.put(url, content=handle, timeout=60.0)
    except OSError as exc:
        raise ArtifactUploadError(f"Failed to read archive: {exc}") from exc
    except httpx.HTTPError as exc:
        raise ArtifactUploadError(f"HTTP upload failed: {exc}") from exc

    if response.status_code >= 400:
        raise ArtifactUploadError(
            f"Upload failed with status {response.status_code}: {response.text[:200]}"
        )
    return url


def _upload_s3(archive_path: Path, s3_url: str) -> str:
    try:
        import boto3
    except ImportError as exc:
        raise ArtifactUploadError("boto3 is required for S3 uploads.") from exc

    parsed = urlparse(s3_url)
    bucket = parsed.netloc
    if not bucket:
        raise ArtifactUploadError("S3 URL must include a bucket (s3://bucket/prefix).")
    prefix = parsed.path.lstrip("/")
    key = f"{prefix}/{archive_path.name}" if prefix else archive_path.name

    endpoint = os.environ.get("AWS_S3_ENDPOINT")
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    session = boto3.session.Session(region_name=region)
    client = session.client("s3", endpoint_url=endpoint)
    try:
        client.upload_file(str(archive_path), bucket, key)
    except Exception as exc:
        raise ArtifactUploadError(f"S3 upload failed: {exc}") from exc

    return _s3_getter_url(bucket, key, endpoint)


def _upload_s3_presign(archive_path: Path, s3_url: str) -> str:
    try:
        import boto3
    except ImportError as exc:
        raise ArtifactUploadError("boto3 is required for S3 uploads.") from exc

    parsed = urlparse(s3_url)
    bucket = parsed.netloc
    if not bucket:
        raise ArtifactUploadError("S3 URL must include a bucket (s3://bucket/prefix).")
    prefix = parsed.path.lstrip("/")
    key = f"{prefix}/{archive_path.name}" if prefix else archive_path.name

    endpoint = os.environ.get("AWS_S3_ENDPOINT")
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    session = boto3.session.Session(region_name=region)
    client = session.client("s3", endpoint_url=endpoint)
    try:
        client.upload_file(str(archive_path), bucket, key)
    except Exception as exc:
        raise ArtifactUploadError(f"S3 upload failed: {exc}") from exc

    expires = int(os.environ.get("FEDCTL_PRESIGN_TTL", "1800"))
    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires,
        )
    except Exception as exc:
        raise ArtifactUploadError(f"Failed to presign URL: {exc}") from exc
    return _maybe_tgz_url(url, archive_path)


def _s3_getter_url(bucket: str, key: str, endpoint: str | None) -> str:
    if endpoint:
        endpoint = endpoint.rstrip("/")
        if "://" not in endpoint:
            raise ArtifactUploadError("AWS_S3_ENDPOINT must include a scheme, e.g. https://")
        return f"s3::{endpoint}/{bucket}/{key}"
    return f"s3://{bucket}/{key}"


def _maybe_tgz_url(url: str, archive_path: Path) -> str:
    if os.environ.get("FEDCTL_FORCE_TGZ", "").strip() not in {"1", "true", "yes"}:
        return url
    suffix = "".join(archive_path.suffixes)
    if suffix in {".tar.gz", ".tgz"}:
        return f"tgz::{url}"
    return url
