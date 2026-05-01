from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import yaml

import fedctl.commands.submit as submit_cmd
import fedctl.submit.artifact as artifact
from fedctl.config.io import DEFAULT_SUBMIT_ENDPOINT
from fedctl.project.experiment_config import resolve_experiment_config


def test_upload_artifact_uses_explicit_presign_service(
    monkeypatch, tmp_path: Path
) -> None:
    archive = tmp_path / "project.tar.gz"
    archive.write_bytes(b"artifact-bytes")
    captured: dict[str, object] = {}

    def fake_upload_via_presign_service(
        archive_path: Path,
        presign_endpoint: str,
        *,
        bucket: str,
        key: str,
        token: str | None = None,
    ) -> str:
        captured["archive_path"] = archive_path
        captured["presign_endpoint"] = presign_endpoint
        captured["bucket"] = bucket
        captured["key"] = key
        captured["token"] = token
        return "https://signed.example/get-object"

    monkeypatch.setattr(
        artifact,
        "_upload_via_presign_service",
        fake_upload_via_presign_service,
    )

    url = artifact.upload_artifact(
        archive,
        "s3+presign://fedctl-submits/fedctl-submits",
        presign_endpoint="http://submit.example:8080/v1/presign",
        presign_token="token-123",
    )

    assert url == "https://signed.example/get-object"
    assert captured == {
        "archive_path": archive,
        "presign_endpoint": "http://submit.example:8080/v1/presign",
        "bucket": "fedctl-submits",
        "key": "fedctl-submits/project.tar.gz",
        "token": "token-123",
    }


def test_fetch_presign_url_omits_expires_when_ttl_unset(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, str]:
            return {"url": "https://signed.example/object"}

    def fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(artifact.httpx, "post", fake_post)

    url = artifact._fetch_presign_url(
        "http://submit.example:8080/v1/presign",
        headers={"Authorization": "Bearer token"},
        bucket="fedctl-submits",
        key="fedctl-submits/project.tar.gz",
        method="GET",
        expires=None,
    )

    assert url == "https://signed.example/object"
    assert captured["json"] == {
        "bucket": "fedctl-submits",
        "key": "fedctl-submits/project.tar.gz",
        "method": "GET",
    }


def test_run_submit_passes_submit_service_context_to_artifact_upload(
    monkeypatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    archive = tmp_path / "project.tar.gz"
    archive.write_bytes(b"artifact-bytes")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        submit_cmd,
        "inspect_flwr_project",
        lambda _: SimpleNamespace(
            project_name="demo-project",
            local_sim_num_supernodes=None,
            root=project_root,
        ),
    )
    monkeypatch.setattr(
        submit_cmd,
        "resolve_deploy_config",
        lambda **_: SimpleNamespace(
            data={
                "submit": {
                    "image": "submit-image:latest",
                    "artifact_store": "s3+presign://fedctl-submits/fedctl-submits",
                    "endpoint": "http://submit.example:8080",
                    "token": "token-from-config",
                }
            },
            path=None,
        ),
    )

    class FakeSubmitClient:
        endpoint = "http://submit.example:8080"
        token = "token-from-client"

        def create_submission(self, payload):
            captured["submission_payload"] = payload
            return {"submission_id": "sub-123"}

    monkeypatch.setattr(
        submit_cmd,
        "_submit_service_client",
        lambda **_: FakeSubmitClient(),
    )
    monkeypatch.setattr(
        submit_cmd,
        "_build_project_archive",
        lambda *_, **__: archive,
    )

    def fake_upload_artifact(archive_path, artifact_store, **kwargs):
        captured["archive_path"] = archive_path
        captured["artifact_store"] = artifact_store
        captured["upload_kwargs"] = kwargs
        return "https://signed.example/get-object"

    monkeypatch.setattr(submit_cmd, "upload_artifact", fake_upload_artifact)
    monkeypatch.setattr(submit_cmd, "load_config", lambda: object())
    monkeypatch.setattr(
        submit_cmd,
        "get_effective_config",
        lambda _: SimpleNamespace(namespace="default"),
    )

    status = submit_cmd.run_submit(
        path=str(project_root),
        flwr_version="1.25.0",
        image="superexec-image:latest",
        no_cache=False,
        platform=None,
        context=None,
        push=False,
        num_supernodes=3,
        auto_supernodes=True,
        supernodes=None,
        net=None,
        allow_oversubscribe=None,
        deploy_config=None,
        experiment="demo-exp",
        timeout_seconds=120,
        federation="remote-deployment",
        stream=True,
        destroy=True,
        submit_image=None,
        artifact_store=None,
        priority=50,
    )

    assert status == 0
    assert captured["archive_path"] == archive
    assert captured["artifact_store"] == "s3+presign://fedctl-submits/fedctl-submits"
    assert captured["upload_kwargs"] == {
        "presign_endpoint": "http://submit.example:8080/v1/presign",
        "presign_token": "token-from-client",
    }
    submit_request = captured["submission_payload"]["submit_request"]
    assert submit_request["path_input"] == str(project_root)
    assert submit_request["project_root"] == str(project_root.resolve())
    assert "fedctl submit run" in submit_request["command_preview"]
    assert submit_request["options"]["experiment"] == "demo-exp"


