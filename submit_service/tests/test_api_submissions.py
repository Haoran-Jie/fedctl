from __future__ import annotations

import os

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from submit_service.app.main import create_app


def _make_client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("SUBMIT_DB_URL", f"sqlite:///{tmp_path / 'submit.db'}")
    monkeypatch.setenv("FEDCTL_SUBMIT_ALLOW_UNAUTH", "true")
    monkeypatch.setenv("SUBMIT_DISPATCH_MODE", "immediate")
    app = create_app()
    return TestClient(app)


def test_create_and_get_submission(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path, monkeypatch)
    payload = {
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


def test_auth_requires_token(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBMIT_DB_URL", f"sqlite:///{tmp_path / 'submit.db'}")
    monkeypatch.setenv("FEDCTL_SUBMIT_TOKENS", "token1")
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
