from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import fedctl.commands.build as build_cmd


def test_build_and_record_prefers_env_registry_override(
    monkeypatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setenv("FEDCTL_IMAGE_REGISTRY", "128.232.61.111:5000")
    monkeypatch.setattr(
        build_cmd,
        "inspect_project",
        lambda _: SimpleNamespace(
            root=project_root,
            project_name="demo-project",
        ),
    )
    monkeypatch.setattr(
        build_cmd,
        "resolve_repo_config",
        lambda **_: SimpleNamespace(
            data={"image_registry": "100.82.158.122:5000"},
            path=None,
        ),
    )
    monkeypatch.setattr(
        build_cmd,
        "default_image_tag",
        lambda project_name, repo_root=None, registry=None: f"{registry}/{project_name}-superexec:testtag",
    )
    monkeypatch.setattr(build_cmd, "render_dockerfile", lambda _: "FROM scratch\n")

    def fake_build_image(**kwargs):
        captured["image"] = kwargs["image"]

    monkeypatch.setattr(build_cmd, "build_image", fake_build_image)
    monkeypatch.setattr(build_cmd, "write_latest_build", lambda metadata: None)
    monkeypatch.setattr(build_cmd, "write_project_build", lambda metadata, root: None)

    image = build_cmd.build_and_record(
        path=str(project_root),
        flwr_version="1.27.0",
        push=False,
    )

    assert image == "128.232.61.111:5000/demo-project-superexec:testtag"
    assert captured["image"] == "128.232.61.111:5000/demo-project-superexec:testtag"
