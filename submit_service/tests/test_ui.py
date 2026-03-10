from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from submit_service.app.main import create_app
from submit_service.app.routes import ui as ui_routes


TOKEN_MAP = {
    "tok-alice": {"name": "alice", "role": "user"},
    "tok-bob": {"name": "bob", "role": "user"},
    "tok-admin": {"name": "ops", "role": "admin"},
}


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


def _make_ui_client(tmp_path, monkeypatch: pytest.MonkeyPatch, *, enabled: bool = True) -> TestClient:
    monkeypatch.setenv("SUBMIT_REPO_CONFIG", str(tmp_path / "missing-fedctl.yaml"))
    monkeypatch.setenv("SUBMIT_DB_URL", f"sqlite:///{tmp_path / 'submit.db'}")
    monkeypatch.setenv("FEDCTL_SUBMIT_TOKEN_MAP", json.dumps(TOKEN_MAP))
    monkeypatch.delenv("FEDCTL_SUBMIT_TOKENS", raising=False)
    monkeypatch.setenv("FEDCTL_SUBMIT_ALLOW_UNAUTH", "false")
    monkeypatch.setenv("SUBMIT_DISPATCH_MODE", "queue")
    monkeypatch.setenv("SUBMIT_UI_ENABLED", "true" if enabled else "false")
    monkeypatch.setenv("SUBMIT_UI_SESSION_SECRET", "test-ui-secret")
    app = create_app()
    return TestClient(app)


def _login(client: TestClient, token: str) -> None:
    response = client.post("/ui/login", data={"token": token}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/ui/submissions"


def test_ui_disabled_returns_404(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_ui_client(tmp_path, monkeypatch, enabled=False)
    response = client.get("/ui/login")
    assert response.status_code == 404


def test_ui_requires_session_and_login_succeeds(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)

    response = client.get("/")
    assert response.status_code == 200
    assert "Bearer token" in response.text

    bad = client.post("/ui/login", data={"token": "wrong"})
    assert bad.status_code == 403
    assert "Invalid token" in bad.text

    _login(client, "tok-alice")
    page = client.get("/ui/submissions")
    assert page.status_code == 200
    assert "Submissions" in page.text


def test_ui_user_scope_cancel_and_purge(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)
    storage = client.app.state.storage

    alice_headers = {"Authorization": "Bearer tok-alice"}
    bob_headers = {"Authorization": "Bearer tok-bob"}
    alice_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]
    bob_id = client.post("/v1/submissions", json=_payload(), headers=bob_headers).json()["submission_id"]

    _login(client, "tok-alice")
    listing = client.get("/ui/submissions?status=all")
    assert alice_id in listing.text
    assert bob_id not in listing.text

    other = client.get(f"/ui/submissions/{bob_id}")
    assert other.status_code == 404

    cancel = client.post(f"/ui/submissions/{alice_id}/cancel", follow_redirects=False)
    assert cancel.status_code == 303
    detail = client.get(f"/ui/submissions/{alice_id}")
    assert "cancelled" in detail.text
    assert "Purge submission" in detail.text

    purge = client.post(f"/ui/submissions/{alice_id}/purge", follow_redirects=False)
    assert purge.status_code == 303
    assert purge.headers["location"] == "/ui/submissions"

    missing = client.get(f"/ui/submissions/{alice_id}")
    assert missing.status_code == 404

    storage.update_submission(bob_id, {"status": "completed"})
    foreign = client.post(f"/ui/submissions/{bob_id}/purge", follow_redirects=False)
    assert foreign.status_code == 404


def test_ui_admin_can_view_nodes_and_all_submissions(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)
    client.app.state.inventory = type(
        "DummyInventory",
        (),
        {
            "list_nodes": staticmethod(
                lambda include_allocs=True: [
                    {
                        "name": "rpi2",
                        "id": "node-1",
                        "status": "ready",
                        "node_class": "submit",
                        "device_type": "rpi",
                        "allocations": [],
                    }
                ]
            )
        },
    )()

    alice_headers = {"Authorization": "Bearer tok-alice"}
    alice_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]

    _login(client, "tok-admin")
    listing = client.get("/ui/submissions?status=all")
    assert alice_id in listing.text
    assert "alice" in listing.text

    nodes = client.get("/ui/nodes")
    assert nodes.status_code == 200
    assert "Nodes" in nodes.text


