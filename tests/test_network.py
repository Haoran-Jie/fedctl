from __future__ import annotations

from fedctl.deploy.network import assignment_key, parse_net_assignments, plan_network
from fedctl.deploy.plan import SupernodePlacement


def test_plan_network_typed_assignments() -> None:
    placements = [
        SupernodePlacement(device_type="rpi", instance_idx=1, node_id=None),
        SupernodePlacement(device_type="rpi", instance_idx=2, node_id=None),
        SupernodePlacement(device_type="jetson", instance_idx=1, node_id=None),
    ]
    assignments = parse_net_assignments(["rpi[1]=med,rpi[2]=none,jetson[*]=high"])
    plan = plan_network(
        assignments=assignments,
        placements=placements,
        default_profile="none",
        profiles={"med": {"delay_ms": 60}, "high": {"delay_ms": 200}},
    )

    rpi_key = assignment_key("rpi")
    jetson_key = assignment_key("jetson")
    assert plan.assignments[rpi_key] == ["med", "none"]
    assert plan.assignments[jetson_key] == ["high"]

