from __future__ import annotations

from submit_service.app.config import SubmitConfig
from submit_service.app.nomad_inventory import NomadInventory


class FakeClient:
    def __init__(self, nodes, details, allocs):
        self._nodes = nodes
        self._details = details
        self._allocs = allocs

    def nodes(self):
        return self._nodes

    def node(self, node_id: str):
        return self._details[node_id]

    def node_allocations(self, node_id: str):
        return self._allocs[node_id]

    def close(self) -> None:
        return None


def _cfg(ttl: int = 5) -> SubmitConfig:
    return SubmitConfig(
        db_url="sqlite:///submit_service/state/submit.db",
        tokens=set(),
        token_identities={},
        allow_unauth=True,
        service_endpoint=None,
        nomad_endpoint="http://127.0.0.1:4646",
        nomad_token=None,
        nomad_namespace=None,
        nomad_tls_ca=None,
        nomad_tls_skip_verify=False,
        dispatch_mode="queue",
        dispatch_interval=10,
        datacenter="dc1",
        default_priority=50,
        docker_socket=None,
        nomad_inventory_ttl=ttl,
        autopurge_completed_after_s=0,
    )


def test_inventory_enriches_resources_and_allocs() -> None:
    nodes = [
        {
            "ID": "n1",
            "Name": "node1",
            "Status": "ready",
            "Drain": False,
            "NodeClass": "node",
            "Datacenter": "dc1",
            "Address": "10.0.0.1",
            "Meta": {"device_type": "jetson", "device": "j1", "gpu": "yes"},
        }
    ]
    details = {
        "n1": {
            "Node": {
                "Resources": {
                    "CPU": 2000,
                    "MemoryMB": 4096,
                    "Devices": [
                        {"Name": "gpu0", "Vendor": "nvidia", "Type": "gpu"},
                    ],
                },
            }
        }
    }
    allocs = {
        "n1": [
            {
                "ID": "a1",
                "Resources": {"CPU": 500, "MemoryMB": 256},
                "ClientStatus": "running",
                "JobID": "job1",
                "TaskGroup": "group1",
            },
            {
                "ID": "a2",
                "AllocatedResources": {"Tasks": {"t1": {"CPU": 250, "MemoryMB": 128}}},
                "ClientStatus": "pending",
                "JobID": "job2",
                "TaskGroup": "group2",
            },
        ]
    }

    inventory = NomadInventory(
        _cfg(),
        client_factory=lambda: FakeClient(nodes, details, allocs),
    )
    data = inventory.list_nodes(include_allocs=True)
    assert len(data) == 1
    node = data[0]
    assert node["device_type"] == "jetson"
    assert node["resources"]["total_cpu"] == 2000
    assert node["resources"]["total_mem"] == 4096
    assert node["resources"]["used_cpu"] == 750
    assert node["resources"]["used_mem"] == 384
    assert node["allocations"]["count"] == 2
    assert node["allocations"]["running_jobs"] == ["job1"]
    assert node["devices"][0]["name"] == "gpu0"
    assert node["allocations"]["items"][0]["tasks"][0]["name"] == "alloc"
    assert node["allocations"]["items"][1]["tasks"][0]["name"] == "t1"


def test_inventory_handles_nested_allocated_resources() -> None:
    nodes = [
        {
            "ID": "n1",
            "Name": "node1",
            "Status": "ready",
            "Drain": False,
            "NodeClass": "node",
            "Datacenter": "dc1",
            "Address": "10.0.0.1",
            "Meta": {"device_type": "jetson"},
        }
    ]
    details = {"n1": {"Node": {"Resources": {"CPU": 1000, "MemoryMB": 1024}}}}
    allocs = {
        "n1": [
            {
                "ID": "a1",
                "AllocatedResources": {
                    "Tasks": {
                        "t1": {
                            "Cpu": {"CpuShares": 200},
                            "Memory": {"MemoryMB": 64},
                        }
                    }
                },
                "ClientStatus": "running",
                "JobID": "job1",
                "TaskGroup": "group1",
            }
        ]
    }

    inventory = NomadInventory(
        _cfg(),
        client_factory=lambda: FakeClient(nodes, details, allocs),
    )
    data = inventory.list_nodes(include_allocs=True)
    node = data[0]
    assert node["resources"]["used_cpu"] == 200
    assert node["resources"]["used_mem"] == 64
    assert node["allocations"]["items"][0]["tasks"][0]["name"] == "t1"


def test_inventory_cache_hits() -> None:
    calls = {"count": 0}
    nodes = [{"ID": "n1", "Name": "node1"}]

    def factory():
        calls["count"] += 1
        return FakeClient(nodes, {"n1": {}}, {"n1": []})

    inventory = NomadInventory(_cfg(ttl=60), client_factory=factory)
    inventory.list_nodes()
    inventory.list_nodes()
    assert calls["count"] == 1
