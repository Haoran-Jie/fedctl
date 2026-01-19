from __future__ import annotations

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
        tls_ca=None,
        tls_skip_verify=False,
        access_mode="lan-only",
        tailscale_subnet_cidr=None,
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
        tls_ca=None,
        tls_skip_verify=False,
        access_mode="lan-only",
        tailscale_subnet_cidr=None,
        nomad_token=None,
    )
    client = NomadClient(cfg)

    def fake_get(path: str):
        return DummyResp(status_code=200, text='"10.0.0.1:4647"', headers={"content-type": "text/plain"})

    monkeypatch.setattr(
        client._client,
        "request",
        lambda method, path, json=None: fake_get(path),
    )
    assert client.status_leader() == "10.0.0.1:4647"
    client.close()
