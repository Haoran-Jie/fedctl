from __future__ import annotations


def job_superlink(exp: str) -> str:
    return f"{exp}-superlink"


def job_supernodes(exp: str) -> str:
    return f"{exp}-supernodes"


def job_superexec_serverapp(exp: str) -> str:
    return f"{exp}-superexec-serverapp"


def job_superexec_clientapp(exp: str, index: int) -> str:
    return f"{exp}-superexec-clientapp-{index}"


def service_superlink_serverappio(exp: str) -> str:
    return f"{exp}-superlink-serverappio"


def service_superlink_fleet(exp: str) -> str:
    return f"{exp}-superlink-fleet"


def service_superlink_control(exp: str) -> str:
    return f"{exp}-superlink-control"


def service_supernode_clientappio(exp: str, index: int) -> str:
    return f"{exp}-supernode-{index}-clientappio"
