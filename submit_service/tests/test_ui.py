from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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
    assert "data-toast-root" in page.text
    assert "data-sticky-panel" in page.text
    assert "data-sticky-shell" in page.text
    assert 'aria-label="Submission status filters"' in page.text
    assert '>Active<' in page.text
    assert '>Completed<' in page.text
    assert '>Failed<' in page.text
    assert '>Cancelled<' in page.text
    assert '>All<' in page.text
    assert '<select name="status"' not in page.text
    assert 'data-auto-submit="260"' in page.text
    assert ">Search</button>" not in page.text


def test_ui_registers_generated_bearer_token(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBMIT_REPO_CONFIG", str(tmp_path / "missing-fedctl.yaml"))
    monkeypatch.setenv("SUBMIT_DB_URL", f"sqlite:///{tmp_path / 'submit.db'}")
    monkeypatch.delenv("FEDCTL_SUBMIT_TOKENS", raising=False)
    monkeypatch.delenv("FEDCTL_SUBMIT_TOKEN_MAP", raising=False)
    monkeypatch.setenv("FEDCTL_SUBMIT_ALLOW_UNAUTH", "false")
    monkeypatch.setenv("SUBMIT_DISPATCH_MODE", "queue")
    monkeypatch.setenv("SUBMIT_UI_ENABLED", "true")
    monkeypatch.setenv("SUBMIT_UI_SESSION_SECRET", "test-ui-secret")
    monkeypatch.setenv("SUBMIT_REGISTRATION_ENABLED", "true")
    monkeypatch.setenv("SUBMIT_REGISTRATION_CODE", "cammlsys")
    client = TestClient(create_app())

    login = client.get("/ui/login")
    assert login.status_code == 200
    assert "Register a bearer token" in login.text

    form = client.post(
        "/ui/register",
        data={"name": "alice", "registration_code": "cammlsys"},
    )
    assert form.status_code == 200
    assert "Token registered for alice" in form.text
    assert "fedctl_" in form.text
    assert "export FEDCTL_SUBMIT_TOKEN=fedctl_" in form.text
    match = re.search(r"fedctl_[A-Za-z0-9_-]+", form.text)
    assert match is not None
    login = client.post("/ui/login", data={"token": match.group(0)}, follow_redirects=False)
    assert login.status_code == 303
    assert login.headers["location"] == "/ui/submissions"


def test_ui_help_page_shows_submit_commands(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)
    _login(client, "tok-alice")

    page = client.get("/ui/help")
    assert page.status_code == 200
    assert "fedctl submit run" in page.text
    assert "fedctl submit register-token" in page.text
    assert "fedctl submit inventory" in page.text
    assert "Most important" in page.text
    assert "On this page" in page.text
    assert 'href="#quickstart"' in page.text
    assert "Install fedctl" in page.text
    assert "python -m pip install fedctl" in page.text
    assert "Register a bearer token" in page.text
    assert "Register a user-scoped bearer token from the CLI" in page.text
    assert "fedctl submit register-token --name &lt;username&gt;" in page.text
    assert "submit-service bearer token" in page.text
    assert "~/.config/fedctl/config.toml" in page.text
    assert "~/.config/fedctl/deploy-default.yaml" in page.text
    assert "FEDCTL_SUBMIT_TOKEN" in page.text
    assert "fedctl submit run &lt;project-dir&gt;" in page.text
    assert "fedctl submit run &lt;project-dir&gt; --stream" not in page.text
    assert "--experiment-config path/to/experiment.toml" in page.text
    assert "--deploy-config path/to/deploy.yaml" in page.text
    assert "fedctl submit results &lt;submission-id&gt; --download --out ./results" in page.text
    assert 'href="#configs"' in page.text
    assert "Config files" in page.text
    assert "Experiment config" in page.text
    assert "Deploy config" in page.text
    assert "--experiment-config" in page.text
    assert "--deploy-config" in page.text
    assert 'href="http://testserver/ui/help/config/experiment-config"' in page.text
    assert 'href="http://testserver/ui/help/config/deploy-config"' in page.text
    assert 'id="config-experiment-config"' in page.text
    assert 'id="config-deploy-config"' in page.text
    assert 'id="command-submit-run"' in page.text
    assert 'data-copy-label="Link"' in page.text
    assert 'data-back-to-top' in page.text


def test_ui_help_config_detail_pages_show_rich_guidance(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)
    _login(client, "tok-alice")

    experiment_page = client.get("/ui/help/config/experiment-config")
    assert experiment_page.status_code == 200
    assert "Experiment config" in experiment_page.text
    assert "Run settings passed to Flower" in experiment_page.text
    assert "Workflow" in experiment_page.text
    assert "File shape" in experiment_page.text
    assert "Sectioned TOML is normalized into Flower" in experiment_page.text
    assert "--run-config-override" in experiment_page.text
    assert "It does not contain the submit-service bearer token." in experiment_page.text
    assert 'href="http://testserver/ui/help/submit-run"' in experiment_page.text

    deploy_page = client.get("/ui/help/config/deploy-config")
    assert deploy_page.status_code == 200
    assert "Deploy config" in deploy_page.text
    assert "Execution environment used by fedctl" in deploy_page.text
    assert "Supported fields" in deploy_page.text
    assert "These are the deploy-config fields currently consumed by fedctl." in deploy_page.text
    assert "Fresh-install setup" in deploy_page.text
    assert "Resolution order" in deploy_page.text
    assert "submit.endpoint" in deploy_page.text
    assert "submit.token" in deploy_page.text
    assert "submit.image" in deploy_page.text
    assert "submit.artifact_store" in deploy_page.text
    assert "submit.user" in deploy_page.text
    assert "deploy.superexec.env" in deploy_page.text
    assert "deploy.placement.allow_oversubscribe" in deploy_page.text
    assert "deploy.placement.prefer_spread_across_hosts" in deploy_page.text
    assert "deploy.resources.supernode.default" in deploy_page.text
    assert "deploy.resources.superexec_clientapp" in deploy_page.text
    assert "deploy.network.default_assignment" in deploy_page.text
    assert "deploy.network.apply.superexec_clientapp" in deploy_page.text
    assert "deploy.network.ingress_profiles.&lt;name&gt;" in deploy_page.text
    assert "FEDCTL_SUBMIT_TOKEN" in deploy_page.text
    assert "128.232.61.111:5000" in deploy_page.text
    assert "local-simulation.num-supernodes" in deploy_page.text
    assert "Legacy top-level registry fallback" in deploy_page.text
    assert "--repo-config" in deploy_page.text


def test_ui_help_command_detail_shows_rich_guidance(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)
    _login(client, "tok-alice")

    page = client.get("/ui/help/submit-run")
    assert page.status_code == 200
    assert "When to use it" in page.text
    assert "Dissertation experiment with explicit config" in page.text
    assert "Related commands" in page.text
    assert "submit logs" in page.text

    register_page = client.get("/ui/help/submit-register-token")
    assert register_page.status_code == 200
    assert "Register a user-scoped bearer token" in register_page.text
    assert "--registration-code" in register_page.text
    assert "--print-token" in register_page.text


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
    cancel_location = urlsplit(cancel.headers["location"])
    assert cancel_location.path == f"/ui/submissions/{alice_id}"
    cancel_query = parse_qs(cancel_location.query)
    assert cancel_query["notice"] == ["Submission cancelled."]
    assert cancel_query["notice_kind"] == ["success"]
    detail = client.get(f"/ui/submissions/{alice_id}")
    assert "cancelled" in detail.text
    assert "Purge submission" in detail.text

    filtered_detail = client.get(f"/ui/submissions/{alice_id}?return_to=/ui/submissions?status=completed")
    assert 'href="/ui/submissions?status=completed"' in filtered_detail.text

    purge = client.post(
        f"/ui/submissions/{alice_id}/purge",
        data={"return_to": "/ui/submissions?status=completed"},
        follow_redirects=False,
    )
    assert purge.status_code == 303
    purge_location = urlsplit(purge.headers["location"])
    assert purge_location.path == "/ui/submissions"
    purge_query = parse_qs(purge_location.query)
    assert purge_query["status"] == ["completed"]
    assert purge_query["notice"] == ["Submission purged."]
    assert purge_query["notice_kind"] == ["success"]

    missing = client.get(f"/ui/submissions/{alice_id}")
    assert missing.status_code == 404

    storage.update_submission(bob_id, {"status": "completed"})
    foreign = client.post(f"/ui/submissions/{bob_id}/purge", follow_redirects=False)
    assert foreign.status_code == 404


def test_ui_active_queue_shows_foreign_runs_without_detail_access(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)

    alice_headers = {"Authorization": "Bearer tok-alice"}
    bob_headers = {"Authorization": "Bearer tok-bob"}
    alice_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]
    bob_payload = _payload()
    bob_payload["project_name"] = "secret-project"
    bob_payload["experiment"] = "secret-experiment"
    bob_id = client.post("/v1/submissions", json=bob_payload, headers=bob_headers).json()["submission_id"]

    _login(client, "tok-alice")
    active = client.get("/ui/submissions?status=active")
    assert active.status_code == 200
    assert alice_id in active.text
    assert bob_id in active.text
    assert f'href="/ui/submissions/{alice_id}' in active.text
    assert f'href="/ui/submissions/{bob_id}' not in active.text
    assert f'data-href="/ui/submissions/{bob_id}' not in active.text
    assert "tok-bob" not in active.text
    assert "bob" in active.text
    assert "Private submission" in active.text
    assert "secret-project" not in active.text
    assert "secret-experiment" not in active.text

    detail = client.get(f"/ui/submissions/{bob_id}")
    assert detail.status_code == 404
    logs = client.get(f"/ui/submissions/{bob_id}/logs")
    assert logs.status_code == 404


