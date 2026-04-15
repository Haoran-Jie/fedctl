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


def test_render_deploy_uses_overridden_runtime_resources() -> None:
    spec = default_deploy_spec(
        num_supernodes=1,
        image="example/superexec:latest",
        experiment="exp-test",
        superlink_resources={"cpu": 700, "mem": 384},
        superexec_serverapp_resources={"cpu": 1500, "mem": 2048},
        superexec_clientapp_resources={"cpu": 900, "mem": 768},
    )
    rendered = render_deploy(spec)

    superlink_task = rendered.superlink["Job"]["TaskGroups"][0]["Tasks"][0]
    serverapp_task = rendered.superexec_serverapp["Job"]["TaskGroups"][0]["Tasks"][0]
    clientapp_task = rendered.superexec_clientapps[0]["Job"]["TaskGroups"][0]["Tasks"][0]

    assert superlink_task["Resources"] == {"CPU": 700, "MemoryMB": 384}
    assert serverapp_task["Resources"] == {"CPU": 1500, "MemoryMB": 2048}
    assert clientapp_task["Resources"] == {"CPU": 900, "MemoryMB": 768}


def test_render_deploy_keeps_clientapp_colocated_with_pinned_supernode() -> None:
    placements = [
        SupernodePlacement(device_type="rpi4", instance_idx=1, node_id="node-rpi4-a"),
    ]
    spec = default_deploy_spec(
        num_supernodes=1,
        image="example/superexec:latest",
        experiment="exp-test",
        supernodes_by_type={"rpi4": 1},
        allow_oversubscribe=True,
        placements=placements,
    )
    rendered = render_deploy(spec)

    supernode_constraints = rendered.supernodes["Job"]["TaskGroups"][0]["Constraints"]
    client_constraints = rendered.superexec_clientapps[0]["Job"]["TaskGroups"][0]["Constraints"]

    assert any(
        c.get("LTarget") == "${node.unique.id}" and c.get("RTarget") == "node-rpi4-a"
        for c in supernode_constraints
    )
    assert any(
        c.get("LTarget") == "${node.unique.id}" and c.get("RTarget") == "node-rpi4-a"
        for c in client_constraints
    )


def test_render_deploy_superexec_jobs_include_custom_env() -> None:
    spec = default_deploy_spec(
        num_supernodes=1,
        image="example/superexec:latest",
        experiment="exp-test",
        superexec_env={"WANDB_PROJECT": "fedctl", "WANDB_ENTITY": "samueljie"},
    )
    rendered = render_deploy(spec)

    server_env = rendered.superexec_serverapp["Job"]["TaskGroups"][0]["Tasks"][0]["Env"]
    client_env = rendered.superexec_clientapps[0]["Job"]["TaskGroups"][0]["Tasks"][0]["Env"]

    assert server_env["WANDB_PROJECT"] == "fedctl"
    assert server_env["WANDB_ENTITY"] == "samueljie"
    assert client_env["WANDB_PROJECT"] == "fedctl"
    assert client_env["WANDB_ENTITY"] == "samueljie"


def test_render_deploy_supernodes_netem_task() -> None:
    placements = [
        SupernodePlacement(device_type="rpi5", instance_idx=1, node_id=None),
        SupernodePlacement(device_type="rpi5", instance_idx=2, node_id=None),
    ]
    assignments = parse_net_assignments(["rpi5[1]=med"])
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
        supernodes_by_type={"rpi5": 2},
        allow_oversubscribe=True,
        placements=placements,
        network_plan=network_plan,
        netem_image="example/netem:latest",
    )
    rendered = render_deploy(spec)
    groups = rendered.supernodes["Job"]["TaskGroups"]
    first_task = groups[0]["Tasks"][0]
    assert first_task["Name"] == "supernode-rpi5-1"
    assert first_task["Config"]["entrypoint"] == ["/bin/sh", "-lc"]
    assert first_task["Config"]["cap_add"] == ["NET_ADMIN"]
    assert first_task["Env"]["NET_PROFILE"] == "med"
    assert "while [ -z \"$${SUP_LINK_ADDR:-}\" ]" in first_task["Config"]["args"][0]
    assert groups[1]["Tasks"][0]["Name"] == "supernode-rpi5-2"
    assert "Env" not in groups[1]["Tasks"][0]


