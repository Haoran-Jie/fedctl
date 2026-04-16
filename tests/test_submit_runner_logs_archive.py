from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fedctl.submit import runner
from fedctl.submit.runner import (
    _LogArchiver,
    _archive_object_name,
    _latest_alloc_for_task,
    _log_archive_signature,
    _truncate_log_text,
)


def test_log_archiver_builds_targets_for_default_topology() -> None:
    archiver = _LogArchiver(
        submission_id="sub-1",
        submit_service_endpoint="http://submit.example",
        submit_service_token="token",
        result_store="s3://results",
        experiment="exp-1",
        num_supernodes=2,
        supernodes=None,
        endpoint="http://nomad.example:4646",
        namespace="default",
        token="nomad-token",
    )

    targets = archiver._targets()  # noqa: SLF001
    labels = [(target["job"], target["index"]) for target in targets]

    assert ("submit", 1) in labels
    assert ("superlink", 1) in labels
    assert ("superexec_serverapp", 1) in labels
    assert ("supernodes", 1) in labels
    assert ("supernodes", 2) in labels
    assert ("superexec_clientapps", 1) in labels
    assert ("superexec_clientapps", 2) in labels


def test_truncate_log_text_keeps_head_and_tail() -> None:
    original = "A" * 40 + "B" * 40
    truncated = _truncate_log_text(original, max_chars=40)

    assert "log truncated for archive size" in truncated
    assert truncated.startswith("A" * 20)
    assert truncated.endswith("B" * 20)


def test_latest_alloc_for_task_prefers_matching_alloc() -> None:
    allocs = [
        {
            "ID": "alloc-newer-wrong-task",
            "ModifyTime": 20,
            "TaskStates": {"supernode-rpi5-2": {}},
        },
        {
            "ID": "alloc-older-correct-task",
            "ModifyTime": 10,
            "AllocatedResources": {"Tasks": {"supernode-rpi5-1": {}}},
        },
    ]

    alloc = _latest_alloc_for_task(allocs, "supernode-rpi5-1")

    assert alloc is not None
    assert alloc["ID"] == "alloc-older-correct-task"


def test_main_uses_effective_experiment_for_reporting_and_archiving(
    monkeypatch, tmp_path: Path
) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr(runner, "_resolve_project_path", lambda path, project_dir: tmp_path)
    monkeypatch.setattr(
        runner,
        "inspect_flwr_project",
        lambda project_path: SimpleNamespace(
            project_name="demo-project",
            local_sim_num_supernodes=4,
        ),
    )
    monkeypatch.setattr(
        runner,
        "resolve_run_experiment_name",
        lambda *, project_name, experiment: "demo-project-20260415220000",
    )

    def fake_report_jobs(**kwargs):
        calls["report_experiment"] = kwargs["experiment"]
        calls["report_num_supernodes"] = kwargs["num_supernodes"]

    class FakeUploader:
        def __init__(self, **kwargs):
            calls["uploader_experiment"] = kwargs["experiment"]
            self.enabled = True

        def start(self) -> None:
            calls["uploader_started"] = True

        def stop(self) -> None:
            calls["uploader_stopped"] = True

        def final_sweep(self) -> None:
            calls["uploader_final_sweep"] = True

    class FakeLogArchiver:
        def __init__(self, **kwargs):
            calls["archiver_experiment"] = kwargs["experiment"]
            calls["archiver_num_supernodes"] = kwargs["num_supernodes"]
            self.enabled = True
            self.started = False
            self.stopped = False

        def start(self) -> None:
            self.started = True
            calls["archiver_started"] = True

        def stop(self) -> None:
            self.stopped = True
            calls["archiver_stopped"] = True

        def final_sweep(self) -> None:
            calls["archiver_final_sweep"] = True

    def fake_run_run(**kwargs):
        calls["run_experiment"] = kwargs["experiment"]
        return 0

    monkeypatch.setattr(runner, "_report_jobs", fake_report_jobs)
    monkeypatch.setattr(runner, "_ResultUploader", FakeUploader)
    monkeypatch.setattr(runner, "_LogArchiver", FakeLogArchiver)
    monkeypatch.setattr(runner, "run_run", fake_run_run)

    monkeypatch.setenv("SUBMIT_SUBMISSION_ID", "sub-1")
    monkeypatch.setenv("SUBMIT_SERVICE_ENDPOINT", "http://submit.example")
    monkeypatch.setenv("SUBMIT_SERVICE_TOKEN", "token")
    monkeypatch.setenv("FEDCTL_ENDPOINT", "http://nomad.example:4646")
    monkeypatch.setenv("FEDCTL_RESULT_STORE", "s3://results")

    status = runner.main(["--path", str(tmp_path), "--no-destroy"])

    assert status == 0
    assert calls["report_experiment"] == "demo-project-20260415220000"
    assert calls["report_num_supernodes"] == 4
    assert calls["uploader_experiment"] == "demo-project-20260415220000"
    assert calls["archiver_experiment"] == "demo-project-20260415220000"
    assert calls["archiver_num_supernodes"] == 4
    assert calls["archiver_started"] is True
    assert calls["archiver_stopped"] is True
    assert calls["run_experiment"] == "demo-project-20260415220000"


