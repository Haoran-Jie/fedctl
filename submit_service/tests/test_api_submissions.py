from __future__ import annotations

import json

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from submit_service.app.main import create_app


def _make_client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("FEDCTL_SUBMIT_TOKENS", raising=False)
    monkeypatch.delenv("FEDCTL_SUBMIT_TOKEN_MAP", raising=False)
    monkeypatch.setenv("SUBMIT_REPO_CONFIG", str(tmp_path / "missing-fedctl.yaml"))
    monkeypatch.setenv("SUBMIT_DB_URL", f"sqlite:///{tmp_path / 'submit.db'}")
    monkeypatch.setenv("FEDCTL_SUBMIT_ALLOW_UNAUTH", "true")
    monkeypatch.setenv("SUBMIT_DISPATCH_MODE", "queue")
    app = create_app()
    return TestClient(app)


def _payload() -> dict[str, object]:
    return {
        "project_name": "mnist",
        "experiment": "mnist-20250125",
        "artifact_url": "s3://bucket/mnist.tar.gz",
        "submit_image": "example/submit:latest",
        "node_class": "submit",
        "args": ["-m", "fedctl.submit.runner"],
        "env": {"FEDCTL_ENDPOINT": "http://127.0.0.1:4646"},
        "priority": 50,
        "namespace": "default",
    }