def test_render_deploy_netem_uses_configured_interface() -> None:
    placements = [
        SupernodePlacement(device_type="rpi5", instance_idx=1, node_id=None),
    ]
    network_plan = plan_network(
        assignments=[],
        placements=placements,
        default_profile="med",
        interface="wlan0",
        profiles={"med": {"delay_ms": 60}},
    )
    spec = default_deploy_spec(
        num_supernodes=1,
        image="example/superexec:latest",
        experiment="exp-test",
        supernodes_by_type={"rpi5": 1},
        allow_oversubscribe=True,
        placements=placements,
        network_plan=network_plan,
        netem_image="example/netem:latest",
    )
    rendered = render_deploy(spec)
    env = rendered.supernodes["Job"]["TaskGroups"][0]["Tasks"][0]["Env"]
    assert env["NET_IFACE"] == "wlan0"
    assert env["NET_INGRESS_IFACE"] == "wlan0"


def test_render_deploy_netem_allows_auto_interface_selection() -> None:
    placements = [
        SupernodePlacement(device_type="rpi5", instance_idx=1, node_id=None),
    ]
    network_plan = plan_network(
        assignments=[],
        placements=placements,
        default_profile="med",
        interface="auto",
        profiles={"med": {"delay_ms": 60}},
    )
    spec = default_deploy_spec(
        num_supernodes=1,
        image="example/superexec:latest",
        experiment="exp-test",
        supernodes_by_type={"rpi5": 1},
        allow_oversubscribe=True,
        placements=placements,
        network_plan=network_plan,
        netem_image="example/netem:latest",
    )
    rendered = render_deploy(spec)
    env = rendered.supernodes["Job"]["TaskGroups"][0]["Tasks"][0]["Env"]
    assert env["NET_IFACE"] == "auto"
    assert env["NET_INGRESS_IFACE"] == "auto"
    cmd = rendered.supernodes["Job"]["TaskGroups"][0]["Tasks"][0]["Config"]["args"][0]
    assert 'Could not auto-select a netem interface' in cmd
    assert 'cat /sys/class/net/wlan0/operstate' in cmd


def test_nomad_service_names_stay_within_length_limit_for_long_experiment_names() -> None:
    exp = "smoke-fedavg-fmnist-mlp-debug-seed1337"

    service_names = [
        naming.service_superlink_serverappio(exp),
        naming.service_superlink_fleet(exp),
        naming.service_superlink_control(exp),
        naming.service_supernode_clientappio(exp, 1, "rpi4"),
    ]

    assert all(len(name) <= 63 for name in service_names)
    assert naming.service_supernode_clientappio(exp, 1, "rpi4").endswith(
        "-supernode-rpi4-1-clientappio"
    )
    assert naming.service_superlink_serverappio(exp).endswith("-superlink-serverappio")
    assert len(set(service_names)) == len(service_names)


def test_nomad_service_names_are_rfc1123_safe() -> None:
    exp = "cifar10_cnn-FIARSE-n20-seed1337"

    service_names = [
        naming.service_superlink_serverappio(exp),
        naming.service_superlink_fleet(exp),
        naming.service_superlink_control(exp),
        naming.service_supernode_clientappio(exp, 1, "rpi4"),
    ]

    assert all("_" not in name for name in service_names)
    assert all(name == name.lower() for name in service_names)
    assert naming.service_superlink_serverappio(exp).startswith(
        "cifar10-cnn-fiarse-n20-seed1337-"
    )


def test_nomad_service_names_remain_rfc1123_safe_after_truncation() -> None:
    exp = "appliances_energy_mlp-heterofl-n20-seed1337"

    service_names = [
        naming.service_superlink_serverappio(exp),
        naming.service_superlink_fleet(exp),
        naming.service_superlink_control(exp),
        naming.service_supernode_clientappio(exp, 1, "rpi5"),
    ]

    assert all(len(name) <= 63 for name in service_names)
    assert all("_" not in name for name in service_names)
    assert all(name == name.lower() for name in service_names)
    assert naming.service_superlink_serverappio(exp).startswith(
        "appliances-energy-mlp-heterofl"
    )


def test_render_deploy_long_experiment_uses_length_safe_service_names() -> None:
    exp = "smoke-fedavg-fmnist-mlp-debug-seed1337"
    spec = default_deploy_spec(
        num_supernodes=2,
        image="example/superexec:latest",
        experiment=exp,
        supernodes_by_type={"rpi4": 1, "rpi5": 1},
    )

    rendered = render_deploy(spec)

    superlink_services = rendered.superlink["Job"]["TaskGroups"][0]["Services"]
    supernode_services = [
        group["Tasks"][0]["Services"][0]
        for group in rendered.supernodes["Job"]["TaskGroups"]
    ]

    all_names = [svc["Name"] for svc in superlink_services + supernode_services]
    assert all(len(name) <= 63 for name in all_names)
