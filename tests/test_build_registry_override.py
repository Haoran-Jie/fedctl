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
        "resolve_deploy_config",
        lambda **_: SimpleNamespace(
            data={"deploy": {"image_registry": "192.168.8.101:5000"}},
            path=None,
        ),
    )
    monkeypatch.setattr(
        build_cmd,
        "default_image_tag",
        lambda project_name, repo_root=None, context_root=None, dockerfile_contents=None, flwr_version=None, registry=None: f"{registry}/{project_name}-superexec:testtag",
    )
    monkeypatch.setattr(build_cmd, "render_dockerfile", lambda _: "FROM scratch\n")

    def fake_build_image(**kwargs):
        captured["image"] = kwargs["image"]

    monkeypatch.setattr(build_cmd, "image_exists", lambda image: False)
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


def test_build_and_record_reuses_existing_deterministic_image(
    monkeypatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    image_tag = "128.232.61.111:5000/demo-project-superexec:ctx-existing"
    captured: dict[str, object] = {}

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
        "resolve_deploy_config",
        lambda **_: SimpleNamespace(data={"deploy": {}}, path=None),
    )
    monkeypatch.setattr(build_cmd, "render_dockerfile", lambda _: "FROM scratch\n")
    monkeypatch.setattr(build_cmd, "default_image_tag", lambda *_, **__: image_tag)
    monkeypatch.setattr(build_cmd, "image_exists", lambda image: image == image_tag)

    def fail_build_image(**kwargs):
        raise AssertionError("existing deterministic image should be reused")

    monkeypatch.setattr(build_cmd, "build_image", fail_build_image)
    monkeypatch.setattr(build_cmd, "push_image", lambda image: captured.setdefault("pushed", image))
    monkeypatch.setattr(
        build_cmd,
        "write_latest_build",
        lambda metadata: captured.setdefault("latest", metadata.image),
    )
    monkeypatch.setattr(
        build_cmd,
        "write_project_build",
        lambda metadata, root: captured.setdefault("project", (metadata.image, root)),
    )

    image = build_cmd.build_and_record(
        path=str(project_root),
        flwr_version="1.27.0",
        push=True,
    )

    assert image == image_tag
    assert captured["pushed"] == image_tag
    assert captured["latest"] == image_tag
    assert captured["project"] == (image_tag, project_root)


def test_build_and_record_no_cache_rebuilds_existing_deterministic_image(
    monkeypatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    image_tag = "128.232.61.111:5000/demo-project-superexec:ctx-existing"
    captured: dict[str, object] = {}

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
        "resolve_deploy_config",
        lambda **_: SimpleNamespace(data={"deploy": {}}, path=None),
    )
    monkeypatch.setattr(build_cmd, "render_dockerfile", lambda _: "FROM scratch\n")
    monkeypatch.setattr(build_cmd, "default_image_tag", lambda *_, **__: image_tag)
    monkeypatch.setattr(build_cmd, "image_exists", lambda image: True)
    monkeypatch.setattr(
        build_cmd,
        "build_image",
        lambda **kwargs: captured.setdefault("build_kwargs", kwargs),
    )
    monkeypatch.setattr(build_cmd, "write_latest_build", lambda metadata: None)
    monkeypatch.setattr(build_cmd, "write_project_build", lambda metadata, root: None)

    image = build_cmd.build_and_record(
        path=str(project_root),
        flwr_version="1.27.0",
        no_cache=True,
    )

    assert image == image_tag
    assert captured["build_kwargs"]["image"] == image_tag
    assert captured["build_kwargs"]["no_cache"] is True