def test_run_submit_requires_token_for_default_submit_service(
    monkeypatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    deploy_cfg_path = tmp_path / "deploy-default.yaml"

    monkeypatch.setattr(
        submit_cmd,
        "inspect_flwr_project",
        lambda _: SimpleNamespace(
            project_name="demo-project",
            local_sim_num_supernodes=None,
            root=project_root,
        ),
    )
    monkeypatch.setattr(
        submit_cmd,
        "resolve_deploy_config",
        lambda **_: SimpleNamespace(
            data={
                "submit": {
                    "image": "submit-image:latest",
                    "artifact_store": "s3+presign://fedctl-submits/fedctl-submits",
                    "endpoint": DEFAULT_SUBMIT_ENDPOINT,
                    "token": "",
                }
            },
            path=deploy_cfg_path,
        ),
    )
    monkeypatch.setattr(
        submit_cmd,
        "_interactive_stdin",
        lambda: False,
    )

    def fake_check_auth(self):
        raise submit_cmd.SubmitServiceError("Submit service error 401: Missing bearer token")

    monkeypatch.setattr(submit_cmd.SubmitServiceClient, "check_auth", fake_check_auth)
    monkeypatch.setattr(
        submit_cmd,
        "_build_project_archive",
        lambda *_, **__: (_ for _ in ()).throw(AssertionError("should not package")),
    )

    status = submit_cmd.run_submit(
        path=str(project_root),
        flwr_version="1.25.0",
        image=None,
        no_cache=False,
        platform=None,
        context=None,
        push=False,
        num_supernodes=2,
        auto_supernodes=True,
        supernodes=None,
        net=None,
        allow_oversubscribe=None,
        deploy_config=None,
        experiment="demo-exp",
        timeout_seconds=120,
        federation="remote-deployment",
        stream=True,
        destroy=True,
        submit_image=None,
        artifact_store=None,
        priority=50,
    )

    assert status == 1


def test_submit_service_client_prompts_and_saves_missing_token(
    monkeypatch, tmp_path: Path
) -> None:
    config_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    deploy_cfg_path = config_home / "fedctl" / "deploy-default.yaml"
    deploy_cfg_path.parent.mkdir(parents=True)
    deploy_cfg_path.write_text(
        "submit:\n  endpoint: http://submit.example\n  token: ''\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(submit_cmd, "_interactive_stdin", lambda: True)
    monkeypatch.setattr(submit_cmd.getpass, "getpass", lambda _: "prompt-token")

    checked_tokens: list[str | None] = []

    def fake_check_auth(self):
        checked_tokens.append(self.token)
        if self.token != "prompt-token":
            raise submit_cmd.SubmitServiceError("Submit service error 401: Missing bearer token")

    monkeypatch.setattr(submit_cmd.SubmitServiceClient, "check_auth", fake_check_auth)

    client = submit_cmd._submit_service_client(
        deploy_cfg={"submit": {"endpoint": "http://submit.example", "token": ""}},
        deploy_cfg_path=deploy_cfg_path,
        prompt_for_token=True,
        validate_auth=True,
    )

    assert isinstance(client, submit_cmd.SubmitServiceClient)
    assert client.token == "prompt-token"
    assert checked_tokens == [None, "prompt-token"]
    assert yaml.safe_load(deploy_cfg_path.read_text())["submit"]["token"] == "prompt-token"


def test_submit_service_client_prompts_and_replaces_invalid_token(
    monkeypatch, tmp_path: Path
) -> None:
    config_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    deploy_cfg_path = config_home / "fedctl" / "deploy-default.yaml"
    deploy_cfg_path.parent.mkdir(parents=True)
    deploy_cfg_path.write_text(
        "submit:\n  endpoint: http://submit.example\n  token: bad-token\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(submit_cmd, "_interactive_stdin", lambda: True)
    monkeypatch.setattr(submit_cmd.getpass, "getpass", lambda _: "good-token")

    checked_tokens: list[str | None] = []

    def fake_check_auth(self):
        checked_tokens.append(self.token)
        if self.token != "good-token":
            raise submit_cmd.SubmitServiceError("Submit service error 403: Invalid token")

    monkeypatch.setattr(submit_cmd.SubmitServiceClient, "check_auth", fake_check_auth)

    client = submit_cmd._submit_service_client(
        deploy_cfg={"submit": {"endpoint": "http://submit.example", "token": "bad-token"}},
        deploy_cfg_path=deploy_cfg_path,
        prompt_for_token=True,
        validate_auth=True,
    )

    assert isinstance(client, submit_cmd.SubmitServiceClient)
    assert client.token == "good-token"
    assert checked_tokens == ["bad-token", "good-token"]
    assert yaml.safe_load(deploy_cfg_path.read_text())["submit"]["token"] == "good-token"


def test_prompted_submit_token_is_not_written_to_repo_deploy_config(
    monkeypatch, tmp_path: Path
) -> None:
    config_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    repo_deploy_cfg_path = tmp_path / "project" / ".fedctl" / "fedctl.yaml"
    repo_deploy_cfg_path.parent.mkdir(parents=True)
    repo_deploy_cfg_path.write_text(
        "submit:\n  endpoint: http://submit.example\n  token: ''\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(submit_cmd, "_interactive_stdin", lambda: True)
    monkeypatch.setattr(submit_cmd.getpass, "getpass", lambda _: "prompt-token")

    def fake_check_auth(self):
        if self.token != "prompt-token":
            raise submit_cmd.SubmitServiceError("Submit service error 401: Missing bearer token")

    monkeypatch.setattr(submit_cmd.SubmitServiceClient, "check_auth", fake_check_auth)

    client = submit_cmd._submit_service_client(
        deploy_cfg={"submit": {"endpoint": "http://submit.example", "token": ""}},
        deploy_cfg_path=repo_deploy_cfg_path,
        prompt_for_token=True,
        validate_auth=True,
    )

    user_deploy_cfg_path = config_home / "fedctl" / "deploy-default.yaml"
    assert isinstance(client, submit_cmd.SubmitServiceClient)
    assert yaml.safe_load(repo_deploy_cfg_path.read_text())["submit"]["token"] == ""
    assert yaml.safe_load(user_deploy_cfg_path.read_text())["submit"]["token"] == "prompt-token"


def test_run_submit_register_token_prompts_and_saves_token(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    saved: dict[str, object] = {}
    registered: dict[str, object] = {}

    class FakeSubmitClient:
        def register_token(self, **kwargs):
            registered.update(kwargs)
            return {"name": kwargs["name"], "role": "user", "token": "fedctl_secret"}

    monkeypatch.setattr(submit_cmd, "_submit_service_client", lambda **_: FakeSubmitClient())
    monkeypatch.setattr(submit_cmd, "_interactive_stdin", lambda: True)
    monkeypatch.setattr(submit_cmd.getpass, "getuser", lambda: "alice")
    monkeypatch.setattr(submit_cmd.getpass, "getpass", lambda _: "cammlsys")

    def fake_store_submit_token(token: str, *, deploy_cfg_path: Path | None) -> Path:
        saved["token"] = token
        saved["deploy_cfg_path"] = deploy_cfg_path
        return tmp_path / "deploy-default.yaml"

    monkeypatch.setattr(submit_cmd, "_store_submit_token", fake_store_submit_token)

    status = submit_cmd.run_submit_register_token(
        name=None,
        registration_code=None,
        token=None,
    )

    output = capsys.readouterr().out
    assert status == 0
    assert registered == {
        "name": "alice",
        "registration_code": "cammlsys",
        "token": None,
    }
    assert saved == {"token": "fedctl_secret", "deploy_cfg_path": None}
    assert "fedctl_secret" not in output


def test_run_submit_auto_generates_experiment_from_experiment_config(
    monkeypatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    experiment_config = project_root / "experiment.toml"
    experiment_config.write_text(
        """
[experiment]
method = "heterofl"
task = "cifar10_cnn"
seed = 1337

[server]
min-available-nodes = 20

[capacity]
model-rate-levels = [1.0, 0.5, 0.25, 0.125]
model-rate-proportions = [0.25, 0.25, 0.25, 0.25]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    archive = tmp_path / "project.tar.gz"
    archive.write_bytes(b"artifact-bytes")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        submit_cmd,
        "inspect_flwr_project",
        lambda _: SimpleNamespace(
            project_name="demo-project",
            local_sim_num_supernodes=None,
            root=project_root,
        ),
    )
    monkeypatch.setattr(
        submit_cmd,
        "resolve_deploy_config",
        lambda **_: SimpleNamespace(
            data={
                "submit": {
                    "image": "submit-image:latest",
                    "artifact_store": "s3+presign://fedctl-submits/fedctl-submits",
                    "endpoint": "http://submit.example:8080",
                    "token": "token-from-config",
                }
            },
            path=None,
        ),
    )

    class FakeSubmitClient:
        endpoint = "http://submit.example:8080"
        token = "token-from-client"

        def create_submission(self, payload):
            captured["submission_payload"] = payload
            return {"submission_id": "sub-123"}

    monkeypatch.setattr(
        submit_cmd,
        "_submit_service_client",
        lambda **_: FakeSubmitClient(),
    )
    monkeypatch.setattr(
        submit_cmd,
        "_build_project_archive",
        lambda *_, **__: archive,
    )
    monkeypatch.setattr(
        submit_cmd,
        "upload_artifact",
        lambda *_, **__: "https://signed.example/get-object",
    )
    monkeypatch.setattr(submit_cmd, "load_config", lambda: object())
    monkeypatch.setattr(
        submit_cmd,
        "get_effective_config",
        lambda _: SimpleNamespace(namespace="default"),
    )

    status = submit_cmd.run_submit(
        path=str(project_root),
        experiment_config="experiment.toml",
        flwr_version="1.25.0",
        image="superexec-image:latest",
        no_cache=False,
        platform=None,
        context=None,
        push=False,
        num_supernodes=3,
        auto_supernodes=True,
        supernodes=None,
        net=None,
        allow_oversubscribe=None,
        deploy_config=None,
        experiment=None,
        timeout_seconds=120,
        federation="remote-deployment",
        stream=True,
        destroy=True,
        submit_image=None,
        artifact_store=None,
        priority=50,
    )

    assert status == 0
    payload = captured["submission_payload"]
    resolved = resolve_experiment_config(project_root, "experiment.toml")
    assert resolved is not None
    expected = submit_cmd._default_submit_experiment_name(
        project_name="demo-project",
        resolved_experiment_config=resolved,
        run_config_overrides=None,
        seed=None,
    )
    assert payload["experiment"] == expected
    assert payload["submit_request"]["options"]["experiment"] == expected


def test_run_submit_auto_generated_experiment_includes_network_profile_label(
    monkeypatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    experiment_config = project_root / "experiment.toml"
    experiment_config.write_text(
        """
[experiment]
method = "fedbuff"
task = "cifar10_cnn"
seed = 1337

[server]
min-available-nodes = 20

[data]
partitioning = "dirichlet"
partitioning-dirichlet-alpha = 0.3

[capacity]
model-rate-levels = [1.0]
model-rate-proportions = [1.0]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    archive = tmp_path / "project.tar.gz"
    archive.write_bytes(b"artifact-bytes")
    captured: dict[str, object] = {}
    deploy_cfg_path = tmp_path / "main_network_heterogeneity_mild.yaml"

    monkeypatch.setattr(
        submit_cmd,
        "inspect_flwr_project",
        lambda _: SimpleNamespace(
            project_name="demo-project",
            local_sim_num_supernodes=None,
            root=project_root,
        ),
    )
    monkeypatch.setattr(
        submit_cmd,
        "resolve_deploy_config",
        lambda **_: SimpleNamespace(
            data={
                "deploy": {"network": {"default_profile": "mild"}},
                "submit": {
                    "image": "submit-image:latest",
                    "artifact_store": "s3+presign://fedctl-submits/fedctl-submits",
                    "endpoint": "http://submit.example:8080",
                    "token": "token-from-config",
                },
            },
            path=deploy_cfg_path,
        ),
    )

    class FakeSubmitClient:
        endpoint = "http://submit.example:8080"
        token = "token-from-client"

        def create_submission(self, payload):
            captured["submission_payload"] = payload
            return {"submission_id": "sub-123"}

    monkeypatch.setattr(submit_cmd, "_submit_service_client", lambda **_: FakeSubmitClient())
    monkeypatch.setattr(submit_cmd, "_build_project_archive", lambda *_, **__: archive)
    monkeypatch.setattr(
        submit_cmd,
        "upload_artifact",
        lambda *_, **__: "https://signed.example/get-object",
    )
    monkeypatch.setattr(submit_cmd, "load_config", lambda: object())
    monkeypatch.setattr(
        submit_cmd,
        "get_effective_config",
        lambda _: SimpleNamespace(namespace="default"),
    )

    status = submit_cmd.run_submit(
        path=str(project_root),
        experiment_config="experiment.toml",
        flwr_version="1.25.0",
        image="superexec-image:latest",
        no_cache=False,
        platform=None,
        context=None,
        push=False,
        num_supernodes=20,
        auto_supernodes=True,
        supernodes=None,
        net=None,
        allow_oversubscribe=None,
        deploy_config=str(deploy_cfg_path),
        experiment=None,
        timeout_seconds=120,
        federation="remote-deployment",
        stream=True,
        destroy=True,
        submit_image=None,
        artifact_store=None,
        priority=50,
    )

    assert status == 0
    payload = captured["submission_payload"]
    assert "-mild-" in payload["experiment"]
    assert payload["submit_request"]["options"]["experiment"] == payload["experiment"]


def test_submit_generated_experiment_name_distinguishes_config_variants(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    iid_config = project_root / "iid.toml"
    iid_config.write_text(
        """
[experiment]
method = "fedavg"
task = "california_housing_mlp"
seed = 1337

[server]
min-available-nodes = 20

[data]
partitioning = "iid"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    noniid_config = project_root / "noniid.toml"
    noniid_config.write_text(
        """
[experiment]
method = "fedavg"
task = "california_housing_mlp"
seed = 1337

[server]
min-available-nodes = 20

[data]
partitioning = "continuous"
partitioning-continuous-column = "MedInc"
partitioning-continuous-strictness = 0.5
""".strip()
        + "\n",
        encoding="utf-8",
    )

    iid_resolution = resolve_experiment_config(project_root, "iid.toml")
    noniid_resolution = resolve_experiment_config(project_root, "noniid.toml")
    assert iid_resolution is not None
    assert noniid_resolution is not None

    iid_name = submit_cmd._default_submit_experiment_name(
        project_name="demo-project",
        resolved_experiment_config=iid_resolution,
        run_config_overrides=None,
        seed=None,
    )
    noniid_name = submit_cmd._default_submit_experiment_name(
        project_name="demo-project",
        resolved_experiment_config=noniid_resolution,
        run_config_overrides=None,
        seed=None,
    )

    assert iid_name != noniid_name
    assert iid_name == "california_housing_mlp-fedavg-iid-s1337"
    assert noniid_name == "california_housing_mlp-fedavg-noniid-s1337"


def test_run_submit_explicit_experiment_overrides_generated_config_name(
    monkeypatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    experiment_config = project_root / "experiment.toml"
    experiment_config.write_text(
        """
[experiment]
method = "heterofl"
task = "cifar10_cnn"
seed = 1337

[server]
min-available-nodes = 20

[capacity]
model-rate-levels = [1.0, 0.5, 0.25, 0.125]
model-rate-proportions = [0.25, 0.25, 0.25, 0.25]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    archive = tmp_path / "project.tar.gz"
    archive.write_bytes(b"artifact-bytes")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        submit_cmd,
        "inspect_flwr_project",
        lambda _: SimpleNamespace(
            project_name="demo-project",
            local_sim_num_supernodes=None,
            root=project_root,
        ),
    )
    monkeypatch.setattr(
        submit_cmd,
        "resolve_deploy_config",
        lambda **_: SimpleNamespace(
            data={
                "submit": {
                    "image": "submit-image:latest",
                    "artifact_store": "s3+presign://fedctl-submits/fedctl-submits",
                    "endpoint": "http://submit.example:8080",
                    "token": "token-from-config",
                }
            },
            path=None,
        ),
    )

    class FakeSubmitClient:
        endpoint = "http://submit.example:8080"
        token = "token-from-client"

        def create_submission(self, payload):
            captured["submission_payload"] = payload
            return {"submission_id": "sub-123"}

    monkeypatch.setattr(
        submit_cmd,
        "_submit_service_client",
        lambda **_: FakeSubmitClient(),
    )
    monkeypatch.setattr(
        submit_cmd,
        "_build_project_archive",
        lambda *_, **__: archive,
    )
    monkeypatch.setattr(
        submit_cmd,
        "upload_artifact",
        lambda *_, **__: "https://signed.example/get-object",
    )
    monkeypatch.setattr(submit_cmd, "load_config", lambda: object())
    monkeypatch.setattr(
        submit_cmd,
        "get_effective_config",
        lambda _: SimpleNamespace(namespace="default"),
    )

    status = submit_cmd.run_submit(
        path=str(project_root),
        experiment_config="experiment.toml",
        flwr_version="1.25.0",
        image="superexec-image:latest",
        no_cache=False,
        platform=None,
        context=None,
        push=False,
        num_supernodes=3,
        auto_supernodes=True,
        supernodes=None,
        net=None,
        allow_oversubscribe=None,
        deploy_config=None,
        experiment="custom-exp",
        timeout_seconds=120,
        federation="remote-deployment",
        stream=True,
        destroy=True,
        submit_image=None,
        artifact_store=None,
        priority=50,
    )

    assert status == 0
    payload = captured["submission_payload"]
    assert payload["experiment"] == "custom-exp"
    assert payload["submit_request"]["options"]["experiment"] == "custom-exp"


def test_run_submit_omits_superexec_image_when_not_explicitly_provided(
    monkeypatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    archive = tmp_path / "project.tar.gz"
    archive.write_bytes(b"artifact-bytes")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        submit_cmd,
        "inspect_flwr_project",
        lambda _: SimpleNamespace(
            project_name="demo-project",
            local_sim_num_supernodes=None,
            root=project_root,
        ),
    )
    monkeypatch.setattr(
        submit_cmd,
        "resolve_deploy_config",
        lambda **_: SimpleNamespace(
            data={
                "submit": {
                    "image": "100.108.13.23:5000/fedctl-submit:latest",
                    "artifact_store": "s3+presign://fedctl-submits/fedctl-submits",
                    "endpoint": "http://submit.example:8080",
                    "token": "token-from-config",
                },
                "submit-service": {
                    "image_registry": "192.168.8.101:5000",
                },
                "image_registry": "100.108.13.23:5000",
            },
            path=None,
        ),
    )

    class FakeSubmitClient:
        endpoint = "http://submit.example:8080"
        token = "token-from-client"

        def create_submission(self, payload):
            captured["submission_payload"] = payload
            return {"submission_id": "sub-123"}

    monkeypatch.setattr(
        submit_cmd,
        "_submit_service_client",
        lambda **_: FakeSubmitClient(),
    )
    monkeypatch.setattr(
        submit_cmd,
        "_build_project_archive",
        lambda *_, **__: archive,
    )
    monkeypatch.setattr(
        submit_cmd,
        "upload_artifact",
        lambda *_, **__: "https://signed.example/get-object",
    )
    monkeypatch.setattr(submit_cmd, "load_config", lambda: object())
    monkeypatch.setattr(
        submit_cmd,
        "get_effective_config",
        lambda _: SimpleNamespace(namespace="default"),
    )

    status = submit_cmd.run_submit(
        path=str(project_root),
        flwr_version="1.25.0",
        image=None,
        no_cache=False,
        platform=None,
        context=None,
        push=False,
        num_supernodes=3,
        auto_supernodes=True,
        supernodes=None,
        net=None,
        allow_oversubscribe=None,
        deploy_config=None,
        experiment="demo-exp",
        timeout_seconds=120,
        federation="remote-deployment",
        stream=True,
        destroy=True,
        submit_image=None,
        artifact_store=None,
        priority=50,
    )

    assert status == 0
    payload = captured["submission_payload"]
    assert payload["submit_image"] == "192.168.8.101:5000/fedctl-submit:latest"
    assert "--image" not in payload["args"]
    assert "image" not in payload["submit_request"]["options"]


def test_run_submit_rewrites_explicit_superexec_image_to_internal_registry(
    monkeypatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    archive = tmp_path / "project.tar.gz"
    archive.write_bytes(b"artifact-bytes")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        submit_cmd,
        "inspect_flwr_project",
        lambda _: SimpleNamespace(
            project_name="demo-project",
            local_sim_num_supernodes=None,
            root=project_root,
        ),
    )
    monkeypatch.setattr(
        submit_cmd,
        "resolve_deploy_config",
        lambda **_: SimpleNamespace(
            data={
                "submit": {
                    "image": "100.108.13.23:5000/fedctl-submit:latest",
                    "artifact_store": "s3+presign://fedctl-submits/fedctl-submits",
                    "endpoint": "http://submit.example:8080",
                    "token": "token-from-config",
                },
                "submit-service": {
                    "image_registry": "192.168.8.101:5000",
                },
                "image_registry": "100.108.13.23:5000",
            },
            path=None,
        ),
    )

    class FakeSubmitClient:
        endpoint = "http://submit.example:8080"
        token = "token-from-client"

        def create_submission(self, payload):
            captured["submission_payload"] = payload
            return {"submission_id": "sub-123"}

    monkeypatch.setattr(
        submit_cmd,
        "_submit_service_client",
        lambda **_: FakeSubmitClient(),
    )
    monkeypatch.setattr(
        submit_cmd,
        "_build_project_archive",
        lambda *_, **__: archive,
    )
    monkeypatch.setattr(
        submit_cmd,
        "upload_artifact",
        lambda *_, **__: "https://signed.example/get-object",
    )
    monkeypatch.setattr(submit_cmd, "load_config", lambda: object())
    monkeypatch.setattr(
        submit_cmd,
        "get_effective_config",
        lambda _: SimpleNamespace(namespace="default"),
    )

    status = submit_cmd.run_submit(
        path=str(project_root),
        flwr_version="1.25.0",
        image="100.108.13.23:5000/demo-project-superexec:test123",
        no_cache=False,
        platform=None,
        context=None,
        push=False,
        num_supernodes=3,
        auto_supernodes=True,
        supernodes=None,
        net=None,
        allow_oversubscribe=None,
        deploy_config=None,
        experiment="demo-exp",
        timeout_seconds=120,
        federation="remote-deployment",
        stream=True,
        destroy=True,
        submit_image=None,
        artifact_store=None,
        priority=50,
    )

    assert status == 0
    payload = captured["submission_payload"]
    assert payload["submit_image"] == "192.168.8.101:5000/fedctl-submit:latest"
    image_idx = payload["args"].index("--image") + 1
    assert payload["args"][image_idx] == "192.168.8.101:5000/demo-project-superexec:test123"
    assert (
        payload["submit_request"]["options"]["image"]
        == "192.168.8.101:5000/demo-project-superexec:test123"
    )
    assert payload["env"]["FEDCTL_IMAGE_REGISTRY"] == "192.168.8.101:5000"


def test_run_submit_uses_deploy_config_supernodes_and_placement_defaults(
    monkeypatch, tmp_path: Path
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    archive = tmp_path / "project.tar.gz"
    archive.write_bytes(b"artifact-bytes")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        submit_cmd,
        "inspect_flwr_project",
        lambda _: SimpleNamespace(
            project_name="demo-project",
            local_sim_num_supernodes=2,
            root=project_root,
        ),
    )
    monkeypatch.setattr(
        submit_cmd,
        "resolve_deploy_config",
        lambda **_: SimpleNamespace(
            data={
                "deploy": {
                    "supernodes": {"rpi4": 2, "rpi5": 2},
                    "placement": {"allow_oversubscribe": False},
                },
                "submit": {
                    "image": "submit-image:latest",
                    "artifact_store": "s3+presign://fedctl-submits/fedctl-submits",
                    "endpoint": "http://submit.example:8080",
                    "token": "token-from-config",
                },
            },
            path=None,
        ),
    )

    class FakeSubmitClient:
        endpoint = "http://submit.example:8080"
        token = "token-from-client"

        def create_submission(self, payload):
            captured["submission_payload"] = payload
            return {"submission_id": "sub-123"}

    monkeypatch.setattr(
        submit_cmd,
        "_submit_service_client",
        lambda **_: FakeSubmitClient(),
    )
    monkeypatch.setattr(
        submit_cmd,
        "_build_project_archive",
        lambda *_, **__: archive,
    )
    monkeypatch.setattr(
        submit_cmd,
        "upload_artifact",
        lambda *_, **__: "https://signed.example/get-object",
    )
    monkeypatch.setattr(submit_cmd, "load_config", lambda: object())
    monkeypatch.setattr(
        submit_cmd,
        "get_effective_config",
        lambda _: SimpleNamespace(namespace="default"),
    )

    status = submit_cmd.run_submit(
        path=str(project_root),
        flwr_version="1.27.0",
        image=None,
        no_cache=False,
        platform=None,
        context=None,
        push=False,
        num_supernodes=2,
        auto_supernodes=True,
        supernodes=None,
        net=None,
        allow_oversubscribe=None,
        deploy_config=None,
        experiment="demo-exp",
        timeout_seconds=120,
        federation="remote-deployment",
        stream=True,
        destroy=True,
        submit_image=None,
        artifact_store=None,
        priority=50,
    )

    assert status == 0
    payload = captured["submission_payload"]
    assert payload["args"].count("--supernodes") == 2
    assert "rpi4=2" in payload["args"]
    assert "rpi5=2" in payload["args"]
    assert "--num-supernodes" not in payload["args"]
    assert "--no-allow-oversubscribe" in payload["args"]
    options = payload["submit_request"]["options"]
    assert options["supernodes"] == ["rpi4=2", "rpi5=2"]
    assert options["allow_oversubscribe"] is False
