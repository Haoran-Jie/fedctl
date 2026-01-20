from __future__ import annotations

from dataclasses import dataclass

from fedctl.deploy import naming
from fedctl.deploy.render import render_deploy
from fedctl.deploy.resolve import wait_for_superlink
from fedctl.deploy.spec import default_deploy_spec
from fedctl.deploy.submit import submit_jobs


def test_submit_jobs_order() -> None:
    spec = default_deploy_spec(
        num_supernodes=2,
        image="example/superexec:latest",
        experiment="exp-test",
    )
    rendered = render_deploy(spec)

    client = DummySubmitClient()
    submitted = submit_jobs(client, rendered)

    assert submitted == [
        naming.job_superlink("exp-test"),
        naming.job_supernodes("exp-test"),
        naming.job_superexec_serverapp("exp-test"),
        naming.job_superexec_clientapp("exp-test", 1),
        naming.job_superexec_clientapp("exp-test", 2),
    ]

    assert client.submitted == submitted


def test_wait_for_superlink_success() -> None:
    client = DummyResolveClient()
    result = wait_for_superlink(
        client,
        job_name=naming.job_superlink("exp-test"),
        timeout_seconds=5,
        poll_interval=0.2,
    )

    assert result.alloc_id == "alloc-1"
    assert result.node_id == "node-123"
    assert result.ip == "192.168.1.10"
    assert result.ports == {"control": 27738, "fleet": 27739, "serverappio": 27740}


class DummySubmitClient:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit_job(self, job: dict) -> None:
        name = job.get("Job", {}).get("Name")
        if isinstance(name, str):
            self.submitted.append(name)


@dataclass
class DummyResolveClient:
    def job_allocations(self, job_name: str) -> list[dict]:
        assert job_name == naming.job_superlink("exp-test")
        return [{"ID": "alloc-1", "ClientStatus": "running"}]

    def allocation(self, alloc_id: str) -> dict:
        assert alloc_id == "alloc-1"
        return {
            "ID": "alloc-1",
            "NodeID": "node-123",
            "ClientStatus": "running",
            "TaskStates": {"exp-test-superlink": {"State": "running"}},
            "AllocatedResources": {
                "Shared": {
                    "Networks": [
                        {
                            "IP": "192.168.1.10",
                            "DynamicPorts": [
                                {"Label": "control", "Value": 27738},
                                {"Label": "fleet", "Value": 27739},
                                {"Label": "serverappio", "Value": 27740},
                            ]
                        }
                    ]
                }
            },
        }
