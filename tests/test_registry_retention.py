from __future__ import annotations

from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ansible"
    / "roles"
    / "registry"
    / "files"
    / "registry_retention.py"
)
SPEC = spec_from_file_location("registry_retention", MODULE_PATH)
assert SPEC and SPEC.loader
registry_retention = module_from_spec(SPEC)
sys.modules[SPEC.name] = registry_retention
SPEC.loader.exec_module(registry_retention)

TagRecord = registry_retention.TagRecord
build_retention_plan = registry_retention.build_retention_plan
matches_repository = registry_retention.matches_repository
parse_created_at = registry_retention.parse_created_at


def _dt(day: int) -> datetime:
    return datetime(2026, 4, day, 12, 0, tzinfo=timezone.utc)


def test_matches_repository_uses_glob_patterns() -> None:
    assert matches_repository("fedctl-research-superexec", ["*-superexec"])
    assert matches_repository("heterofl-fedctl-superexec", ["*-superexec"])
    assert not matches_repository("fedctl-submit", ["*-superexec"])


def test_build_retention_plan_keeps_latest_plus_newest_tags() -> None:
    records = [
        TagRecord(tag="latest", delete_digest="sha256:latest", created_at=_dt(1)),
        TagRecord(tag="old", delete_digest="sha256:old", created_at=_dt(2)),
        TagRecord(tag="mid", delete_digest="sha256:mid", created_at=_dt(3)),
        TagRecord(tag="new", delete_digest="sha256:new", created_at=_dt(4)),
    ]

    deletions = build_retention_plan(records, keep_tags=2, keep_latest=True)

    assert deletions == [registry_retention.DigestDeletion(digest="sha256:old", tags=("old",))]


def test_build_retention_plan_skips_unresolved_metadata() -> None:
    records = [
        TagRecord(tag="latest", delete_digest="sha256:latest", created_at=_dt(1)),
        TagRecord(tag="resolved", delete_digest="sha256:resolved", created_at=_dt(2)),
        TagRecord(tag="broken", delete_digest="unresolved:broken", created_at=None, metadata_ok=False),
    ]

    deletions = build_retention_plan(records, keep_tags=1, keep_latest=True)

    assert deletions == []


def test_build_retention_plan_keeps_shared_digest_when_any_tag_is_kept() -> None:
    records = [
        TagRecord(tag="latest", delete_digest="sha256:shared", created_at=_dt(3)),
        TagRecord(tag="old-alias", delete_digest="sha256:shared", created_at=_dt(1)),
        TagRecord(tag="older-unique", delete_digest="sha256:older", created_at=_dt(2)),
    ]

    deletions = build_retention_plan(records, keep_tags=0, keep_latest=True)

    assert deletions == [registry_retention.DigestDeletion(digest="sha256:older", tags=("older-unique",))]


def test_parse_created_at_handles_z_suffix() -> None:
    assert parse_created_at("2026-04-15T03:30:00Z") == datetime(2026, 4, 15, 3, 30, tzinfo=timezone.utc)