def test_ui_shows_wait_and_runtime_columns(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)
    storage = client.app.state.storage
    headers = {"Authorization": "Bearer tok-alice"}
    submission_id = client.post("/v1/submissions", json=_payload(), headers=headers).json()["submission_id"]
    storage.update_submission(
        submission_id,
        {
            "status": "completed",
            "created_at": "2026-01-01T00:00:00+00:00",
            "started_at": "2026-01-01T00:05:00+00:00",
            "finished_at": "2026-01-01T00:12:30+00:00",
        },
    )

    _login(client, "tok-alice")
    listing = client.get("/ui/submissions?status=all")
    assert listing.status_code == 200
    assert ">Wait<" in listing.text
    assert ">Runtime<" in listing.text
    assert "5m 0s" in listing.text
    assert "7m 30s" in listing.text

    detail = client.get(f"/ui/submissions/{submission_id}")
    assert detail.status_code == 200
    assert "<dt>Queue wait</dt><dd>5m 0s</dd>" in detail.text
    assert "<dt>Runtime</dt><dd>7m 30s</dd>" in detail.text


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
                        "allocations": {
                            "count": 2,
                            "running_jobs": ["job-a"],
                            "items": [
                                {"id": "alloc-1", "job_id": "job-a"},
                                {"id": "alloc-2", "job_id": "job-b"},
                            ],
                        },
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
    assert "data-sticky-panel" in nodes.text
    assert "data-sticky-shell" in nodes.text
    assert ">2</td>" in nodes.text
    assert ">1</td>" in nodes.text
    assert "job-a, job-b" in nodes.text


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


