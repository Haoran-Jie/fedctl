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
            "priority": 50,
            "logs_location": None,
            "result_location": None,
            "error_message": None,
            "namespace": "default",
        }
    )

    row = storage.get_submission(sub_id)
    assert row["id"] == sub_id
    assert row["args"] == ["-m", "fedctl.submit.runner"]
    assert row["env"]["FEDCTL_ENDPOINT"] == "http://127.0.0.1:4646"

    rows = storage.list_submissions(limit=5)
    assert rows[0]["id"] == sub_id
