"""Resolve research methods by runtime name."""

from __future__ import annotations

from fedctl_research.methods import fedavg, fedavgm, fedbuff, fedrolex, fedstaleweight, fiarse, heterofl
from fedctl_research.methods.base import MethodModule

_METHODS: dict[str, MethodModule] = {
    "fedavg": fedavg,
    "fedavgm": fedavgm,
    "fedbuff": fedbuff,
    "fedstaleweight": fedstaleweight,
    "fiarse": fiarse,
    "fedrolex": fedrolex,
    "heterofl": heterofl,
}


def resolve_method(name: str) -> MethodModule:
    try:
        return _METHODS[name]
    except KeyError as exc:
        known = ", ".join(sorted(_METHODS))
        raise ValueError(f"Unknown method '{name}'. Known methods: {known}") from exc