def test_ui_stats_are_based_on_all_visible_submissions_not_active_filter(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)
    storage = client.app.state.storage

    alice_headers = {"Authorization": "Bearer tok-alice"}
    queued_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]
    completed_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]
    failed_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]
    blocked_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]

    storage.update_submission(queued_id, {"status": "running"})
    storage.update_submission(completed_id, {"status": "completed"})
    storage.update_submission(failed_id, {"status": "failed"})
    storage.update_submission(blocked_id, {"status": "blocked"})

    _login(client, "tok-alice")
    page = client.get("/ui/submissions?status=active")
    assert page.status_code == 200
    assert "<strong>4</strong>" in page.text
    assert "<strong>2</strong>" in page.text
    assert "<strong>1</strong>" in page.text


def test_ui_non_admin_redirected_from_nodes(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)
    _login(client, "tok-alice")
    response = client.get("/ui/nodes", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/ui/submissions"


def test_ui_detail_shows_archived_logs(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)

    alice_headers = {"Authorization": "Bearer tok-alice"}
    submission_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]
    client.post(
        f"/v1/submissions/{submission_id}/logs",
        json={
            "logs_archive": {
                "schema": "v1",
                "entries": [
                    {
                        "job": "submit",
                        "index": 1,
                        "task": "submit",
                        "stderr": True,
                        "content": "archived submit stderr",
                    }
                ],
            }
        },
        headers=alice_headers,
    )

    _login(client, "tok-alice")
    detail = client.get(f"/ui/submissions/{submission_id}")
    assert detail.status_code == 200
    assert "archived submit stderr" in detail.text


def test_ui_detail_renders_structured_args_env_and_jobs(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)
    storage = client.app.state.storage

    alice_headers = {"Authorization": "Bearer tok-alice"}
    submission_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]
    storage.update_submission(
        submission_id,
        {
            "jobs": {
                "superlink": {
                    "job_id": "job-superlink",
                    "task": "superlink",
                    "alloc_group": "core",
                }
            }
        },
    )

    _login(client, "tok-alice")
    detail = client.get(f"/ui/submissions/{submission_id}")
    assert detail.status_code == 200
    assert "Runner args" in detail.text
    assert "FEDCTL_ENDPOINT" in detail.text
    assert "Job IDs" in detail.text
    assert "job-superlink" in detail.text


def test_ui_requires_secret_when_enabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBMIT_REPO_CONFIG", str(tmp_path / "missing-fedctl.yaml"))
    monkeypatch.setenv("SUBMIT_DB_URL", f"sqlite:///{tmp_path / 'submit.db'}")
    monkeypatch.setenv("FEDCTL_SUBMIT_TOKEN_MAP", json.dumps(TOKEN_MAP))
    monkeypatch.setenv("SUBMIT_UI_ENABLED", "true")
    monkeypatch.delenv("SUBMIT_UI_SESSION_SECRET", raising=False)
    monkeypatch.setenv("FEDCTL_SUBMIT_ALLOW_UNAUTH", "false")
    monkeypatch.setenv("SUBMIT_DISPATCH_MODE", "queue")

    with pytest.raises(RuntimeError, match="SUBMIT_UI_SESSION_SECRET"):
        create_app()


def test_render_logs_html_converts_ansi_sequences() -> None:
    rendered = ui_routes._render_logs_html("\x1b[92mINFO\x1b[0m: hello")
    assert "INFO" in rendered
    assert "\x1b[" not in rendered
    assert "style=" in rendered or "color:" in rendered
