from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse
import os

import httpx


class ArtifactUploadError(RuntimeError):
    pass


DEFAULT_PRESIGN_TTL = 604800


def upload_artifact(
    archive_path: Path,
    artifact_store: str,
    *,
    presign_endpoint: str | None = None,
    presign_token: str | None = None,
) -> str:
    if artifact_store.startswith(("http://", "https://")):
        return _upload_http(archive_path, artifact_store)
    if artifact_store.startswith("s3+presign://"):
        return _upload_s3_presign(
            archive_path,
            artifact_store,
            presign_endpoint=presign_endpoint,
            presign_token=presign_token,
        )
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


def _upload_s3_presign(
    archive_path: Path,
    s3_url: str,
    *,
    presign_endpoint: str | None = None,
    presign_token: str | None = None,
) -> str:
    parsed = urlparse(s3_url)
    bucket = parsed.netloc
    if not bucket:
        raise ArtifactUploadError("S3 URL must include a bucket (s3://bucket/prefix).")
    prefix = parsed.path.lstrip("/")
    key = f"{prefix}/{archive_path.name}" if prefix else archive_path.name
    if presign_endpoint is None:
        presign_endpoint = os.environ.get("FEDCTL_PRESIGN_ENDPOINT")
    if not presign_endpoint:
        submit_service = os.environ.get("SUBMIT_SERVICE_ENDPOINT", "").strip()
        if submit_service:
            presign_endpoint = submit_service.rstrip("/") + "/v1/presign"
    if presign_endpoint:
        return _upload_via_presign_service(
            archive_path,
            presign_endpoint,
            bucket=bucket,
            key=key,
            token=presign_token,
        )
    try:
        import boto3
    except ImportError as exc:
        raise ArtifactUploadError("boto3 is required for S3 uploads.") from exc

    endpoint = os.environ.get("AWS_S3_ENDPOINT")
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    session = boto3.session.Session(region_name=region)
    client = session.client("s3", endpoint_url=endpoint)
    try:
        client.upload_file(str(archive_path), bucket, key)
    except Exception as exc:
        raise ArtifactUploadError(f"S3 upload failed: {exc}") from exc

    expires = _presign_ttl_or_default()
    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires,
        )
    except Exception as exc:
        raise ArtifactUploadError(f"Failed to presign URL: {exc}") from exc
    return _maybe_tgz_url(url, archive_path)


def _upload_via_presign_service(
    archive_path: Path,
    presign_endpoint: str,
    *,
    bucket: str,
    key: str,
    token: str | None = None,
) -> str:
    headers: dict[str, str] = {}
    if token is None:
        token = os.environ.get("SUBMIT_SERVICE_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    expires = _configured_presign_ttl()
    put_url = _fetch_presign_url(
        presign_endpoint,
        headers=headers,
        bucket=bucket,
        key=key,
        method="PUT",
        expires=expires,
    )
    try:
        with archive_path.open("rb") as handle:
            response = httpx.put(put_url, content=handle, timeout=60.0)
    except OSError as exc:
        raise ArtifactUploadError(f"Failed to read archive: {exc}") from exc
    except httpx.HTTPError as exc:
        raise ArtifactUploadError(f"HTTP upload failed: {exc}") from exc
    if response.status_code >= 400:
        raise ArtifactUploadError(
            f"Upload failed with status {response.status_code}: {response.text[:200]}"
        )
    get_url = _fetch_presign_url(
        presign_endpoint,
        headers=headers,
        bucket=bucket,
        key=key,
        method="GET",
        expires=expires,
    )
    return _maybe_tgz_url(get_url, archive_path)


def _fetch_presign_url(
    presign_endpoint: str,
    *,
    headers: dict[str, str],
    bucket: str,
    key: str,
    method: str,
    expires: int | None,
) -> str:
    payload = {
        "bucket": bucket,
        "key": key,
        "method": method,
    }
    if expires is not None:
        payload["expires"] = expires
    try:
        response = httpx.post(presign_endpoint, json=payload, headers=headers, timeout=10.0)
    except httpx.HTTPError as exc:
        raise ArtifactUploadError(f"Presign request failed: {exc}") from exc
    if response.status_code >= 400:
        raise ArtifactUploadError(
            f"Presign request failed with status {response.status_code}: {response.text[:200]}"
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise ArtifactUploadError(f"Presign response was not JSON: {exc}") from exc
    url = data.get("url") if isinstance(data, dict) else None
    if not isinstance(url, str) or not url:
        raise ArtifactUploadError("Presign response missing url.")
    return url


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


def _configured_presign_ttl() -> int | None:
    raw = os.environ.get("FEDCTL_PRESIGN_TTL")
    if raw is None or not raw.strip():
        return None
    return int(raw)


def _presign_ttl_or_default() -> int:
    return _configured_presign_ttl() or DEFAULT_PRESIGN_TTL