def test_ui_active_list_orders_running_before_blocked(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)
    storage = client.app.state.storage

    alice_headers = {"Authorization": "Bearer tok-alice"}
    blocked_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]
    running_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]
    storage.update_submission(
        blocked_id,
        {
            "status": "blocked",
            "created_at": "2026-01-01T00:00:00+00:00",
            "blocked_reason": "waiting",
        },
    )
    storage.update_submission(
        running_id,
        {
            "status": "running",
            "created_at": "2026-01-01T00:01:00+00:00",
            "started_at": "2026-01-01T00:02:00+00:00",
        },
    )

    _login(client, "tok-alice")
    page = client.get("/ui/submissions?status=active")
    assert page.status_code == 200
    assert page.text.index(running_id.replace("sub-", "", 1)) < page.text.index(blocked_id.replace("sub-", "", 1))


def test_ui_queue_panel_keeps_priority_order_across_queued_and_blocked(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)
    storage = client.app.state.storage

    alice_headers = {"Authorization": "Bearer tok-alice"}
    queued_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]
    blocked_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]
    storage.update_submission(
        queued_id,
        {
            "status": "queued",
            "created_at": "2026-01-01T00:00:00+00:00",
            "priority": 50,
        },
    )
    storage.update_submission(
        blocked_id,
        {
            "status": "blocked",
            "created_at": "2026-01-01T00:01:00+00:00",
            "priority": 100,
            "blocked_reason": "strict placement waits",
        },
    )

    _login(client, "tok-alice")
    page = client.get("/ui/submissions?status=active")

    assert page.status_code == 200
    assert "Pending dispatch" in page.text
    assert page.text.index(blocked_id.replace("sub-", "", 1)) < page.text.index(
        queued_id.replace("sub-", "", 1)
    )


