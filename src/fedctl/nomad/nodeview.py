from __future__ import annotations

from typing import Any, Iterable, Optional


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
    return extract_from_meta_or_attr(node, "device_type")


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
