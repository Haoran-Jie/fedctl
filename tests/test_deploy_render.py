from __future__ import annotations

from fedctl.deploy import naming
from fedctl.deploy.render import render_deploy
from fedctl.deploy.spec import default_deploy_spec


def test_render_deploy_superlink_basic() -> None:
    spec = default_deploy_spec(num_supernodes=2)
    rendered = render_deploy(spec)

    job = rendered.superlink["Job"]
    assert job["Name"] == naming.job_superlink()

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
    assert naming.service_superlink_fleet() in service_names
    assert naming.service_superlink_serverappio() in service_names
    assert naming.service_superlink_control() in service_names


def test_render_deploy_supernodes_groups() -> None:
    spec = default_deploy_spec(num_supernodes=2)
    rendered = render_deploy(spec)
    job = rendered.supernodes["Job"]

    groups = job["TaskGroups"]
    assert len(groups) == 2
    assert groups[0]["Name"] == "supernode-1"
    assert groups[1]["Name"] == "supernode-2"

    task_services = [
        groups[0]["Tasks"][0]["Services"][0]["Name"],
        groups[1]["Tasks"][0]["Services"][0]["Name"],
    ]
    assert task_services == [
        naming.service_supernode_clientappio(1),
        naming.service_supernode_clientappio(2),
    ]

    args = groups[0]["Tasks"][0]["Config"]["args"]
    assert "--node-config" in args
    assert "partition-id=0 num-partitions=2" in args


def test_render_deploy_superexec_jobs() -> None:
    spec = default_deploy_spec(num_supernodes=1)
    rendered = render_deploy(spec)

    server_job = rendered.superexec_serverapp["Job"]
    group = server_job["TaskGroups"][0]
    constraint = group["Constraints"][0]
    assert constraint["LTarget"] == "${node.class}"
    assert constraint["RTarget"] == "link"

    template = group["Tasks"][0]["Templates"][0]["EmbeddedTmpl"]
    assert naming.service_superlink_serverappio() in template

    client_job = rendered.superexec_clientapps[0]["Job"]
    client_group = client_job["TaskGroups"][0]
    template = client_group["Tasks"][0]["Templates"][0]["EmbeddedTmpl"]
    assert naming.service_supernode_clientappio(1) in template
