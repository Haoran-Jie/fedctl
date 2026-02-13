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


def test_parse_net_assignments_supports_tuple_and_multiple_entries() -> None:
    assignments = parse_net_assignments(["[1]=med,[2]=(low,high)"])
    assert len(assignments) == 2
    assert assignments[0].device_type is None
    assert assignments[0].index == 1
    assert assignments[0].ingress_profile == "med"
    assert assignments[0].egress_profile == "med"
    assert assignments[1].device_type is None
    assert assignments[1].index == 2
    assert assignments[1].ingress_profile == "low"
    assert assignments[1].egress_profile == "high"


def test_plan_network_supports_tuple_assignment_for_untyped_supernodes() -> None:
    placements = [
        SupernodePlacement(device_type=None, instance_idx=1, node_id=None),
        SupernodePlacement(device_type=None, instance_idx=2, node_id=None),
    ]
    assignments = parse_net_assignments(["[1]=med,[2]=(low,high)"])
    plan = plan_network(
        assignments=assignments,
        placements=placements,
        default_profile="none",
        profiles={
            "none": {},
            "med": {"delay_ms": 60},
            "low": {"delay_ms": 20},
            "high": {"delay_ms": 120},
        },
    )
    untyped_key = assignment_key(None)
    assert plan.assignments[untyped_key] == ["med", "high"]
    assert plan.ingress_assignments[untyped_key] == ["med", "low"]
    assert plan.egress_assignments[untyped_key] == ["med", "high"]
