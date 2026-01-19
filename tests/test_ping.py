from __future__ import annotations

from fedctl.commands import ping as ping_module


def test_run_ping_success(monkeypatch) -> None:
    def fake_load_config():
        return object()

    def fake_get_effective_config(*args, **kwargs):
        return object()

    class FakeClient:
        def __init__(self, cfg):
            pass

        def status_leader(self):
            return "10.0.0.1:4647"

        def close(self):
            pass

    monkeypatch.setattr(ping_module, "load_config", fake_load_config)
    monkeypatch.setattr(ping_module, "get_effective_config", fake_get_effective_config)
    monkeypatch.setattr(ping_module, "NomadClient", FakeClient)

    assert ping_module.run_ping() == 0
