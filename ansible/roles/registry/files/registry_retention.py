#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib import error, request

MANIFEST_ACCEPT = ", ".join(
    [
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.oci.image.index.v1+json",
    ]
)


@dataclass(frozen=True)
class TagRecord:
    tag: str
    delete_digest: str
    created_at: datetime | None
    metadata_ok: bool = True


@dataclass(frozen=True)
class DigestDeletion:
    digest: str
    tags: tuple[str, ...]


class RegistryClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _request(self, path: str, *, method: str = "GET", headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        req = request.Request(f"{self.base_url}{path}", method=method, headers=headers or {})
        try:
            with request.urlopen(req, timeout=30) as resp:
                return resp.status, dict(resp.headers.items()), resp.read()
        except error.HTTPError as exc:
            return exc.code, dict(exc.headers.items()), exc.read()

    def _get_json(self, path: str, *, headers: dict[str, str] | None = None) -> Any:
        status, _, body = self._request(path, headers=headers)
        if status >= 400:
            raise RuntimeError(f"GET {path} failed with HTTP {status}")
        return json.loads(body.decode("utf-8"))

    def catalog(self) -> list[str]:
        payload = self._get_json("/v2/_catalog?n=1000")
        repos = payload.get("repositories", []) if isinstance(payload, dict) else []
        return [repo for repo in repos if isinstance(repo, str)]

    def tags(self, repo: str) -> list[str]:
        payload = self._get_json(f"/v2/{repo}/tags/list")
        tags = payload.get("tags", []) if isinstance(payload, dict) else []
        return [tag for tag in tags if isinstance(tag, str)]

    def manifest(self, repo: str, reference: str) -> tuple[dict[str, Any], str]:
        status, headers, body = self._request(
            f"/v2/{repo}/manifests/{reference}", headers={"Accept": MANIFEST_ACCEPT}
        )
        if status >= 400:
            raise RuntimeError(f"manifest lookup failed for {repo}:{reference} with HTTP {status}")
        digest = headers.get("Docker-Content-Digest") or headers.get("docker-content-digest")
        if not digest:
            raise RuntimeError(f"manifest digest missing for {repo}:{reference}")
        return json.loads(body.decode("utf-8")), digest

    def blob(self, repo: str, digest: str) -> dict[str, Any]:
        payload = self._get_json(f"/v2/{repo}/blobs/{digest}")
        if not isinstance(payload, dict):
            raise RuntimeError(f"blob {digest} for {repo} is not a JSON object")
        return payload

    def delete_manifest(self, repo: str, digest: str) -> int:
        status, _, _ = self._request(f"/v2/{repo}/manifests/{digest}", method="DELETE")
        return status


def matches_repository(repo: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(repo, pattern) for pattern in patterns)


def parse_created_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def build_retention_plan(
    tag_records: list[TagRecord],
    *,
    keep_tags: int,
    keep_latest: bool,
) -> list[DigestDeletion]:
    keep_tag_names: set[str] = set()
    if keep_latest and any(record.tag == "latest" for record in tag_records):
        keep_tag_names.add("latest")

    resolved = [record for record in tag_records if record.metadata_ok and record.created_at is not None]
    sorted_records = sorted(
        resolved,
        key=lambda record: (record.created_at, record.tag),
        reverse=True,
    )
    for record in sorted_records:
        if record.tag in keep_tag_names:
            continue
        if len([name for name in keep_tag_names if name != "latest"]) >= keep_tags:
            break
        keep_tag_names.add(record.tag)

    by_digest: dict[str, list[TagRecord]] = {}
    for record in tag_records:
        by_digest.setdefault(record.delete_digest, []).append(record)

    deletions: list[DigestDeletion] = []
    for digest, records in by_digest.items():
        if any(not record.metadata_ok or record.created_at is None for record in records):
            continue
        if any(record.tag in keep_tag_names for record in records):
            continue
        deletions.append(
            DigestDeletion(digest=digest, tags=tuple(sorted(record.tag for record in records)))
        )
    return sorted(deletions, key=lambda item: item.digest)


def resolve_created_at(client: RegistryClient, repo: str, manifest: dict[str, Any]) -> datetime | None:
    config = manifest.get("config") if isinstance(manifest, dict) else None
    if isinstance(config, dict) and isinstance(config.get("digest"), str):
        blob = client.blob(repo, config["digest"])
        return parse_created_at(blob.get("created"))

    manifests = manifest.get("manifests") if isinstance(manifest, dict) else None
    if isinstance(manifests, list) and manifests:
        chosen: dict[str, Any] | None = None
        for candidate in manifests:
            platform = candidate.get("platform") if isinstance(candidate, dict) else None
            if isinstance(platform, dict) and platform.get("architecture") == "arm64" and platform.get("os") == "linux":
                chosen = candidate
                break
        if chosen is None and isinstance(manifests[0], dict):
            chosen = manifests[0]
        if chosen and isinstance(chosen.get("digest"), str):
            child_manifest, _ = client.manifest(repo, chosen["digest"])
            return resolve_created_at(client, repo, child_manifest)
    return None


def collect_tag_records(client: RegistryClient, repo: str) -> list[TagRecord]:
    records: list[TagRecord] = []
    for tag in client.tags(repo):
        try:
            manifest, delete_digest = client.manifest(repo, tag)
            created_at = resolve_created_at(client, repo, manifest)
            if created_at is None:
                raise RuntimeError("created timestamp unavailable")
            records.append(TagRecord(tag=tag, delete_digest=delete_digest, created_at=created_at, metadata_ok=True))
        except Exception as exc:
            print(f"[warn] skipping metadata for {repo}:{tag}: {exc}", file=sys.stderr)
            records.append(TagRecord(tag=tag, delete_digest=f"unresolved:{tag}", created_at=None, metadata_ok=False))
    return records


def default_patterns_from_env() -> list[str]:
    raw = os.environ.get("FEDCTL_REPO_PATTERNS", "*-superexec")
    return [part.strip() for part in raw.split(",") if part.strip()]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Delete old SuperExec tags from a local Docker registry")
    parser.add_argument("--registry-url", default=os.environ.get("FEDCTL_REGISTRY_URL", "http://127.0.0.1:5000"))
    parser.add_argument("--keep-tags", type=int, default=int(os.environ.get("FEDCTL_KEEP_TAGS", "10")))
    parser.add_argument(
        "--keep-latest",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("FEDCTL_KEEP_LATEST", "true").strip().lower() in {"1", "true", "yes", "on"},
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("FEDCTL_DRY_RUN", "false").strip().lower() in {"1", "true", "yes", "on"},
    )
    parser.add_argument("--repo-pattern", action="append", default=None)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    patterns = args.repo_pattern or default_patterns_from_env()
    client = RegistryClient(args.registry_url)
    try:
        repositories = sorted(repo for repo in client.catalog() if matches_repository(repo, patterns))
    except Exception as exc:
        print(f"[error] failed to fetch registry catalog: {exc}", file=sys.stderr)
        return 1

    if not repositories:
        print("[info] no matching repositories found")
        return 0

    deleted = 0
    for repo in repositories:
        print(f"[info] repo={repo}")
        records = collect_tag_records(client, repo)
        plan = build_retention_plan(records, keep_tags=max(args.keep_tags, 0), keep_latest=args.keep_latest)
        if not plan:
            print("[info] nothing to delete")
            continue
        for deletion in plan:
            print(f"[plan] delete digest={deletion.digest} tags={','.join(deletion.tags)}")
            if args.dry_run:
                continue
            status = client.delete_manifest(repo, deletion.digest)
            if status not in {202, 200}:
                print(f"[warn] delete failed repo={repo} digest={deletion.digest} status={status}", file=sys.stderr)
                continue
            deleted += 1
    print(f"[info] completed; deleted_digests={deleted} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
