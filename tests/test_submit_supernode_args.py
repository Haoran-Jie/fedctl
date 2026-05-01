from __future__ import annotations

from pathlib import Path

from fedctl.commands.submit import _submit_command_preview


def test_submit_runner_uses_typed_supernode_guard() -> None:
    source = Path("src/fedctl/commands/submit.py").read_text(encoding="utf-8")
    assert "use_typed_supernodes = bool(supernodes)" in source
    assert 'if not use_typed_supernodes:' in source
    assert 'args.extend(["--num-supernodes", str(num_supernodes)])' in source


def test_submit_command_preview_uses_typed_supernode_guard() -> None:
    source = Path("src/fedctl/commands/submit.py").read_text(encoding="utf-8")
    assert 'options["num_supernodes"] = num_supernodes' in source
    assert 'if not use_typed_supernodes:' in source
    assert 'parts.extend(["--num-supernodes", str(options["num_supernodes"])])' in source


def test_submit_command_preview_uses_deploy_config_spelling() -> None:
    preview = _submit_command_preview(
        {
            "path": "apps/fedctl_research",
            "deploy_config": "cluster.yaml",
        }
    )

    assert "--deploy-config cluster.yaml" in preview
    assert "--repo-config" not in preview


def test_run_command_clears_untyped_count_for_typed_supernodes() -> None:
    source = Path("src/fedctl/commands/run.py").read_text(encoding="utf-8")
    assert "deploy_num_supernodes = None if supernodes else num_supernodes" in source
    assert "num_supernodes=deploy_num_supernodes" in source
