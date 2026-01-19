from __future__ import annotations


def job_superlink() -> str:
    return "superlink"


def job_supernodes() -> str:
    return "supernodes"


def job_superexec_serverapp() -> str:
    return "superexec-serverapp"


def job_superexec_clientapp(index: int) -> str:
    return f"superexec-clientapp-{index}"


def service_superlink_serverappio() -> str:
    return "superlink-serverappio"


def service_superlink_fleet() -> str:
    return "superlink-fleet"


def service_superlink_control() -> str:
    return "superlink-control"


def service_supernode_clientappio(index: int) -> str:
    return f"supernode-{index}-clientappio"
