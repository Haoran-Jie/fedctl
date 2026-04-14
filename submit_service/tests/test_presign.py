from __future__ import annotations

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("itsdangerous")
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


def test_presign_uses_server_default_ttl_when_expires_omitted(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_client(tmp_path, monkeypatch)
    monkeypatch.setenv("FEDCTL_PRESIGN_TTL", "21600")

    captured: dict[str, object] = {}

    class FakeS3Client:
        def generate_presigned_url(self, operation, *, Params, ExpiresIn):
            captured["operation"] = operation
            captured["params"] = Params
            captured["expires"] = ExpiresIn
            return "https://signed.example/object"

    monkeypatch.setattr("submit_service.app.routes.presign._s3_client", lambda: FakeS3Client())

    response = client.post(
        "/v1/presign",
        json={
            "bucket": "fedctl-submits",
            "key": "fedctl-submits/project.tar.gz",
            "method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"url": "https://signed.example/object"}
    assert captured["operation"] == "get_object"
    assert captured["params"] == {
        "Bucket": "fedctl-submits",
        "Key": "fedctl-submits/project.tar.gz",
    }
    assert captured["expires"] == 21600
