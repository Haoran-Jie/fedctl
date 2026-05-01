from __future__ import annotations

import pytest

from fedctl.deploy.network import assignment_key, parse_net_assignments, plan_network
from fedctl.deploy.plan import SupernodePlacement, plan_supernodes
from fedctl.commands.deploy import _resolve_network_plan


def test_plan_network_typed_assignments() -> None:
    placements = [
        SupernodePlacement(device_type="rpi5", instance_idx=1, node_id=None),
        SupernodePlacement(device_type="rpi5", instance_idx=2, node_id=None),
        SupernodePlacement(device_type="jetson", instance_idx=1, node_id=None),
    ]
    assignments = parse_net_assignments(["rpi5[1]=med,rpi5[2]=none,jetson[*]=high"])
    plan = plan_network(
        assignments=assignments,
        placements=placements,
        default_profile="none",
        profiles={"med": {"delay_ms": 60}, "high": {"delay_ms": 200}},
    )

    rpi_key = assignment_key("rpi5")
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


def test_resolve_network_plan_uses_deploy_default_assignment_without_cli_net() -> None:
    placements = [
        SupernodePlacement(device_type="rpi4", instance_idx=1, node_id=None),
        SupernodePlacement(device_type="rpi5", instance_idx=1, node_id=None),
    ]

    plan, resolved_placements = _resolve_network_plan(
        net=None,
        placements=placements,
        supernodes_by_type={"rpi4": 1, "rpi5": 1},
        num_supernodes=2,
        deploy_network_profiles={
            "none": {},
            "med": {"delay_ms": 60},
        },
        deploy_network_ingress_profiles={},
        deploy_network_egress_profiles={},
        deploy_network_default="none",
        deploy_network_default_assignment=["rpi4[*]=med,rpi5[*]=med"],
        deploy_network_interface="eth0",
    )

    assert resolved_placements == placements
    assert plan is not None
    assert plan.assignments[assignment_key("rpi4")] == ["med"]
    assert plan.assignments[assignment_key("rpi5")] == ["med"]


def test_resolve_network_plan_cli_net_overrides_deploy_default_assignment() -> None:
    placements = [
        SupernodePlacement(device_type="rpi4", instance_idx=1, node_id=None),
        SupernodePlacement(device_type="rpi5", instance_idx=1, node_id=None),
    ]

    plan, _ = _resolve_network_plan(
        net=["rpi4[*]=none,rpi5[*]=med"],
        placements=placements,
        supernodes_by_type={"rpi4": 1, "rpi5": 1},
        num_supernodes=2,
        deploy_network_profiles={
            "none": {},
            "mild": {"delay_ms": 20},
            "med": {"delay_ms": 60},
        },
        deploy_network_ingress_profiles={},
        deploy_network_egress_profiles={},
        deploy_network_default="none",
        deploy_network_default_assignment=["rpi4[*]=mild,rpi5[*]=mild"],
        deploy_network_interface="eth0",
    )

    assert plan is not None
    assert plan.assignments[assignment_key("rpi4")] == ["none"]
    assert plan.assignments[assignment_key("rpi5")] == ["med"]


def test_resolve_network_plan_deploy_default_assignment_supports_asymmetry() -> None:
    placements = [
        SupernodePlacement(device_type="rpi4", instance_idx=1, node_id=None),
        SupernodePlacement(device_type="rpi5", instance_idx=1, node_id=None),
    ]

    plan, _ = _resolve_network_plan(
        net=None,
        placements=placements,
        supernodes_by_type={"rpi4": 1, "rpi5": 1},
        num_supernodes=2,
        deploy_network_profiles={"none": {}},
        deploy_network_ingress_profiles={
            "asym_down": {"delay_ms": 90},
        },
        deploy_network_egress_profiles={
            "asym_up": {"delay_ms": 90},
        },
        deploy_network_default="none",
        deploy_network_default_assignment=["rpi4[*]=(none,asym_up),rpi5[*]=(asym_down,none)"],
        deploy_network_interface="eth0",
    )

    assert plan is not None
    assert plan.ingress_assignments[assignment_key("rpi4")] == ["none"]
    assert plan.egress_assignments[assignment_key("rpi4")] == ["asym_up"]
    assert plan.ingress_assignments[assignment_key("rpi5")] == ["asym_down"]
    assert plan.egress_assignments[assignment_key("rpi5")] == ["none"]


def test_plan_network_rejects_unknown_default_profile() -> None:
    placements = [
        SupernodePlacement(device_type="rpi5", instance_idx=1, node_id=None),
    ]

    with pytest.raises(ValueError, match="Unknown default net profile 'med'"):
        plan_network(
            assignments=[],
            placements=placements,
            default_profile="med",
            profiles={"none": {}},
        )


def test_plan_network_rejects_directionally_incomplete_default_profile() -> None:
    placements = [
        SupernodePlacement(device_type="rpi5", instance_idx=1, node_id=None),
    ]

    with pytest.raises(ValueError, match="for ingress"):
        plan_network(
            assignments=[],
            placements=placements,
            default_profile="asym_up",
            profiles={"none": {}},
            egress_profiles={"asym_up": {"delay_ms": 80}},
        )


def test_plan_supernodes_uses_all_available_nodes_without_off_by_one() -> None:
    nodes = [
        {"ID": "node-a", "Name": "rpi4-001"},
        {"ID": "node-b", "Name": "rpi4-002"},
    ]
    placements = plan_supernodes(
        counts={"rpi4": 2},
        allow_oversubscribe=False,
        nodes=nodes,
    )
    assert placements == [
        SupernodePlacement(
            device_type="rpi4",
            instance_idx=1,
            node_id="node-a",
            preferred_node_id="node-a",
        ),
        SupernodePlacement(
            device_type="rpi4",
            instance_idx=2,
            node_id="node-b",
            preferred_node_id="node-b",
        ),
    ]


def test_plan_supernodes_spread_across_hosts_pins_nodes_even_when_oversubscribed() -> None:
    nodes = [
        {"ID": "node-a", "Name": "rpi4-001"},
        {"ID": "node-b", "Name": "rpi4-002"},
    ]
    placements = plan_supernodes(
        counts={"rpi4": 2},
        allow_oversubscribe=True,
        spread_across_hosts=True,
        nodes=nodes,
    )
    assert placements == [
        SupernodePlacement(
            device_type="rpi4",
            instance_idx=1,
            node_id="node-a",
            preferred_node_id="node-a",
        ),
        SupernodePlacement(
            device_type="rpi4",
            instance_idx=2,
            node_id="node-b",
            preferred_node_id="node-b",
        ),
    ]


def test_plan_supernodes_prefer_spread_across_hosts_softly_prefers_nodes() -> None:
    nodes = [
        {"ID": "node-a", "Name": "rpi5-001"},
        {"ID": "node-b", "Name": "rpi5-002"},
    ]
    placements = plan_supernodes(
        counts={"rpi5": 3},
        allow_oversubscribe=True,
        prefer_spread_across_hosts=True,
        nodes=nodes,
    )
    assert placements == [
        SupernodePlacement(
            device_type="rpi5",
            instance_idx=1,
            node_id=None,
            preferred_node_id="node-a",
        ),
        SupernodePlacement(
            device_type="rpi5",
            instance_idx=2,
            node_id=None,
            preferred_node_id="node-b",
        ),
        SupernodePlacement(
            device_type="rpi5",
            instance_idx=3,
            node_id=None,
            preferred_node_id="node-a",
        ),
    ]