def test_create_and_get_submission(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path, monkeypatch)
    payload = _payload()
    response = client.post("/v1/submissions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    submission_id = data["submission_id"]

    response = client.get(f"/v1/submissions/{submission_id}")
    assert response.status_code == 200
    assert response.json()["submission_id"] == submission_id

    response = client.get("/v1/submissions", params={"limit": 5})
    assert response.status_code == 200
    assert response.json()[0]["submission_id"] == submission_id


def test_list_submissions_active_only_filter(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_client(tmp_path, monkeypatch)
    storage = client.app.state.storage

    first = client.post("/v1/submissions", json=_payload()).json()["submission_id"]
    second = client.post("/v1/submissions", json=_payload()).json()["submission_id"]
    storage.update_submission(first, {"status": "completed"})
    storage.update_submission(second, {"status": "running"})

    response = client.get("/v1/submissions", params={"limit": 10, "active_only": "true"})
    assert response.status_code == 200
    ids = [entry["submission_id"] for entry in response.json()]
    assert second in ids
    assert first not in ids


def test_list_submissions_status_filter(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_client(tmp_path, monkeypatch)
    storage = client.app.state.storage

    completed_id = client.post("/v1/submissions", json=_payload()).json()["submission_id"]
    failed_id = client.post("/v1/submissions", json=_payload()).json()["submission_id"]
    storage.update_submission(completed_id, {"status": "completed"})
    storage.update_submission(failed_id, {"status": "failed"})

    response = client.get("/v1/submissions", params={"limit": 10, "status": "failed"})
    assert response.status_code == 200
    ids = [entry["submission_id"] for entry in response.json()]
    assert failed_id in ids
    assert completed_id not in ids


def test_auth_requires_token(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBMIT_REPO_CONFIG", str(tmp_path / "missing-fedctl.yaml"))
    monkeypatch.setenv("SUBMIT_DB_URL", f"sqlite:///{tmp_path / 'submit.db'}")
    monkeypatch.setenv("FEDCTL_SUBMIT_TOKENS", "token1")
    monkeypatch.delenv("FEDCTL_SUBMIT_TOKEN_MAP", raising=False)
    monkeypatch.setenv("FEDCTL_SUBMIT_ALLOW_UNAUTH", "false")
    app = create_app()
    client = TestClient(app)

    payload = {
        "project_name": "mnist",
        "experiment": "mnist-20250125",
        "artifact_url": "s3://bucket/mnist.tar.gz",
        "submit_image": "example/submit:latest",
    }
    response = client.post("/v1/submissions", json=payload)
    assert response.status_code == 401

    response = client.post(
        "/v1/submissions",
        json=payload,
        headers={"Authorization": "Bearer token1"},
    )
    assert response.status_code == 200


def test_token_map_enforces_owner_scope_and_admin_override(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUBMIT_REPO_CONFIG", str(tmp_path / "missing-fedctl.yaml"))
    monkeypatch.setenv("SUBMIT_DB_URL", f"sqlite:///{tmp_path / 'submit.db'}")
    monkeypatch.setenv(
        "FEDCTL_SUBMIT_TOKEN_MAP",
        json.dumps(
            {
                "tok-alice": {"name": "alice", "role": "user"},
                "tok-bob": {"name": "bob", "role": "user"},
                "tok-admin": {"name": "ops", "role": "admin"},
            }
        ),
    )
    monkeypatch.delenv("FEDCTL_SUBMIT_TOKENS", raising=False)
    monkeypatch.setenv("FEDCTL_SUBMIT_ALLOW_UNAUTH", "false")
    monkeypatch.setenv("SUBMIT_DISPATCH_MODE", "queue")
    app = create_app()
    client = TestClient(app)

    alice_headers = {"Authorization": "Bearer tok-alice"}
    bob_headers = {"Authorization": "Bearer tok-bob"}
    admin_headers = {"Authorization": "Bearer tok-admin"}

    alice_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()[
        "submission_id"
    ]
    bob_id = client.post("/v1/submissions", json=_payload(), headers=bob_headers).json()[
        "submission_id"
    ]

    alice_list = client.get("/v1/submissions", headers=alice_headers)
    assert alice_list.status_code == 200
    alice_ids = {item["submission_id"] for item in alice_list.json()}
    assert alice_id in alice_ids
    assert bob_id not in alice_ids

    alice_get_bob = client.get(f"/v1/submissions/{bob_id}", headers=alice_headers)
    assert alice_get_bob.status_code == 404

    alice_cancel_bob = client.post(f"/v1/submissions/{bob_id}/cancel", headers=alice_headers)
    assert alice_cancel_bob.status_code == 404

    admin_cancel_bob = client.post(f"/v1/submissions/{bob_id}/cancel", headers=admin_headers)
    assert admin_cancel_bob.status_code == 200
    assert admin_cancel_bob.json()["status"] == "cancelled"


def test_owner_can_purge_single_terminal_submission_only(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUBMIT_REPO_CONFIG", str(tmp_path / "missing-fedctl.yaml"))
    monkeypatch.setenv("SUBMIT_DB_URL", f"sqlite:///{tmp_path / 'submit.db'}")
    monkeypatch.setenv(
        "FEDCTL_SUBMIT_TOKEN_MAP",
        json.dumps(
            {
                "tok-user": {"name": "alice", "role": "user"},
                "tok-admin": {"name": "ops", "role": "admin"},
            }
        ),
    )
    monkeypatch.delenv("FEDCTL_SUBMIT_TOKENS", raising=False)
    monkeypatch.setenv("FEDCTL_SUBMIT_ALLOW_UNAUTH", "false")
    app = create_app()
    client = TestClient(app)

    user_headers = {"Authorization": "Bearer tok-user"}
    admin_headers = {"Authorization": "Bearer tok-admin"}

    first_id = client.post("/v1/submissions", json=_payload(), headers=user_headers).json()[
        "submission_id"
    ]
    second_payload = dict(_payload())
    second_payload["experiment"] = "mnist-20250126"
    second_id = client.post(
        "/v1/submissions",
        json=second_payload,
        headers=user_headers,
    ).json()["submission_id"]

    active = client.post(f"/v1/submissions/{first_id}/purge", headers=user_headers)
    assert active.status_code == 409

    client.app.state.storage.update_submission(first_id, {"status": "completed"})

    purged = client.post(f"/v1/submissions/{first_id}/purge", headers=user_headers)
    assert purged.status_code == 200
    assert purged.json() == {"status": "ok"}

    missing = client.get(f"/v1/submissions/{first_id}", headers=admin_headers)
    assert missing.status_code == 404

    remaining = client.get(f"/v1/submissions/{second_id}", headers=admin_headers)
    assert remaining.status_code == 200
    assert remaining.json()["submission_id"] == second_id

    foreign = client.post(f"/v1/submissions/{second_id}/purge", headers=admin_headers)
    assert foreign.status_code == 409


def test_logs_falls_back_to_archived_when_nomad_unavailable(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_client(tmp_path, monkeypatch)
    submission_id = client.post("/v1/submissions", json=_payload()).json()["submission_id"]

    update = client.post(
        f"/v1/submissions/{submission_id}/logs",
        json={
            "logs_location": "inline://submit-service-db",
            "logs_archive": {
                "schema": "v1",
                "entries": [
                    {
                        "job": "submit",
                        "index": 1,
                        "task": "submit",
                        "stderr": True,
                        "content": "archived submit stderr",
                    },
                    {
                        "job": "superlink",
                        "index": 1,
                        "task": "exp-superlink",
                        "stderr": True,
                        "content": "archived superlink stderr",
                    },
                ],
            },
        },
    )
    assert update.status_code == 200

    submit_logs = client.get(f"/v1/submissions/{submission_id}/logs")
    assert submit_logs.status_code == 200
    assert submit_logs.text == "archived submit stderr"

    superlink_logs = client.get(
        f"/v1/submissions/{submission_id}/logs",
        params={"job": "superlink", "task": "exp-superlink"},
    )
    assert superlink_logs.status_code == 200
    assert superlink_logs.text == "archived superlink stderr"


def test_logs_falls_back_to_external_manifest_when_nomad_unavailable(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_client(tmp_path, monkeypatch)
    submission_id = client.post("/v1/submissions", json=_payload()).json()["submission_id"]

    update = client.post(
        f"/v1/submissions/{submission_id}/logs",
        json={
            "logs_location": "https://storage.example/logs/sub-1/manifest.json",
        },
    )
    assert update.status_code == 200

    manifest = {
        "schema": "v1-external",
        "entries": [
            {
                "job": "submit",
                "index": 1,
                "task": "submit",
                "stderr": True,
                "url": "https://storage.example/logs/sub-1/submit.stderr.log",
            },
            {
                "job": "superlink",
                "index": 1,
                "task": "exp-superlink",
                "stderr": True,
                "url": "https://storage.example/logs/sub-1/superlink.stderr.log",
            },
            {
                "job": "supernodes",
                "index": 2,
                "task": "rpi5-002",
                "stderr": True,
                "url": "https://storage.example/logs/sub-1/supernode-2.stderr.log",
            },
            {
                "job": "superexec_clientapps",
                "index": 1,
                "task": "clientapp-1",
                "stderr": True,
                "url": "https://storage.example/logs/sub-1/client.stderr.log",
            },
        ],
    }

    class FakeResponse:
        def __init__(self, text: str):
            self.text = text

        def raise_for_status(self) -> None:
            return None

    def fake_get(url: str, timeout: float):  # noqa: ANN001
        if url.endswith("manifest.json"):
            return FakeResponse(json.dumps(manifest))
        if url.endswith("submit.stderr.log"):
            return FakeResponse("external submit stderr")
        if url.endswith("superlink.stderr.log"):
            return FakeResponse("external superlink stderr")
        if url.endswith("supernode-2.stderr.log"):
            return FakeResponse("external supernode stderr")
        if url.endswith("client.stderr.log"):
            return FakeResponse("external client stderr")
        raise AssertionError(url)

    monkeypatch.setattr("submit_service.app.submissions_service.httpx.get", fake_get)

    submit_logs = client.get(f"/v1/submissions/{submission_id}/logs")
    assert submit_logs.status_code == 200
    assert submit_logs.text == "external submit stderr"

    superlink_logs = client.get(
        f"/v1/submissions/{submission_id}/logs",
        params={"job": "superlink", "task": "exp-superlink"},
    )
    assert superlink_logs.status_code == 200
    assert superlink_logs.text == "external superlink stderr"

    supernode_logs = client.get(
        f"/v1/submissions/{submission_id}/logs",
        params={"job": "supernodes", "index": 2},
    )
    assert supernode_logs.status_code == 200
    assert supernode_logs.text == "external supernode stderr"

    client_logs = client.get(
        f"/v1/submissions/{submission_id}/logs",
        params={"job": "superexec_clientapps", "task": "clientapp-1"},
    )
    assert client_logs.status_code == 200
    assert client_logs.text == "external client stderr"


def test_create_app_starts_dispatcher_for_immediate_mode_with_nomad(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import submit_service.app.main as main_mod

    starts: list[str] = []
    stops: list[str] = []

    class FakeDispatcher:
        def __init__(self, storage, cfg):
            self.storage = storage
            self.cfg = cfg

        def start(self) -> None:
            starts.append("start")

        def stop(self) -> None:
            stops.append("stop")

    monkeypatch.setenv("SUBMIT_REPO_CONFIG", str(tmp_path / "missing-fedctl.yaml"))
    monkeypatch.setenv("SUBMIT_DB_URL", f"sqlite:///{tmp_path / 'submit.db'}")
    monkeypatch.setenv("FEDCTL_SUBMIT_ALLOW_UNAUTH", "true")
    monkeypatch.setenv("SUBMIT_DISPATCH_MODE", "immediate")
    monkeypatch.setenv("SUBMIT_NOMAD_ENDPOINT", "http://nomad.example:4646")
    monkeypatch.setattr(main_mod, "Dispatcher", FakeDispatcher)

    with TestClient(main_mod.create_app()):
        pass

    assert starts == ["start"]
    assert stops == ["stop"]


def test_logs_use_index_to_resolve_supernode_task_and_matching_alloc(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_client(tmp_path, monkeypatch)
    storage = client.app.state.storage
    submission_id = client.post("/v1/submissions", json=_payload()).json()["submission_id"]
    storage.update_submission(
        submission_id,
        {
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
        },
    )
    client.app.state.cfg.nomad_endpoint = "http://nomad.example:4646"

    class FakeNomadClient:
        def __init__(self, *args, **kwargs):
            self.calls: list[tuple[str, str]] = []

        def job_allocations(self, job_id: str):
            assert job_id == "job-supernodes"
            return [
                {
                    "ID": "alloc-newer-wrong-task",
                    "ModifyTime": 20,
                    "TaskStates": {"supernode-rpi4-1": {}},
                },
                {
                    "ID": "alloc-older-correct-task",
                    "ModifyTime": 10,
                    "TaskStates": {"supernode-rpi5-1": {}},
                },
            ]

        def alloc_logs(self, alloc_id: str, task: str, *, stderr: bool = True, follow: bool = False):
            assert alloc_id == "alloc-older-correct-task"
            assert task == "supernode-rpi5-1"
            assert stderr is True
            assert follow is False
            return "live supernode stderr"

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "submit_service.app.submissions_service.NomadClient",
        FakeNomadClient,
    )

    response = client.get(
        f"/v1/submissions/{submission_id}/logs",
        params={"job": "supernodes", "index": 2},
    )

    assert response.status_code == 200
    assert response.text == "live supernode stderr"
