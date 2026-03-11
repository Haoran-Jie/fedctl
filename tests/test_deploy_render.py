from __future__ import annotations

from fedctl.deploy import naming
from fedctl.deploy.network import parse_net_assignments, plan_network
from fedctl.deploy.render import render_deploy
from fedctl.deploy.plan import SupernodePlacement
from fedctl.deploy.spec import default_deploy_spec


def test_render_deploy_superlink_basic() -> None:
    spec = default_deploy_spec(
        num_supernodes=2,
        image="example/superexec:latest",
        experiment="exp-test",
    )
    rendered = render_deploy(spec)

    job = rendered.superlink["Job"]
    assert job["Name"] == naming.job_superlink("exp-test")
    assert job["Namespace"] == "default"

    constraints = job.get("Constraints", [])
    assert any(
        c.get("LTarget") == "${node.class}" and c.get("RTarget") == "link"
        for c in constraints
    )

    group = job["TaskGroups"][0]
    ports = group["Networks"][0]["DynamicPorts"]
    port_labels = {p["Label"] for p in ports}
    assert {"serverappio", "fleet", "control"} <= port_labels

    service_names = {svc["Name"] for svc in group["Services"]}
    assert naming.service_superlink_fleet("exp-test") in service_names
    assert naming.service_superlink_serverappio("exp-test") in service_names
    assert naming.service_superlink_control("exp-test") in service_names


def test_render_deploy_supernodes_groups() -> None:
    spec = default_deploy_spec(
        num_supernodes=2,
        image="example/superexec:latest",
        experiment="exp-test",
    )
    rendered = render_deploy(spec)
    job = rendered.supernodes["Job"]
    assert job["Namespace"] == "default"

    groups = job["TaskGroups"]
    assert len(groups) == 2
    assert groups[0]["Name"] == "supernode-1"
    assert groups[1]["Name"] == "supernode-2"

    task_services = [
        groups[0]["Tasks"][0]["Services"][0]["Name"],
        groups[1]["Tasks"][0]["Services"][0]["Name"],
    ]
    assert task_services == [
        naming.service_supernode_clientappio("exp-test", 1),
        naming.service_supernode_clientappio("exp-test", 2),
    ]

    task_cfg = groups[0]["Tasks"][0]["Config"]
    assert task_cfg["entrypoint"] == ["/bin/sh", "-lc"]
    cmd = task_cfg["args"][0]
    assert "$${SUP_LINK_ADDR}" in cmd
    assert "while [ -z \"$${SUP_LINK_ADDR:-}\" ]" in cmd
    assert "FEDCTL_WAIT_SUP_LINK_ADDR_TIMEOUT_S" in cmd
    assert "--node-config" in cmd
    assert "partition-id=0 num-partitions=2" in cmd


def test_render_deploy_superexec_jobs() -> None:
    spec = default_deploy_spec(
        num_supernodes=1,
        image="example/superexec:latest",
        experiment="exp-test",
    )
    rendered = render_deploy(spec)

    server_job = rendered.superexec_serverapp["Job"]
    assert server_job["Namespace"] == "default"
    group = server_job["TaskGroups"][0]
    constraint = group["Constraints"][0]
    assert constraint["LTarget"] == "${node.class}"
    assert constraint["RTarget"] == "link"

    template = group["Tasks"][0]["Templates"][0]["EmbeddedTmpl"]
    assert naming.service_superlink_serverappio("exp-test") in template
    server_cfg = group["Tasks"][0]["Config"]
    assert server_cfg["entrypoint"] == ["/bin/sh", "-lc"]
    assert "$${SERVERAPP_IO}" in server_cfg["args"][0]

    client_job = rendered.superexec_clientapps[0]["Job"]
    assert client_job["Namespace"] == "default"
    client_group = client_job["TaskGroups"][0]
    template = client_group["Tasks"][0]["Templates"][0]["EmbeddedTmpl"]
    assert naming.service_supernode_clientappio("exp-test", 1) in template
    client_cfg = client_group["Tasks"][0]["Config"]
    assert client_cfg["entrypoint"] == ["/bin/sh", "-lc"]
    assert "$${CLIENT_IO}" in client_cfg["args"][0]
    assert "while [ -z \"$${CLIENT_IO:-}\" ]" in client_cfg["args"][0]
    assert "FEDCTL_WAIT_CLIENT_IO_TIMEOUT_S" in client_cfg["args"][0]


def test_render_deploy_supernodes_netem_task() -> None:
    placements = [
        SupernodePlacement(device_type="rpi", instance_idx=1, node_id=None),
        SupernodePlacement(device_type="rpi", instance_idx=2, node_id=None),
    ]
    assignments = parse_net_assignments(["rpi[1]=med"])
    network_plan = plan_network(
        assignments=assignments,
        placements=placements,
        default_profile="none",
        profiles={"med": {"delay_ms": 60}},
    )
    spec = default_deploy_spec(
        num_supernodes=2,
        image="example/superexec:latest",
        experiment="exp-test",
        supernodes_by_type={"rpi": 2},
        allow_oversubscribe=True,
        placements=placements,
        network_plan=network_plan,
        netem_image="example/netem:latest",
    )
    rendered = render_deploy(spec)
    groups = rendered.supernodes["Job"]["TaskGroups"]
    first_task = groups[0]["Tasks"][0]
    assert first_task["Name"] == "supernode-rpi-1"
    assert first_task["Config"]["entrypoint"] == ["/bin/sh", "-lc"]
    assert first_task["Config"]["cap_add"] == ["NET_ADMIN"]
    assert first_task["Env"]["NET_PROFILE"] == "med"
    assert "while [ -z \"$${SUP_LINK_ADDR:-}\" ]" in first_task["Config"]["args"][0]
    assert groups[1]["Tasks"][0]["Name"] == "supernode-rpi-2"
    assert "Env" not in groups[1]["Tasks"][0]