def test_queue_panel_rows_sorts_pending_like_dispatcher() -> None:
    rows = [
        {
            "id": "sub-low",
            "status": "blocked",
            "priority": 50,
            "created_at": {"iso": "2026-01-01T00:00:00+00:00"},
        },
        {
            "id": "sub-high",
            "status": "blocked",
            "priority": 100,
            "created_at": {"iso": "2026-01-01T00:01:00+00:00"},
        },
        {
            "id": "sub-default",
            "status": "queued",
            "priority": None,
            "created_at": {"iso": "2026-01-01T00:02:00+00:00"},
        },
    ]

    queue_rows = ui_routes._queue_panel_rows(rows, default_priority=50)

    assert [row["id"] for row in queue_rows["pending"]] == [
        "sub-high",
        "sub-low",
        "sub-default",
    ]


def test_ui_submissions_search_filters_rows_and_preserves_return_to(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)
    storage = client.app.state.storage

    alice_headers = {"Authorization": "Bearer tok-alice"}
    match_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]
    other_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]
    storage.update_submission(match_id, {"experiment": "vision-run"})
    storage.update_submission(other_id, {"experiment": "nlp-run"})

    _login(client, "tok-alice")
    page = client.get("/ui/submissions?status=all&q=vision")
    assert page.status_code == 200
    assert match_id in page.text
    assert other_id not in page.text
    assert 'name="q"' in page.text
    assert 'value="vision"' in page.text
    assert "return_to=/ui/submissions%3Fstatus%3Dall%26q%3Dvision" in page.text


def test_ui_submissions_paginates_and_preserves_filters(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)
    storage = client.app.state.storage
    alice_headers = {"Authorization": "Bearer tok-alice"}

    first_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]
    second_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]
    third_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]

    storage.update_submission(
        first_id,
        {"status": "completed", "experiment": "vision-first", "created_at": "2026-01-01T00:01:00+00:00"},
    )
    storage.update_submission(
        second_id,
        {"status": "completed", "experiment": "vision-second", "created_at": "2026-01-01T00:02:00+00:00"},
    )
    storage.update_submission(
        third_id,
        {"status": "completed", "experiment": "vision-third", "created_at": "2026-01-01T00:03:00+00:00"},
    )

    _login(client, "tok-alice")
    page_one = client.get("/ui/submissions?status=completed&q=vision&limit=2")
    assert page_one.status_code == 200
    assert "Showing 1-2 of 3" in page_one.text
    assert "Page 1 of 2" in page_one.text
    assert "vision-third" in page_one.text
    assert "vision-second" in page_one.text
    assert "vision-first" not in page_one.text
    assert "/ui/submissions?status=completed&amp;q=vision&amp;page=2&amp;limit=2" in page_one.text

    page_two = client.get("/ui/submissions?status=completed&q=vision&page=2&limit=2")
    assert page_two.status_code == 200
    assert "Showing 3-3 of 3" in page_two.text
    assert "Page 2 of 2" in page_two.text
    assert "vision-first" in page_two.text
    assert "vision-third" not in page_two.text
    assert "return_to=/ui/submissions%3Fstatus%3Dcompleted%26q%3Dvision%26page%3D2%26limit%3D2" in page_two.text


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
                        "stderr": False,
                        "content": "archived submit stdout",
                    },
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
    assert "archived submit stdout" in detail.text
    assert "archived submit stderr" not in detail.text
    assert '<option value="false" selected>stdout</option>' in detail.text
    assert 'data-log-filter' in detail.text
    assert "Copy logs" in detail.text
    assert "Copy link" not in detail.text
    assert 'data-logs-endpoint="/ui/submissions/' in detail.text
    assert "Follow" in detail.text
    assert "Latest" not in detail.text
    assert 'name="task"' not in detail.text

    stderr_detail = client.get(f"/ui/submissions/{submission_id}?stderr=true")
    assert stderr_detail.status_code == 200
    assert "archived submit stderr" in stderr_detail.text
    assert '<option value="true" selected>stderr</option>' in stderr_detail.text


