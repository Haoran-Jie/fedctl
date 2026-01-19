from __future__ import annotations

import os
from typing import Optional

from .schema import FedctlConfig, EffectiveConfig


def get_effective_config(
    cfg: FedctlConfig,
    profile_name: Optional[str] = None,
    endpoint: Optional[str] = None,
    namespace: Optional[str] = None,
    token: Optional[str] = None,
    tls_ca: Optional[str] = None,
    tls_skip_verify: Optional[bool] = None,
) -> EffectiveConfig:
    name = profile_name or os.environ.get("FEDCTL_PROFILE") or cfg.active_profile
    if name not in cfg.profiles:
        raise ValueError(f"Unknown profile '{name}'. Use `fedctl profile ls`.")

    p = cfg.profiles[name]

    env_endpoint = os.environ.get("FEDCTL_ENDPOINT")
    env_namespace = os.environ.get("FEDCTL_NAMESPACE")
    env_token = os.environ.get("NOMAD_TOKEN")

    eff_endpoint = endpoint or env_endpoint or p.endpoint
    eff_namespace = namespace or env_namespace or p.namespace
    eff_tls_ca = tls_ca or p.tls_ca
    eff_tls_skip = tls_skip_verify if tls_skip_verify is not None else p.tls_skip_verify

    eff_token = token or env_token

    return EffectiveConfig(
        profile_name=name,
        endpoint=eff_endpoint,
        namespace=eff_namespace,
        tls_ca=eff_tls_ca,
        tls_skip_verify=eff_tls_skip,
        access_mode=p.access_mode,
        tailscale_subnet_cidr=p.tailscale.subnet_cidr,
        nomad_token=eff_token,
    )
