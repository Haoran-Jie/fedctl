from __future__ import annotations

import json

from fedctl.config.schema import EffectiveConfig
from fedctl.nomad.client import NomadClient


class DummyResp:
    def __init__(self, status_code=200, text='"127.0.0.1:4647"', json_obj=None, headers=None):
        self.status_code = status_code
        self.text = text
        self._json = json_obj
        self.headers = headers or {"content-type": "application/json"}

    def json(self):
        return self._json


def test_nomad_client_sets_headers_and_base_url() -> None:
    cfg = EffectiveConfig(
        profile_name="p",
        endpoint="http://127.0.0.1:4646",
        namespace="ns",
        nomad_token="tok",
    )

    client = NomadClient(cfg)
    assert str(client._client.base_url) == "http://127.0.0.1:4646"
    assert client._client.headers["X-Nomad-Token"] == "tok"
    assert client._client.headers["X-Nomad-Namespace"] == "ns"
    client.close()


def test_status_leader_parses_string(monkeypatch) -> None:
    cfg = EffectiveConfig(
        profile_name="p",
        endpoint="http://127.0.0.1:4646",
        namespace=None,
        nomad_token=None,
    )
    client = NomadClient(cfg)

    def fake_get(path: str):
        return DummyResp(status_code=200, text='"10.0.0.1:4647"', headers={"content-type": "text/plain"})

    monkeypatch.setattr(
        client._client,
        "request",
        lambda method, path, json=None, params=None: fake_get(path),
    )
    assert client.status_leader() == "10.0.0.1:4647"
    client.close()


def test_alloc_logs_follow_flag(monkeypatch) -> None:
    cfg = EffectiveConfig(
        profile_name="p",
        endpoint="http://127.0.0.1:4646",
        namespace=None,
        nomad_token=None,
    )
    client = NomadClient(cfg)
    captured = {}

    def fake_request(method, path, json=None, params=None):
        captured["params"] = params
        return DummyResp(status_code=200, text="", json_obj={"Data": ""})

    monkeypatch.setattr(client._client, "request", fake_request)
    client.alloc_logs("alloc", "task", stderr=False, follow=True)
    assert captured["params"]["follow"] == "true"
    assert captured["params"]["type"] == "stdout"
    client.close()


def test_alloc_logs_handles_concatenated_json_text_response(monkeypatch) -> None:
    cfg = EffectiveConfig(
        profile_name="p",
        endpoint="http://127.0.0.1:4646",
        namespace=None,
        nomad_token=None,
    )
    client = NomadClient(cfg)
    first = {"Data": "aGVsbG8g"}
    second = {"Data": "d29ybGQK"}

    class BrokenJSONResp(DummyResp):
        def __init__(self):
            super().__init__(status_code=200, text=json.dumps(first) + json.dumps(second))
            self.headers = {"content-type": "application/json"}

        def json(self):
            raise ValueError("Extra data: line 1 column 10 (char 9)")

    monkeypatch.setattr(client._client, "request", lambda method, path, json=None, params=None: BrokenJSONResp())

    decoded = client.alloc_logs("alloc", "task", stderr=True, follow=False)

    assert decoded == "hello world\n"
    client.close()
