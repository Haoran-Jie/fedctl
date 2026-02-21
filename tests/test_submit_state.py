from __future__ import annotations

from pathlib import Path

import pytest

from fedctl.state.submissions import SubmissionRecord, load_submissions, record_submission


def test_record_and_load_submissions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fedctl.state.submissions.user_config_dir", lambda: tmp_path)

    record_submission(
        SubmissionRecord(
            submission_id="sub-1",
            experiment="exp",
            created_at="2024-01-01T00:00:00Z",
            namespace="ns",
        )
    )
    record_submission(
        SubmissionRecord(
            submission_id="sub-2",
            experiment="exp2",
            created_at="2024-01-02T00:00:00Z",
            namespace="ns",
        )
    )
    entries = load_submissions()
    assert entries[0]["submission_id"] == "sub-2"
    assert entries[1]["submission_id"] == "sub-1"
    assert entries[0]["status"] == "queued"
    assert entries[1]["status"] == "queued"


def test_record_submission_max_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fedctl.state.submissions.user_config_dir", lambda: tmp_path)

    record_submission(
        SubmissionRecord(
            submission_id="sub-1",
            experiment="exp",
            created_at="2024-01-01T00:00:00Z",
        ),
        max_entries=1,
    )
    record_submission(
        SubmissionRecord(
            submission_id="sub-2",
            experiment="exp2",
            created_at="2024-01-02T00:00:00Z",
        ),
        max_entries=1,
    )
    entries = load_submissions()
    assert len(entries) == 1
    assert entries[0]["submission_id"] == "sub-2"


def test_load_submissions_backfills_missing_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("fedctl.state.submissions.user_config_dir", lambda: tmp_path)
    path = tmp_path / "state" / "submissions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '[{"submission_id":"sub-legacy","experiment":"exp","created_at":"2024-01-01T00:00:00Z"}]',
        encoding="utf-8",
    )

    entries = load_submissions()
    assert entries[0]["submission_id"] == "sub-legacy"
    assert entries[0]["status"] == "queued"
