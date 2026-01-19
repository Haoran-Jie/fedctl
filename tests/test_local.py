from __future__ import annotations

import json

from fedctl.commands import local as local_module


def test_local_status_reads_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    state_path = local_module._state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "started_at": "now",
                "agents": [{"role": "server", "pid": 123, "log": "x.log"}],
            }
        )
    )

    monkeypatch.setattr(local_module, "_is_pid_alive", lambda pid: False)
    assert local_module.run_local_status() == 0


def test_local_up_writes_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setattr(local_module.shutil, "which", lambda _: "/usr/bin/nomad")

    class FakePopen:
        _pid = 1000

        def __init__(self, *args, **kwargs):
            FakePopen._pid += 1
            self.pid = FakePopen._pid

    monkeypatch.setattr(local_module.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(local_module, "_wait_for_ready", lambda *args, **kwargs: ("leader", 2))

    result = local_module.run_local_up(
        server_config="server.hcl",
        client_configs=["client1.hcl"],
        wait_seconds=1,
    )
    assert result == 0
    assert local_module._state_path().exists()
