from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi import HTTPException

from submit_service.app.submissions_service import (
    archived_log_issue,
    latest_alloc_for_task,
    resolve_nomad_job,
)


def test_resolve_nomad_job_uses_explicit_targets_by_index() -> None:
    record = {
        "jobs": {
            "supernodes": {
                "job_id": "job-supernodes",
                "tasks": ["supernode-rpi4-1", "supernode-rpi5-1"],
                "targets": [
                    {"index": 1, "job_id": "job-supernodes", "task": "supernode-rpi4-1"},
                    {"index": 2, "job_id": "job-supernodes", "task": "supernode-rpi5-1"},
                ],
            }
        }
    }

    job_id, task = resolve_nomad_job(record, "supernodes", None, 2)

    assert job_id == "job-supernodes"
    assert task == "supernode-rpi5-1"


def test_resolve_nomad_job_uses_index_for_multi_task_job_legacy_shape() -> None:
    record = {
        "jobs": {
            "supernodes": {
                "job_id": "job-supernodes",
                "tasks": ["supernode-rpi4-1", "supernode-rpi5-1"],
            }
        }
    }

    job_id, task = resolve_nomad_job(record, "supernodes", None, 2)

    assert job_id == "job-supernodes"
    assert task == "supernode-rpi5-1"


def test_resolve_nomad_job_rejects_out_of_range_task_index() -> None:
    record = {
        "jobs": {
            "supernodes": {
                "job_id": "job-supernodes",
                "tasks": ["supernode-rpi4-1"],
            }
        }
    }

    with pytest.raises(HTTPException) as exc:
        resolve_nomad_job(record, "supernodes", None, 2)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Task index out of range for supernodes: 2"


def test_resolve_nomad_job_rejects_unknown_task_when_targets_present() -> None:
    record = {
        "jobs": {
            "supernodes": {
                "job_id": "job-supernodes",
                "targets": [
                    {"index": 1, "job_id": "job-supernodes", "task": "supernode-rpi4-1"},
                ],
            }
        }
    }

    with pytest.raises(HTTPException) as exc:
        resolve_nomad_job(record, "supernodes", "supernode-rpi5-1", 1)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Task not found for supernodes: supernode-rpi5-1"


def test_latest_alloc_for_task_prefers_matching_allocation() -> None:
    allocs = [
        {
            "ID": "alloc-newer-wrong-task",
            "ModifyTime": 20,
            "TaskStates": {"supernode-rpi5-2": {}},
        },
        {
            "ID": "alloc-older-correct-task",
            "ModifyTime": 10,
            "TaskStates": {"supernode-rpi5-1": {}},
        },
    ]

    alloc = latest_alloc_for_task(allocs, "supernode-rpi5-1")

    assert alloc is not None
    assert alloc["ID"] == "alloc-older-correct-task"


def test_archived_log_issue_returns_matching_error_by_index() -> None:
    record = {
        "logs_archive": {
            "entries": [
                {
                    "job": "supernodes",
                    "index": 1,
                    "task": "supernode-1",
                    "stderr": True,
                    "error": "alloc logs unavailable: task not found",
                }
            ]
        }
    }

    issue = archived_log_issue(
        record=record,
        job="supernodes",
        task=None,
        index=1,
        stderr=True,
    )

    assert issue == "alloc logs unavailable: task not found"
