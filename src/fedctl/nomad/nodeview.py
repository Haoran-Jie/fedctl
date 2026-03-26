from __future__ import annotations

import re
from typing import Any, Iterable, Optional

_DEVICE_NAME_RE = re.compile(r"^(rpi\d+)(?:[-_].*)?$", re.IGNORECASE)


def _first_value(node: dict, keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        if key in node and node[key] is not None:
            return str(node[key])
    return None


def extract_from_meta_or_attr(node: dict, key: str) -> Optional[str]:
    meta = node.get("Meta", {}) if isinstance(node.get("Meta"), dict) else {}
    attrs = node.get("Attributes", {}) if isinstance(node.get("Attributes"), dict) else {}
    if key in meta and meta[key] is not None:
        return str(meta[key])
    if key in attrs and attrs[key] is not None:
        return str(attrs[key])
    return None


def extract_device(node: dict) -> Optional[str]:
    return extract_from_meta_or_attr(node, "device")


def extract_device_type(node: dict) -> Optional[str]:
    value = extract_from_meta_or_attr(node, "device_type")
    if value:
        return value

    name = node.get("Name")
    if isinstance(name, str):
        match = _DEVICE_NAME_RE.match(name.strip())
        if match:
            return match.group(1).lower()
    return None


def extract_gpu(node: dict) -> Optional[str]:
    return extract_from_meta_or_attr(node, "gpu")


def extract_arch(node: dict) -> Optional[str]:
    attrs = node.get("Attributes", {}) if isinstance(node.get("Attributes"), dict) else {}
    value = attrs.get("arch")
    return str(value) if value is not None else None


def extract_os(node: dict) -> Optional[str]:
    attrs = node.get("Attributes", {}) if isinstance(node.get("Attributes"), dict) else {}
    value = attrs.get("os")
    return str(value) if value is not None else None