def test_log_archiver_reports_only_when_logs_change(monkeypatch) -> None:
    posted: list[dict[str, object]] = []
    uploaded: list[tuple[str, str, bytes]] = []
    archiver = _LogArchiver(
        submission_id="sub-1",
        submit_service_endpoint="http://submit.example",
        submit_service_token="token",
        result_store="s3://results",
        experiment="exp-1",
        num_supernodes=2,
        supernodes=None,
        endpoint="http://nomad.example:4646",
        namespace="default",
        token="nomad-token",
    )
    entries = [
        {
            "job": "submit",
            "index": 1,
            "job_id": "sub-1",
            "task": "submit",
            "stderr": False,
            "content": "hello",
        }
    ]

    monkeypatch.setattr(archiver, "_collect", lambda: entries.copy())

    class FakeResponse:
        status_code = 200
        text = "ok"

    def fake_post(url, json, headers, timeout):  # noqa: ANN001
        posted.append(json)
        return FakeResponse()

    def fake_upload_artifact(path, store, **kwargs):  # noqa: ANN001
        uploaded.append((path.name, store, path.read_bytes()))
        return f"https://storage.example/{store.rsplit('/', 1)[-1]}/{path.name}"

    monkeypatch.setattr(runner.httpx, "post", fake_post)
    monkeypatch.setattr(runner, "upload_artifact", fake_upload_artifact)

    archiver._archive_current(force=False)  # noqa: SLF001
    archiver._archive_current(force=False)  # noqa: SLF001
    archiver.final_sweep()

    assert len(posted) == 2
    assert posted[0]["logs_location"] == "https://storage.example/sub-1/manifest.json"
    assert posted[1]["logs_location"] == "https://storage.example/sub-1/manifest.json"
    assert [(name, store) for name, store, _ in uploaded] == [
        ("1-submit.stdout.log", "s3://results/logs/sub-1/submit"),
        ("manifest.json", "s3://results/logs/sub-1"),
        ("1-submit.stdout.log", "s3://results/logs/sub-1/submit"),
        ("manifest.json", "s3://results/logs/sub-1"),
    ]
    assert _log_archive_signature(entries) == archiver._last_uploaded_signature  # noqa: SLF001


def test_archive_object_name_encodes_job_index_task_and_stream() -> None:
    entry = {
        "job": "superexec_clientapps",
        "index": 3,
        "task": "clientapp-rpi5-1",
        "stderr": True,
    }

    assert _archive_object_name(entry) == "superexec_clientapps/3-clientapp-rpi5-1.stderr.log"


def test_log_archiver_manifest_records_upload_failure(monkeypatch) -> None:
    uploaded: list[bytes] = []
    archiver = _LogArchiver(
        submission_id="sub-1",
        submit_service_endpoint="http://submit.example",
        submit_service_token="token",
        result_store="s3://results",
        experiment="exp-1",
        num_supernodes=2,
        supernodes=None,
        endpoint="http://nomad.example:4646",
        namespace="default",
        token="nomad-token",
    )
    entries = [
        {
            "job": "submit",
            "index": 1,
            "job_id": "sub-1",
            "task": "submit",
            "stderr": False,
            "content": "hello",
        }
    ]

    def fake_upload_artifact(path, store, **kwargs):  # noqa: ANN001
        if path.name == "manifest.json":
            uploaded.append(path.read_bytes())
            return "https://storage.example/manifest.json"
        raise runner.ArtifactUploadError("boom")

    monkeypatch.setattr(runner, "upload_artifact", fake_upload_artifact)

    manifest_url = archiver._upload_archive(entries)  # noqa: SLF001

    assert manifest_url == "https://storage.example/manifest.json"
    manifest = runner.json.loads(uploaded[0].decode("utf-8"))
    assert manifest["entries"][0]["error"] == "archive upload failed"
    assert "url" not in manifest["entries"][0]
