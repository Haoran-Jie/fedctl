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
