from __future__ import annotations

import hashlib


_NOMAD_SERVICE_NAME_MAX = 63
_TRUNCATION_HASH_LEN = 8


def _nomad_service_name(exp: str, suffix: str) -> str:
    candidate = f"{exp}{suffix}"
    if len(candidate) <= _NOMAD_SERVICE_NAME_MAX:
        return candidate

    available = _NOMAD_SERVICE_NAME_MAX - len(suffix) - _TRUNCATION_HASH_LEN - 1
    if available <= 0:
        digest = hashlib.sha1(candidate.encode("utf-8")).hexdigest()[:_TRUNCATION_HASH_LEN]
        return f"{digest}{suffix}"[:_NOMAD_SERVICE_NAME_MAX]

    exp_prefix = exp[:available].rstrip("-")
    if not exp_prefix:
        exp_prefix = exp[:available]
    digest = hashlib.sha1(candidate.encode("utf-8")).hexdigest()[:_TRUNCATION_HASH_LEN]
    return f"{exp_prefix}-{digest}{suffix}"


def job_superlink(exp: str) -> str:
    return f"{exp}-superlink"


def job_supernodes(exp: str) -> str:
    return f"{exp}-supernodes"


def job_superexec_serverapp(exp: str) -> str:
    return f"{exp}-superexec-serverapp"


def job_superexec_clientapp(
    exp: str, index: int, device_type: str | None = None
) -> str:
    if device_type:
        return f"{exp}-superexec-clientapp-{device_type}-{index}"
    return f"{exp}-superexec-clientapp-{index}"


def service_superlink_serverappio(exp: str) -> str:
    return _nomad_service_name(exp, "-superlink-serverappio")


def service_superlink_fleet(exp: str) -> str:
    return _nomad_service_name(exp, "-superlink-fleet")


def service_superlink_control(exp: str) -> str:
    return _nomad_service_name(exp, "-superlink-control")


def service_supernode_clientappio(
    exp: str, index: int, device_type: str | None = None
) -> str:
    if device_type:
        return _nomad_service_name(exp, f"-supernode-{device_type}-{index}-clientappio")
    return _nomad_service_name(exp, f"-supernode-{index}-clientappio")
