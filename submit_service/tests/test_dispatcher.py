from __future__ import annotations

from datetime import timedelta
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from submit_service.app.config import SubmitConfig
from submit_service.app.storage import Storage, StorageConfig
from submit_service.app.workers import dispatcher as dispatcher_mod


def _cfg(db_path: Path) -> SubmitConfig:
    return SubmitConfig(
        db_url=f"sqlite:///{db_path}",
        tokens=set(),
        token_identities={},
        allow_unauth=True,
        service_endpoint=None,
        nomad_endpoint=None,
        nomad_token=None,
        nomad_namespace=None,
        nomad_tls_ca=None,
        nomad_tls_skip_verify=False,
        dispatch_mode="queue",
        dispatch_interval=10,
        datacenter="dc1",
        default_priority=50,
        docker_socket=None,
        nomad_inventory_ttl=5,
        autopurge_completed_after_s=0,
    )


def _create_submission(
    storage: Storage,
    *,
    submission_id: str,
    status: str,
    created_at: str,
    priority: int | None,
) -> None:
    storage.create_submission(
        {
            "id": submission_id,
            "user": "tester",
            "project_name": "proj",
            "experiment": "exp",
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


def test_dispatcher_respects_priority_and_age_order(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "submit.db"
    storage = Storage(StorageConfig(db_url=f"sqlite:///{db_path}"))
    storage.init_db()

    _create_submission(
        storage,
        submission_id="sub-low",
        status="queued",
        created_at="2026-01-01T00:00:03+00:00",
        priority=10,
    )
    _create_submission(
        storage,
        submission_id="sub-high",
        status="queued",
        created_at="2026-01-01T00:00:02+00:00",
        priority=100,
    )
    _create_submission(
        storage,
        submission_id="sub-default-old",
        status="queued",
        created_at="2026-01-01T00:00:00+00:00",
        priority=None,
    )
    _create_submission(
        storage,
        submission_id="sub-default-new",
        status="blocked",
        created_at="2026-01-01T00:00:01+00:00",
        priority=None,
    )

    monkeypatch.setattr(dispatcher_mod, "_inventory_snapshot", lambda inventory: ([], None))
    monkeypatch.setattr(
        dispatcher_mod,
        "_capacity_allows",
        lambda submission, free_nodes, inventory_error: (True, None),
    )

    dispatched_ids: list[str] = []

    def fake_dispatch(storage_obj, submission, cfg):
        dispatched_ids.append(submission["id"])
        return dispatcher_mod.DispatchResult(submitted=True)

    monkeypatch.setattr(dispatcher_mod, "dispatch_submission", fake_dispatch)

    dispatcher = dispatcher_mod.Dispatcher(storage, _cfg(db_path))
    dispatcher.run_once()

    assert dispatched_ids == ["sub-high", "sub-default-old", "sub-default-new", "sub-low"]


def test_dispatcher_autopurges_completed_jobs_after_delay(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "submit.db"
    storage = Storage(StorageConfig(db_url=f"sqlite:///{db_path}"))
    storage.init_db()
    finished_at = (dispatcher_mod.utcnow() - timedelta(seconds=120)).isoformat()
    _create_submission(
        storage,
        submission_id="sub-completed",
        status="completed",
        created_at="2026-01-01T00:00:00+00:00",
        priority=50,
    )
    storage.update_submission(
        "sub-completed",
        {
            "nomad_job_id": "sub-completed",
            "finished_at": finished_at,
            "namespace": "default",
        },
    )

    calls: list[tuple[str, bool]] = []

    class FakeNomadClient:
        def __init__(self, *args, **kwargs):
            return None

        def stop_job(self, job_id: str, *, purge: bool = False):
            calls.append((job_id, purge))
            return {}

        def close(self):
            return None

    monkeypatch.setattr(dispatcher_mod, "NomadClient", FakeNomadClient)
    monkeypatch.setattr(dispatcher_mod, "_inventory_snapshot", lambda inventory: ([], None))
    monkeypatch.setattr(
        dispatcher_mod,
        "_capacity_allows",
        lambda submission, free_nodes, inventory_error: (True, None),
    )

    cfg = _cfg(db_path)
    cfg = SubmitConfig(
        **{
            **cfg.__dict__,
            "nomad_endpoint": "http://nomad.example:4646",
            "autopurge_completed_after_s": 60,
        }
    )
    dispatcher = dispatcher_mod.Dispatcher(storage, cfg)
    dispatcher.run_once()

    assert calls == [("sub-completed", True)]
    updated = storage.get_submission("sub-completed")
    assert updated.get("nomad_job_id") is None
