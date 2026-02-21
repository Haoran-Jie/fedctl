from __future__ import annotations

from fedctl.submit.runner import _LogArchiver, _truncate_log_text


def test_log_archiver_builds_targets_for_default_topology() -> None:
    archiver = _LogArchiver(
        submission_id="sub-1",
        submit_service_endpoint="http://submit.example",
        submit_service_token="token",
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
