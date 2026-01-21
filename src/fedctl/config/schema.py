from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Literal

AccessMode = Literal["tailscale-subnet", "tailscale-mesh", "lan-only", "ssh-tunnel"]


@dataclass
class TailscaleConfig:
    subnet_cidr: Optional[str] = None


@dataclass
class ProfileConfig:
    endpoint: str
    namespace: Optional[str] = None
    repo_config: Optional[str] = None
    tls_ca: Optional[str] = None
    tls_skip_verify: bool = False
    access_mode: AccessMode = "lan-only"
    tailscale: TailscaleConfig = field(default_factory=TailscaleConfig)


@dataclass
class FedctlConfig:
    active_profile: str = "default"
    profiles: Dict[str, ProfileConfig] = field(default_factory=dict)


@dataclass
class EffectiveConfig:
    profile_name: str
    endpoint: str
    namespace: Optional[str]
    tls_ca: Optional[str]
    tls_skip_verify: bool
    access_mode: AccessMode
    tailscale_subnet_cidr: Optional[str]
    nomad_token: Optional[str]
