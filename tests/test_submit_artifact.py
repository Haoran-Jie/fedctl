from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import fedctl.commands.submit as submit_cmd
import fedctl.submit.artifact as artifact


def test_upload_artifact_uses_explicit_presign_service(
    monkeypatch, tmp_path: Path
) -> None:
    archive = tmp_path / "project.tar.gz"
    archive.write_bytes(b"artifact-bytes")
    captured: dict[str, object] = {}

    def fake_upload_via_presign_service(
        archive_path: Path,
        presign_endpoint: str,
        *,
        bucket: str,
        key: str,
        token: str | None = None,
    ) -> str:
        captured["archive_path"] = archive_path
        captured["presign_endpoint"] = presign_endpoint
        captured["bucket"] = bucket
        captured["key"] = key
        captured["token"] = token
        return "https://signed.example/get-object"

    monkeypatch.setattr(
        artifact,
        "_upload_via_presign_service",
        fake_upload_via_presign_service,
    )

    url = artifact.upload_artifact(
        archive,
        "s3+presign://fedctl-submits/fedctl-submits",
        presign_endpoint="http://submit.example:8080/v1/presign",
        presign_token="token-123",
    )

    assert url == "https://signed.example/get-object"
    assert captured == {
        "archive_path": archive,
        "presign_endpoint": "http://submit.example:8080/v1/presign",
        "bucket": "fedctl-submits",
        "key": "fedctl-submits/project.tar.gz",
        "token": "token-123",
    }


def test_run_submit_passes_submit_service_context_to_artifact_upload(
    monkeypatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    archive = tmp_path / "project.tar.gz"
    archive.write_bytes(b"artifact-bytes")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        submit_cmd,
        "inspect_flwr_project",
        lambda _: SimpleNamespace(
            project_name="demo-project",
            local_sim_num_supernodes=None,
            root=project_root,
        ),
    )
    monkeypatch.setattr(
        submit_cmd,
        "resolve_repo_config",
        lambda **_: SimpleNamespace(
            data={
                "submit": {
                    "image": "submit-image:latest",
                    "artifact_store": "s3+presign://fedctl-submits/fedctl-submits",
                    "endpoint": "http://submit.example:8080",
                    "token": "token-from-config",
                }
            },
            path=None,
        ),
    )

    class FakeSubmitClient:
        endpoint = "http://submit.example:8080"
        token = "token-from-client"

        def create_submission(self, payload):
            captured["submission_payload"] = payload
            return {"submission_id": "sub-123"}

    monkeypatch.setattr(
        submit_cmd,
        "_submit_service_client",
        lambda **_: FakeSubmitClient(),
    )
    monkeypatch.setattr(
        submit_cmd,
        "_build_project_archive",
        lambda *_, **__: archive,
    )

    def fake_upload_artifact(archive_path, artifact_store, **kwargs):
        captured["archive_path"] = archive_path
        captured["artifact_store"] = artifact_store
        captured["upload_kwargs"] = kwargs
        return "https://signed.example/get-object"

    monkeypatch.setattr(submit_cmd, "upload_artifact", fake_upload_artifact)
    monkeypatch.setattr(submit_cmd, "load_config", lambda: object())
    monkeypatch.setattr(
        submit_cmd,
        "get_effective_config",
        lambda _: SimpleNamespace(namespace="default"),
    )

    status = submit_cmd.run_submit(
        path=str(project_root),
        flwr_version="1.25.0",
        image="superexec-image:latest",
        no_cache=False,
        platform=None,
        context=None,
        push=False,
        num_supernodes=3,
        auto_supernodes=True,
        supernodes=None,
        net=None,
        allow_oversubscribe=None,
        repo_config=None,
        experiment="demo-exp",
        timeout_seconds=120,
        federation="remote-deployment",
        stream=True,
        verbose=False,
        destroy=True,
        submit_image=None,
        artifact_store=None,
        priority=50,
    )

    assert status == 0
    assert captured["archive_path"] == archive
    assert captured["artifact_store"] == "s3+presign://fedctl-submits/fedctl-submits"
    assert captured["upload_kwargs"] == {
        "presign_endpoint": "http://submit.example:8080/v1/presign",
        "presign_token": "token-from-client",
    }
    submit_request = captured["submission_payload"]["submit_request"]
    assert submit_request["path_input"] == str(project_root)
    assert submit_request["project_root"] == str(project_root.resolve())
    assert "fedctl submit run" in submit_request["command_preview"]
    assert submit_request["options"]["experiment"] == "demo-exp"


def test_run_submit_rewrites_cluster_images_to_internal_registry(
    monkeypatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    archive = tmp_path / "project.tar.gz"
    archive.write_bytes(b"artifact-bytes")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        submit_cmd,
        "inspect_flwr_project",
        lambda _: SimpleNamespace(
            project_name="demo-project",
            local_sim_num_supernodes=None,
            root=project_root,
        ),
    )
    monkeypatch.setattr(
        submit_cmd,
        "resolve_repo_config",
        lambda **_: SimpleNamespace(
            data={
                "submit": {
                    "image": "100.108.13.23:5000/fedctl-submit:latest",
                    "artifact_store": "s3+presign://fedctl-submits/fedctl-submits",
                    "endpoint": "http://submit.example:8080",
                    "token": "token-from-config",
                },
                "submit-service": {
                    "image_registry": "192.168.8.101:5000",
                },
                "image_registry": "100.108.13.23:5000",
            },
            path=None,
        ),
    )

    class FakeSubmitClient:
        endpoint = "http://submit.example:8080"
        token = "token-from-client"

        def create_submission(self, payload):
            captured["submission_payload"] = payload
            return {"submission_id": "sub-123"}

    monkeypatch.setattr(
        submit_cmd,
        "_submit_service_client",
        lambda **_: FakeSubmitClient(),
    )
    monkeypatch.setattr(
        submit_cmd,
        "_build_project_archive",
        lambda *_, **__: archive,
    )
    monkeypatch.setattr(
        submit_cmd,
        "upload_artifact",
        lambda *_, **__: "https://signed.example/get-object",
    )
    monkeypatch.setattr(submit_cmd, "load_config", lambda: object())
    monkeypatch.setattr(
        submit_cmd,
        "get_effective_config",
        lambda _: SimpleNamespace(namespace="default"),
    )

    status = submit_cmd.run_submit(
        path=str(project_root),
        flwr_version="1.25.0",
        image=None,
        no_cache=False,
        platform=None,
        context=None,
        push=False,
        num_supernodes=3,
        auto_supernodes=True,
        supernodes=None,
        net=None,
        allow_oversubscribe=None,
        repo_config=None,
        experiment="demo-exp",
        timeout_seconds=120,
        federation="remote-deployment",
        stream=True,
        verbose=False,
        destroy=True,
        submit_image=None,
        artifact_store=None,
        priority=50,
    )

    assert status == 0
    payload = captured["submission_payload"]
    assert payload["submit_image"] == "192.168.8.101:5000/fedctl-submit:latest"
    image_idx = payload["args"].index("--image") + 1
    assert payload["args"][image_idx].startswith("192.168.8.101:5000/demo-project-superexec:")
