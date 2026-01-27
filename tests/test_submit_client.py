from __future__ import annotations

import httpx

from fedctl.submit.client import SubmitServiceClient, SubmitServiceError


class DummyResp:
    def __init__(self, status_code: int, text: str, json_obj=None):
        self.status_code = status_code
        self.text = text
        self._json = json_obj

    def json(self):
        return self._json


def test_submit_client_sends_auth_headers(monkeypatch) -> None:
    captured = {}

    def fake_request(method, url, json=None, params=None, headers=None, timeout=None):
        captured["headers"] = headers
        return DummyResp(200, "{}", json_obj={"ok": True})

    monkeypatch.setattr(httpx, "request", fake_request)

    client = SubmitServiceClient(
        endpoint="http://submit.example",
        token="token-123",
        user="alice",
    )
    resp = client.create_submission({"project_name": "proj"})
    assert resp["ok"] is True
    assert captured["headers"]["Authorization"] == "Bearer token-123"
    assert captured["headers"]["X-Submit-User"] == "alice"


def test_submit_client_raises_on_http_error(monkeypatch) -> None:
    def fake_request(method, url, json=None, params=None, headers=None, timeout=None):
        return DummyResp(500, "boom")

    monkeypatch.setattr(httpx, "request", fake_request)

    client = SubmitServiceClient(endpoint="http://submit.example")
    try:
        client.list_submissions()
    except SubmitServiceError as exc:
        assert "500" in str(exc)
    else:
        raise AssertionError("Expected SubmitServiceError")