def test_ui_nodes_search_filters_inventory(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
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
                        "allocations": {"count": 0, "running_jobs": [], "items": []},
                    },
                    {
                        "name": "jetson4",
                        "id": "node-2",
                        "status": "ready",
                        "node_class": "gpu",
                        "device_type": "jetson",
                        "allocations": {"count": 1, "running_jobs": ["job-c"], "items": []},
                    },
                ]
            )
        },
    )()

    _login(client, "tok-admin")
    page = client.get("/ui/nodes?q=jet")
    assert page.status_code == 200
    assert "jetson4" in page.text
    assert "rpi2" not in page.text
    assert 'value="jet"' in page.text
    assert 'data-auto-submit="260"' in page.text
    assert 'name="status"' not in page.text
    assert 'name="node_class"' not in page.text
    assert 'name="device_type"' not in page.text


def test_ui_nodes_page_renders_node_resource_totals_and_usage(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
                        "resources": {
                            "total_cpu": 4000,
                            "total_mem": 8192,
                            "used_cpu": 1000,
                            "used_mem": 2048,
                        },
                        "allocations": {
                            "count": 2,
                            "running_jobs": ["job-a"],
                            "items": [
                                {"id": "alloc-1", "job_id": "job-a", "resources": {"cpu": 700, "mem": 1024}},
                                {"id": "alloc-2", "job_id": "job-b", "resources": {"cpu": 300, "mem": 1024}},
                            ],
                        },
                    }
                ]
            )
        },
    )()

    _login(client, "tok-admin")
    page = client.get("/ui/nodes")
    assert page.status_code == 200
    assert "1000/4000 (25%)" in page.text
    assert "2GB/8GB (25%)" in page.text
    assert 'class="resource-bar-fill" style="width: 25%' in page.text
    assert page.text.count('class="resource-segment"') == 4
    assert 'data-job-id="job-a"' in page.text
    assert 'data-job-id="job-b"' in page.text
    assert 'title="CPU: 1000/4000 | Jobs: job-a"' in page.text
    assert 'title="job-a: 700 CPU"' in page.text
    assert 'title="job-b: 1GB"' in page.text


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
            "submit_request": {
                "path_input": "../quickstart-pytorch",
                "project_root": "/tmp/quickstart-pytorch",
                "cwd": "/tmp",
                "command_preview": "fedctl submit run ../quickstart-pytorch --exp mnist-20250125",
                "options": {
                    "path": "../quickstart-pytorch",
                    "experiment": "mnist-20250125",
                    "priority": 50,
                },
            },
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
    assert "Original submit request" in detail.text
    assert "fedctl submit run ../quickstart-pytorch --exp mnist-20250125" in detail.text
    assert "Internal runner args" in detail.text
    assert "Resolved project root" in detail.text
    assert "Job IDs" in detail.text
    assert "job-superlink" in detail.text
    assert "Open logs" in detail.text
    assert "job=superlink" in detail.text
    assert "Show details" in detail.text
    assert "SuperLink" in detail.text
    assert 'data-mapping-detail' in detail.text
    assert "Copy job ID" not in detail.text
    assert "Expand all" not in detail.text


def test_ui_detail_hides_results_tab(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_ui_client(tmp_path, monkeypatch)

    alice_headers = {"Authorization": "Bearer tok-alice"}
    submission_id = client.post("/v1/submissions", json=_payload(), headers=alice_headers).json()["submission_id"]

    _login(client, "tok-alice")
    detail = client.get(f"/ui/submissions/{submission_id}")
    assert detail.status_code == 200
    assert 'id="tab-button-results"' not in detail.text
    assert 'id="tab-results"' not in detail.text


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


def test_submission_list_command_matches_ui_filters() -> None:
    assert ui_routes._submission_list_command("active") == "fedctl submit ls --active"
    assert ui_routes._submission_list_command("completed") == "fedctl submit ls --completed"
    assert ui_routes._submission_list_command("failed") == "fedctl submit ls --failed"
    assert ui_routes._submission_list_command("cancelled") == "fedctl submit ls --cancelled"
    assert ui_routes._submission_list_command("all") == "fedctl submit ls --all"
