from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ProfileConfig:
    endpoint: str
    namespace: Optional[str] = None
    deploy_config: Optional[str] = None


@dataclass
class FedctlConfig:
    active_profile: str = "default"
    profiles: Dict[str, ProfileConfig] = field(default_factory=dict)


@dataclass
class EffectiveConfig:
    profile_name: str
    endpoint: str
    namespace: Optional[str]
    nomad_token: Optional[str]
