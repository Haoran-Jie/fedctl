from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fedctl.commands import run as run_module
from fedctl.commands.run import _resolve_run_repo_config


def test_resolve_run_repo_config_prefers_explicit_value(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()
    explicit = str(tmp_path / "external-fedctl.yaml")

    resolved = _resolve_run_repo_config(
        repo_config=explicit,
        project_root=project_root,
    )

    assert resolved == explicit


def test_resolve_run_repo_config_uses_project_local_config(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    local_cfg = project_root / ".fedctl" / "fedctl.yaml"
    local_cfg.parent.mkdir(parents=True)
    local_cfg.write_text("deploy: {}\n", encoding="utf-8")

    resolved = _resolve_run_repo_config(
        repo_config=None,
        project_root=project_root,
    )

    assert resolved == str(local_cfg)


def test_resolve_run_repo_config_returns_none_when_not_found(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()

    resolved = _resolve_run_repo_config(
        repo_config=None,
        project_root=project_root,
    )

    assert resolved is None


def test_run_run_waits_for_remote_completion_when_no_stream(monkeypatch, tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    calls: dict[str, object] = {}

    monkeypatch.setattr(
        run_module,
        "inspect_flwr_project",
        lambda path: SimpleNamespace(
            root=project_root,
            project_name="demo",
            local_sim_num_supernodes=None,
        ),
    )
    monkeypatch.setattr(run_module, "build_and_record", lambda **kwargs: "example:latest")
    monkeypatch.setattr(run_module, "run_deploy", lambda **kwargs: 0)
    monkeypatch.setattr(run_module, "run_configure", lambda **kwargs: 0)
    monkeypatch.setattr(run_module, "resolve_flwr_home", lambda project_root: project_root / ".flwr")
    monkeypatch.setattr(run_module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(run_module, "run_destroy", lambda **kwargs: 0)

    def fake_wait(**kwargs):
        calls["experiment"] = kwargs["experiment"]
        return 0

    monkeypatch.setattr(run_module, "_wait_for_remote_run_completion", fake_wait)

    status = run_module.run_run(
        path=str(project_root),
        federation="remote-deployment",
        stream=False,
        destroy=False,
        endpoint="http://nomad.example:4646",
        namespace="default",
        token="token",
    )

    assert status == 0
    assert str(calls["experiment"]).startswith("demo-")


def test_run_run_skips_remote_wait_when_streaming(monkeypatch, tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    monkeypatch.setattr(
        run_module,
        "inspect_flwr_project",
        lambda path: SimpleNamespace(
            root=project_root,
            project_name="demo",
            local_sim_num_supernodes=None,
        ),
    )
    monkeypatch.setattr(run_module, "build_and_record", lambda **kwargs: "example:latest")
    monkeypatch.setattr(run_module, "run_deploy", lambda **kwargs: 0)
    monkeypatch.setattr(run_module, "run_configure", lambda **kwargs: 0)
    monkeypatch.setattr(run_module, "resolve_flwr_home", lambda project_root: project_root / ".flwr")
    monkeypatch.setattr(run_module.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(run_module, "run_destroy", lambda **kwargs: 0)

    def fail_wait(**kwargs):
        raise AssertionError("wait helper should not be called when streaming")

    monkeypatch.setattr(run_module, "_wait_for_remote_run_completion", fail_wait)

    status = run_module.run_run(
        path=str(project_root),
        federation="remote-deployment",
        stream=True,
        destroy=False,
        endpoint="http://nomad.example:4646",
        namespace="default",
        token="token",
    )

    assert status == 0


def test_latest_serverapp_alloc_selects_latest_allocation() -> None:
    class FakeClient:
        def job_allocations(self, job_name: str):
            assert job_name == "demo-serverapp"
            return [
                {"ID": "older", "ModifyTime": 10},
                {"ID": "newer", "ModifyTime": 20},
            ]

    alloc = run_module._latest_serverapp_alloc(FakeClient(), "demo-serverapp")

    assert alloc == {"ID": "newer", "ModifyTime": 20}
