from __future__ import annotations

from pathlib import Path

from fedctl.build.tagging import default_image_tag


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_default_image_tag_uses_deterministic_context_hash(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write(project_root / "pyproject.toml", '[project]\nname = "demo"\nversion = "0.1.0"\n')
    _write(project_root / "src" / "demo.py", 'print("hello")\n')

    tag_one = default_image_tag(
        "demo-project",
        context_root=project_root,
        dockerfile_contents="FROM scratch\nCOPY . .\n",
        flwr_version="1.27.0",
        registry="128.232.61.111:5000",
    )
    tag_two = default_image_tag(
        "demo-project",
        context_root=project_root,
        dockerfile_contents="FROM scratch\nCOPY . .\n",
        flwr_version="1.27.0",
        registry="128.232.61.111:5000",
    )

    assert tag_one == tag_two
    assert tag_one.startswith("128.232.61.111:5000/demo-project-superexec:ctx-")


def test_default_image_tag_changes_when_context_changes(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write(project_root / "pyproject.toml", '[project]\nname = "demo"\nversion = "0.1.0"\n')
    _write(project_root / "src" / "demo.py", 'print("hello")\n')

    before = default_image_tag(
        "demo-project",
        context_root=project_root,
        dockerfile_contents="FROM scratch\nCOPY . .\n",
        flwr_version="1.27.0",
    )

    _write(project_root / "src" / "demo.py", 'print("hello world")\n')

    after = default_image_tag(
        "demo-project",
        context_root=project_root,
        dockerfile_contents="FROM scratch\nCOPY . .\n",
        flwr_version="1.27.0",
    )

    assert before != after


def test_default_image_tag_ignores_non_package_files(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write(project_root / "pyproject.toml", '[project]\nname = "demo"\nversion = "0.1.0"\n')
    _write(project_root / "src" / "demo.py", 'print("hello")\n')
    _write(project_root / "run.toml", 'method = "heterofl"\n')

    before = default_image_tag(
        "demo-project",
        context_root=project_root,
        dockerfile_contents="FROM scratch\nCOPY . .\n",
        flwr_version="1.27.0",
    )

    _write(project_root / "run.toml", 'method = "fedrolex"\n')

    after = default_image_tag(
        "demo-project",
        context_root=project_root,
        dockerfile_contents="FROM scratch\nCOPY . .\n",
        flwr_version="1.27.0",
    )

    assert before == after


def test_default_image_tag_changes_when_pyproject_changes(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write(project_root / "pyproject.toml", '[project]\nname = "demo"\nversion = "0.1.0"\n')
    _write(project_root / "src" / "demo.py", 'print("hello")\n')

    before = default_image_tag(
        "demo-project",
        context_root=project_root,
        dockerfile_contents="FROM scratch\nCOPY . .\n",
        flwr_version="1.27.0",
    )

    _write(project_root / "pyproject.toml", '[project]\nname = "demo"\nversion = "0.2.0"\n')

    after = default_image_tag(
        "demo-project",
        context_root=project_root,
        dockerfile_contents="FROM scratch\nCOPY . .\n",
        flwr_version="1.27.0",
    )

    assert before != after


def test_default_image_tag_changes_when_dockerfile_changes(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write(project_root / "pyproject.toml", '[project]\nname = "demo"\nversion = "0.1.0"\n')

    before = default_image_tag(
        "demo-project",
        context_root=project_root,
        dockerfile_contents="FROM scratch\nCOPY . .\n",
        flwr_version="1.27.0",
    )
    after = default_image_tag(
        "demo-project",
        context_root=project_root,
        dockerfile_contents="FROM busybox\nCOPY . .\n",
        flwr_version="1.27.0",
    )

    assert before != after
