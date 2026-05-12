from __future__ import annotations

from types import SimpleNamespace

import fedctl.commands.submit as submit_cmd


class _FakeSubmitClient:
    def __init__(self, record: dict[str, object]):
        self._record = record

    def get_submission(self, submission_id: str) -> dict[str, object]:
        return {**self._record, "submission_id": submission_id}


def test_submit_status_prints_logs_next_step_for_active_status(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        submit_cmd,
        "_submit_service_client",
        lambda **_: _FakeSubmitClient({"status": "running"}),
    )

    status = submit_cmd.run_submit_status(submission_id="sub-123")

    assert status == 0
    output = capsys.readouterr().out
    assert "Status:" in output
    assert "running" in output
    assert "fedctl submit logs sub-123" in output


def test_submit_status_omits_logs_next_step_for_terminal_status(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        submit_cmd,
        "_submit_service_client",
        lambda **_: _FakeSubmitClient({"status": "completed"}),
    )

    status = submit_cmd.run_submit_status(submission_id="sub-123")

    assert status == 0
    output = capsys.readouterr().out
    assert "Status:" in output
    assert "completed" in output
    assert "fedctl submit logs sub-123" not in output


class _FakeNomadClient:
    def __init__(self, _eff: object):
        pass

    def job(self, submission_id: str) -> dict[str, object]:
        return {"ID": submission_id, "Status": "running"}

    def job_allocations(self, _submission_id: str) -> list[dict[str, object]]:
        return [{"ID": "alloc-1", "ClientStatus": "running"}]

    def close(self) -> None:
        return None


def test_submit_status_prints_logs_next_step_for_running_nomad_job(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(submit_cmd, "_submit_service_client", lambda **_: None)
    monkeypatch.setattr(submit_cmd, "load_config", lambda: object())
    monkeypatch.setattr(
        submit_cmd,
        "get_effective_config",
        lambda _cfg: SimpleNamespace(namespace="default"),
    )
    monkeypatch.setattr(submit_cmd, "NomadClient", _FakeNomadClient)

    status = submit_cmd.run_submit_status(submission_id="submit-demo")

    assert status == 0
    output = capsys.readouterr().out
    assert "Job:" in output
    assert "running" in output
    assert "fedctl submit logs submit-demo" in output
