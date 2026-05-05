from __future__ import annotations

import fedctl.commands.submit as submit_cmd


def test_run_submit_logs_follow_uses_stream_path(monkeypatch) -> None:
    captured = {"lines": None}

    class FakeClient:
        def stream_logs(self, submission_id, *, job, task, stderr, index):
            assert submission_id == "sub-1"
            assert job == "submit"
            assert task is None
            assert stderr is False
            assert index == 1
            yield "line-a"
            yield "line-b"

        def get_logs(self, *args, **kwargs):
            raise AssertionError("get_logs should not be called when follow=True")

    def fake_print_streamed_logs(lines):
        captured["lines"] = list(lines)

    monkeypatch.setattr(submit_cmd, "_submit_service_client", lambda **_: FakeClient())
    monkeypatch.setattr(submit_cmd, "_print_streamed_logs", fake_print_streamed_logs)

    status = submit_cmd.run_submit_logs(
        submission_id="sub-1",
        job="submit",
        task=None,
        stderr=False,
        follow=True,
        index=1,
    )
    assert status == 0
    assert captured["lines"] == ["line-a", "line-b"]


def test_run_submit_logs_defaults_submit_job_to_stdout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def get_logs(self, submission_id, *, job, task, stderr, follow, index):
            captured.update(
                {
                    "submission_id": submission_id,
                    "job": job,
                    "task": task,
                    "stderr": stderr,
                    "follow": follow,
                    "index": index,
                }
            )
            return "submit stdout"

    monkeypatch.setattr(submit_cmd, "_submit_service_client", lambda **_: FakeClient())
    monkeypatch.setattr(submit_cmd, "_print_structured_logs", lambda logs: None)

    status = submit_cmd.run_submit_logs(
        submission_id="sub-1",
        job="submit",
        task=None,
        stderr=None,
        follow=False,
        index=1,
    )

    assert status == 0
    assert captured["stderr"] is False


def test_run_submit_logs_defaults_runtime_jobs_to_stderr(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def get_logs(self, submission_id, *, job, task, stderr, follow, index):
            captured.update({"job": job, "stderr": stderr})
            return "superlink stderr"

    monkeypatch.setattr(submit_cmd, "_submit_service_client", lambda **_: FakeClient())
    monkeypatch.setattr(submit_cmd, "_print_structured_logs", lambda logs: None)

    status = submit_cmd.run_submit_logs(
        submission_id="sub-1",
        job="superlink",
        task=None,
        stderr=None,
        follow=False,
        index=1,
    )

    assert status == 0
    assert captured == {"job": "superlink", "stderr": True}
