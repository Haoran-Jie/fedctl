from __future__ import annotations

import json

from fedctl.commands import discover as discover_module


class DummyConsole:
    def __init__(self):
        self.last_json = None

    def print_json(self, data):
        self.last_json = data

    def print(self, *args, **kwargs):
        pass


def test_discover_json_output(monkeypatch) -> None:
    dummy_console = DummyConsole()

    def fake_load_config():
        return object()

    def fake_get_effective_config(*args, **kwargs):
        return object()

    class FakeClient:
        def __init__(self, cfg):
            pass

        def nodes(self):
            return [{"Name": "node1"}]

        def close(self):
            pass

    monkeypatch.setattr(discover_module, "console", dummy_console)
    monkeypatch.setattr(discover_module, "load_config", fake_load_config)
    monkeypatch.setattr(discover_module, "get_effective_config", fake_get_effective_config)
    monkeypatch.setattr(discover_module, "NomadClient", FakeClient)

    assert discover_module.run_discover(json_output=True) == 0
    assert json.loads(dummy_console.last_json) == [{"Name": "node1"}]
