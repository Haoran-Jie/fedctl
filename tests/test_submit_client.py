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


class DummyStreamResp:
    def __init__(self, status_code: int = 200, lines: list[str] | None = None):
        self.status_code = status_code
        self._lines = lines or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def iter_lines(self):
        for line in self._lines:
            yield line

    def read(self):
        return b""


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


def test_submit_client_list_submissions_active_only(monkeypatch) -> None:
    captured = {}

    def fake_request(method, url, json=None, params=None, headers=None, timeout=None):
        captured["params"] = params
        return DummyResp(200, "[]", json_obj=[])

    monkeypatch.setattr(httpx, "request", fake_request)
    client = SubmitServiceClient(endpoint="http://submit.example")
    client.list_submissions(limit=7, active_only=True)
    assert captured["params"]["limit"] == "7"
    assert captured["params"]["active_only"] == "true"


def test_submit_client_stream_logs(monkeypatch) -> None:
    captured = {}

    def fake_stream(method, url, params=None, headers=None, timeout=None):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return DummyStreamResp(lines=["line-1", "line-2"])

    monkeypatch.setattr(httpx, "stream", fake_stream)

    client = SubmitServiceClient(
        endpoint="http://submit.example",
        token="token-123",
        user="alice",
    )
    lines = list(
        client.stream_logs(
            "sub-1",
            job="supernodes",
            task="supernode-1",
            stderr=False,
            index=2,
        )
    )
    assert lines == ["line-1", "line-2"]
    assert captured["method"] == "GET"
    assert captured["url"] == "http://submit.example/v1/submissions/sub-1/logs"
    assert captured["params"]["follow"] == "true"
    assert captured["params"]["job"] == "supernodes"
    assert captured["params"]["task"] == "supernode-1"
    assert captured["params"]["stderr"] == "false"
    assert captured["params"]["index"] == "2"
    assert captured["headers"]["Authorization"] == "Bearer token-123"
    assert captured["headers"]["X-Submit-User"] == "alice"
