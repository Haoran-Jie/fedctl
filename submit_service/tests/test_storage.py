from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from submit_service.app.storage import Storage, StorageConfig, new_submission_id, utcnow


def test_storage_create_and_list(tmp_path) -> None:
    db_path = tmp_path / "submit.db"
    storage = Storage(StorageConfig(db_url=f"sqlite:///{db_path}"))
    storage.init_db()

    sub_id = new_submission_id("sub")
    storage.create_submission(
        {
            "id": sub_id,
            "user": "tester",
            "project_name": "proj",
            "experiment": "exp",
            "status": "queued",
            "created_at": utcnow().isoformat(),
            "started_at": None,
            "finished_at": None,
            "nomad_job_id": None,
            "artifact_url": "s3://bucket/proj.tar.gz",
            "submit_image": "example/submit:latest",
            "node_class": "submit",
            "args": ["-m", "fedctl.submit.runner"],
            "env": {"FEDCTL_ENDPOINT": "http://127.0.0.1:4646"},
            "submit_request": {
                "path_input": "../proj",
                "command_preview": "fedctl submit run ../proj --exp exp",
            },
            "priority": 50,
            "logs_location": None,
            "result_location": None,
            "result_artifacts": [],
            "error_message": None,
            "blocked_reason": None,
            "namespace": "default",
        }
    )

    row = storage.get_submission(sub_id)
    assert row["id"] == sub_id
    assert row["args"] == ["-m", "fedctl.submit.runner"]
    assert row["env"]["FEDCTL_ENDPOINT"] == "http://127.0.0.1:4646"
    assert row["submit_request"]["path_input"] == "../proj"

    rows = storage.list_submissions(limit=5)
    assert rows[0]["id"] == sub_id

    storage.update_submission(sub_id, {"status": "completed"})
    filtered = storage.list_submissions(limit=5, statuses=["queued", "running", "blocked"])
    assert filtered == []


def test_storage_list_submissions_supports_offset_count_search_and_ui_order(tmp_path) -> None:
    db_path = tmp_path / "submit.db"
    storage = Storage(StorageConfig(db_url=f"sqlite:///{db_path}"))
    storage.init_db()

    rows = [
        ("sub-completed-new", "completed", "vision-new", "2026-01-01T00:05:00+00:00", 50),
        ("sub-running", "running", "vision-running", "2026-01-01T00:04:00+00:00", 50),
        ("sub-queued", "queued", "vision-queued", "2026-01-01T00:03:00+00:00", 50),
        ("sub-blocked-old", "blocked", "vision-blocked", "2026-01-01T00:01:00+00:00", 50),
        ("sub-blocked-new", "blocked", "vision-blocked", "2026-01-01T00:02:00+00:00", 100),
        ("sub-other", "completed", "language", "2026-01-01T00:06:00+00:00", 50),
    ]
    for sub_id, status, experiment, created_at, priority in rows:
        storage.create_submission(
            {
                "id": sub_id,
                "user": "tester",
                "project_name": "proj",
                "experiment": experiment,
                "status": status,
                "created_at": created_at,
                "started_at": None,
                "finished_at": None,
                "nomad_job_id": None,
                "artifact_url": "s3://bucket/proj.tar.gz",
                "submit_image": "example/submit:latest",
                "node_class": "submit",
                "args": ["-m", "fedctl.submit.runner"],
                "env": {},
                "priority": priority,
                "logs_location": None,
                "result_location": None,
                "result_artifacts": [],
                "error_message": None,
                "blocked_reason": None,
                "namespace": "default",
            }
        )

    assert storage.count_submissions(user="tester", query="vision") == 5

    page = storage.list_submissions(
        limit=3,
        offset=0,
        user="tester",
        query="vision",
        order="ui",
    )
    assert [row["id"] for row in page] == ["sub-running", "sub-blocked-new", "sub-blocked-old"]

    next_page = storage.list_submissions(
        limit=3,
        offset=3,
        user="tester",
        query="vision",
        order="ui",
    )
    assert [row["id"] for row in next_page] == ["sub-queued", "sub-completed-new"]


def test_storage_list_dispatch_candidates_orders_by_priority_then_age(tmp_path) -> None:
    db_path = tmp_path / "submit.db"
    storage = Storage(StorageConfig(db_url=f"sqlite:///{db_path}"))
    storage.init_db()

    rows = [
        {
            "id": "sub-low",
            "status": "queued",
            "created_at": "2026-01-01T00:00:03+00:00",
            "priority": 10,
        },
        {
            "id": "sub-high",
            "status": "queued",
            "created_at": "2026-01-01T00:00:02+00:00",
            "priority": 100,
        },
        {
            "id": "sub-default-old",
            "status": "blocked",
            "created_at": "2026-01-01T00:00:00+00:00",
            "priority": None,
        },
        {
            "id": "sub-default-new",
            "status": "queued",
            "created_at": "2026-01-01T00:00:01+00:00",
            "priority": None,
        },
        {
            "id": "sub-completed",
            "status": "completed",
            "created_at": "2026-01-01T00:00:04+00:00",
            "priority": 999,
        },
    ]
    for row in rows:
        storage.create_submission(
            {
                "id": row["id"],
                "user": "tester",
                "project_name": "proj",
                "experiment": "exp",
                "status": row["status"],
                "created_at": row["created_at"],
                "started_at": None,
                "finished_at": None,
                "nomad_job_id": None,
                "artifact_url": "s3://bucket/proj.tar.gz",
                "submit_image": "example/submit:latest",
                "node_class": "submit",
                "args": ["-m", "fedctl.submit.runner"],
                "env": {},
                "priority": row["priority"],
                "logs_location": None,
                "result_location": None,
                "result_artifacts": [],
                "error_message": None,
                "blocked_reason": None,
                "namespace": "default",
            }
        )

    candidates = storage.list_dispatch_candidates(limit=10, default_priority=50)
    ids = [row["id"] for row in candidates]
    assert ids == ["sub-high", "sub-default-old", "sub-default-new", "sub-low"]
