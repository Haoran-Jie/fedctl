from __future__ import annotations

import tarfile
from pathlib import Path
import tomllib

from fedctl.commands.run import _build_run_config_overrides
from fedctl.commands.submit import _build_project_archive, _runner_args
from fedctl.project.run_config import (
    extract_seed_sweep,
    materialize_run_config,
    resolve_run_config,
)


def test_resolve_run_config_prefers_project_relative_path(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    config_dir = project_root / "run_configs"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "run.toml"
    config_path.write_text('method = "heterofl"\n', encoding="utf-8")

    resolved = resolve_run_config(project_root, "run_configs/run.toml")

    assert resolved is not None
    assert resolved.resolved_path == config_path.resolve()
    assert resolved.runner_path == "run_configs/run.toml"
    assert resolved.archive_source is None


def test_resolve_run_config_archives_external_file(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    external = tmp_path / "external.toml"
    external.write_text('method = "heterofl"\n', encoding="utf-8")

    resolved = resolve_run_config(project_root, str(external))

    assert resolved is not None
    assert resolved.resolved_path == external.resolve()
    assert resolved.runner_path == ".fedctl/run_config.toml"
    assert resolved.archive_source == external.resolve()


def test_resolve_run_config_normalizes_nested_project_relative_file(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    config_dir = project_root / "run_configs"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "run.toml"
    config_path.write_text(
        "\n".join(
            [
                "[run]",
                'method = "heterofl"',
                'task = "fashion_mnist_cnn"',
                "seed = 1337",
                "seeds = [1337, 1338, 1339]",
                "",
                "[server]",
                "num-server-rounds = 3",
                'fraction-train = 1.0',
                "",
                "[client]",
                'optimizer = "adam"',
                "",
                "[capacity]",
                'heterofl-partition-rates = "0:1.0,1:0.5"',
                'heterofl-device-type-allocations = "rpi4:0.125@5,0.25@5;rpi5:0.5@5,1.0@5"',
                "",
                "[data]",
                'partitioning-continuous-column = "Appliances"',
                "partitioning-continuous-strictness = 0.5",
                "",
                "[devices.rpi4]",
                "batch-size = 8",
                "model-rate = 0.25",
                "",
                "[fedavgm]",
                "server-momentum = 0.9",
                "",
                "[fedbuff]",
                "buffer-size = 10",
                "train-concurrency = 4",
                "server-learning-rate = 0.5",
                "",
                "[fedcover]",
                "buffer-size = 5",
                "train-concurrency = 4",
                "server-learning-rate = 0.5",
                "coverage-power = 0.5",
                "max-block-weight = 2.0",
                "min-observed-mass = 0.15",
                "",
                "[fiarse]",
                'threshold-mode = "layerwise"',
                "global-learning-rate = 0.75",
                "",
                "[evaluation]",
                "client-eval-enabled = false",
                "final-client-eval-enabled = true",
                "target-score = 0.60",
                "stop-on-target-score = true",
                "",
                "[wandb]",
                "enabled = true",
                'tags = ["realistic", "heterofl"]',
            ]
        ),
        encoding="utf-8",
    )

    resolved = resolve_run_config(project_root, "run_configs/run.toml")

    assert resolved is not None
    assert resolved.resolved_path != config_path.resolve()
    assert resolved.runner_path == "run_configs/run.toml"
    assert resolved.archive_source == resolved.resolved_path

    normalized = tomllib.loads(resolved.resolved_path.read_text(encoding="utf-8"))
    assert normalized["method"] == "heterofl"
    assert normalized["task"] == "fashion_mnist_cnn"
    assert normalized["seed"] == 1337
    assert normalized["num-server-rounds"] == 3
    assert normalized["optimizer"] == "adam"
    assert normalized["heterofl-partition-rates"] == "0:1.0,1:0.5"
    assert (
        normalized["heterofl-device-type-allocations"]
        == "rpi4:0.125@5,0.25@5;rpi5:0.5@5,1.0@5"
    )
    assert normalized["partitioning-continuous-column"] == "Appliances"
    assert normalized["partitioning-continuous-strictness"] == 0.5
    assert normalized["target-score"] == 0.60
    assert normalized["stop-on-target-score"] is True
    assert normalized["rpi4-batch-size"] == 8
    assert normalized["rpi4-model-rate"] == 0.25
    assert normalized["fedavgm-server-momentum"] == 0.9
    assert normalized["fedbuff-buffer-size"] == 10
    assert normalized["fedbuff-train-concurrency"] == 4
    assert normalized["fedbuff-server-learning-rate"] == 0.5
    assert normalized["fedcover-buffer-size"] == 5
    assert normalized["fedcover-train-concurrency"] == 4
    assert normalized["fedcover-server-learning-rate"] == 0.5
    assert normalized["fedcover-coverage-power"] == 0.5
    assert normalized["fedcover-max-block-weight"] == 2.0
    assert normalized["fedcover-min-observed-mass"] == 0.15
    assert normalized["fiarse-threshold-mode"] == "layerwise"
    assert normalized["fiarse-global-learning-rate"] == 0.75
    assert normalized["client-eval-enabled"] is False
    assert normalized["final-client-eval-enabled"] is True
    assert normalized["wandb-enabled"] is True
    assert normalized["wandb-tags"] == "realistic,heterofl"
    assert "seeds" not in normalized


def test_extract_seed_sweep_reads_nested_run_seeds(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    config_path = project_root / "run.toml"
    config_path.write_text(
        "\n".join(
            [
                "[run]",
                'method = "heterofl"',
                "seeds = [1337, 1338, 1339]",
            ]
        ),
        encoding="utf-8",
    )

    seeds = extract_seed_sweep(project_root, "run.toml")

    assert seeds == (1337, 1338, 1339)


def test_build_project_archive_includes_external_run_config(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    external = tmp_path / "external.toml"
    external.write_text('method = "heterofl"\n', encoding="utf-8")

    archive = _build_project_archive(
        project_root,
        "demo",
        run_config_path=external,
        run_config_arcname=".fedctl/run_config.toml",
    )

    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()

    assert "project/pyproject.toml" in names
    assert "project/.fedctl/run_config.toml" in names


def test_build_project_archive_can_include_normalized_project_relative_config(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    config_dir = project_root / "run_configs"
    config_dir.mkdir(parents=True)
    (project_root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    config_path = config_dir / "run.toml"
    config_path.write_text(
        "\n".join(
            [
                "[run]",
                'method = "fedavg"',
                "",
                "[devices.rpi5]",
                "batch-size = 32",
            ]
        ),
        encoding="utf-8",
    )

    resolved = resolve_run_config(project_root, "run_configs/run.toml")
    assert resolved is not None

    archive = _build_project_archive(
        project_root,
        "demo",
        run_config_path=resolved.archive_source,
        run_config_arcname=resolved.runner_path,
    )

    with tarfile.open(archive, "r:gz") as tar:
        member = tar.extractfile("project/run_configs/run.toml")
        assert member is not None
        normalized = tomllib.loads(member.read().decode("utf-8"))

    assert normalized["method"] == "fedavg"
    assert normalized["rpi5-batch-size"] == 32


def test_runner_args_include_run_config_when_present() -> None:
    args = _runner_args(
        project_dir_name="fedctl_research",
        exp_name="demo-exp",
        run_config=".fedctl/run_config.toml",
        run_config_overrides=None,
        seed=None,
        flwr_version="1.27.0",
        image=None,
        no_cache=False,
        platform=None,
        context=None,
        push=False,
        num_supernodes=4,
        auto_supernodes=True,
        supernodes=None,
        net=None,
        allow_oversubscribe=None,
        federation="remote-deployment",
        stream=True,
        timeout_seconds=120,
        destroy=True,
    )

    assert "--run-config" in args
    idx = args.index("--run-config")
    assert args[idx + 1] == ".fedctl/run_config.toml"


def test_runner_args_include_seed_and_run_config_overrides() -> None:
    args = _runner_args(
        project_dir_name="fedctl_research",
        exp_name="demo-exp",
        run_config=None,
        run_config_overrides=["learning-rate=0.02", "wandb.group=test-group"],
        seed=1441,
        flwr_version="1.27.0",
        image=None,
        no_cache=False,
        platform=None,
        context=None,
        push=False,
        num_supernodes=4,
        auto_supernodes=True,
        supernodes=None,
        net=None,
        allow_oversubscribe=None,
        federation="remote-deployment",
        stream=True,
        timeout_seconds=120,
        destroy=True,
    )

    assert args.count("--run-config-override") == 2
    assert "--seed" in args
    assert args[args.index("--seed") + 1] == "1441"


def test_build_run_config_overrides_appends_seed_last() -> None:
    overrides = _build_run_config_overrides(
        run_config_overrides=["learning-rate=0.02"],
        seed=2026,
    )

    assert overrides == ["learning-rate=0.02", "seed=2026"]


def test_materialize_run_config_merges_overrides_into_single_toml(tmp_path: Path) -> None:
    base = tmp_path / "run.toml"
    base.write_text(
        "\n".join(
            [
                'method = "fedavg"',
                "num-server-rounds = 2",
            ]
        ),
        encoding="utf-8",
    )

    merged = materialize_run_config(
        base_path=base,
        run_config_overrides=["learning-rate=0.02", "seed=2026", "wandb.group=test-group"],
    )

    assert merged is not None
    assert merged != base
    data = tomllib.loads(merged.read_text(encoding="utf-8"))
    assert data["method"] == "fedavg"
    assert data["num-server-rounds"] == 2
    assert data["learning-rate"] == 0.02
    assert data["seed"] == 2026
    assert data["wandb.group"] == "test-group"
