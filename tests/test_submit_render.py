from __future__ import annotations

from fedctl.submit.render import SubmitJobSpec, render_submit_job


def test_render_submit_job_basic() -> None:
    spec = SubmitJobSpec(
        job_name="submit-exp-123",
        node_class="submit",
        image="example/submit:latest",
        artifact_url="https://example.com/archive.tar.gz",
        namespace="ns",
        args=["-m", "fedctl.submit.runner", "--path", "local/project"],
        env={"FEDCTL_ENDPOINT": "http://127.0.0.1:4646"},
        priority=75,
    )
    rendered = render_submit_job(spec)
    job = rendered["Job"]
    assert job["Name"] == "submit-exp-123"
    assert job["Namespace"] == "ns"
    assert job["Type"] == "batch"
    assert job["Priority"] == 75

    group = job["TaskGroups"][0]
    constraint = job["Constraints"][0]
    assert constraint["LTarget"] == "${node.class}"
    assert constraint["RTarget"] == "submit"

    task = group["Tasks"][0]
    assert task["Config"]["image"] == "example/submit:latest"
    assert task["Config"]["args"] == ["-m", "fedctl.submit.runner", "--path", "local/project"]
    assert task["Artifacts"][0]["GetterSource"] == "https://example.com/archive.tar.gz"
    assert task["Env"]["FEDCTL_ENDPOINT"] == "http://127.0.0.1:4646"
