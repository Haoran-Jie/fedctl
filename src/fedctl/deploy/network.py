from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


UNTYPED_KEY = "_untyped"


@dataclass(frozen=True)
class NetAssignment:
    device_type: str | None
    index: int | None
    wildcard: bool
    ingress_profile: str
    egress_profile: str


@dataclass(frozen=True)
class NetworkPlan:
    scope: str
    default_profile: str
    profiles: dict[str, dict[str, float | int]]
    ingress_profiles: dict[str, dict[str, float | int]]
    egress_profiles: dict[str, dict[str, float | int]]
    assignments: dict[str, list[str]]
    ingress_assignments: dict[str, list[str]]
    egress_assignments: dict[str, list[str]]


def parse_net_assignments(values: Iterable[str]) -> list[NetAssignment]:
    result: list[NetAssignment] = []
    for raw in values:
        parts = [p for p in raw.split(",") if p]
        for part in parts:
            if "=" not in part:
                raise ValueError(f"Invalid net assignment: {part}")
            selector_raw, profile_raw = part.split("=", 1)
            selector = selector_raw.strip()
            profile = profile_raw.strip()
            if not selector:
                raise ValueError(f"Invalid net assignment: {part}")
            if not profile:
                raise ValueError("Net assignment profile cannot be empty.")
            ingress_profile, egress_profile = _parse_profile_pair(profile)
            device_type, idx = _parse_selector(selector)
            if idx == "*":
                result.append(
                    NetAssignment(
                        device_type=device_type,
                        index=None,
                        wildcard=True,
                        ingress_profile=ingress_profile,
                        egress_profile=egress_profile,
                    )
                )
                continue
            try:
                index = int(idx)
            except ValueError as exc:
                raise ValueError(f"Invalid net index: {selector}") from exc
            if index <= 0:
                raise ValueError(f"Net index must be >= 1: {selector}")
            result.append(
                NetAssignment(
                    device_type=device_type,
                    index=index,
                    wildcard=False,
                    ingress_profile=ingress_profile,
                    egress_profile=egress_profile,
                )
            )
    return result


def plan_network(
    *,
    assignments: Iterable[NetAssignment],
    placements: list[object],
    default_profile: str | None,
    profiles: dict[str, dict[str, float | int]] | None,
    ingress_profiles: dict[str, dict[str, float | int]] | None = None,
    egress_profiles: dict[str, dict[str, float | int]] | None = None,
    scope: str | None = None,
) -> NetworkPlan:
    scope_value = (scope or "allocation").strip() or "allocation"
    if scope_value not in {"allocation", "node"}:
        raise ValueError(f"Invalid network scope: {scope_value}")

    default_name = (default_profile or "none").strip() or "none"
    profile_defs = _normalize_profiles(profiles)
    ingress_defs = _merge_profiles(profile_defs, _normalize_profiles(ingress_profiles))
    egress_defs = _merge_profiles(profile_defs, _normalize_profiles(egress_profiles))

    assignment_map = _init_assignment_lists(placements, default_name)
    ingress_map = _init_assignment_lists(placements, default_name)
    egress_map = _init_assignment_lists(placements, default_name)
    if not assignment_map:
        return NetworkPlan(
            scope=scope_value,
            default_profile=default_name,
            profiles=profile_defs,
            ingress_profiles=ingress_defs,
            egress_profiles=egress_defs,
            assignments={},
            ingress_assignments={},
            egress_assignments={},
        )

    has_untyped = UNTYPED_KEY in assignment_map
    has_typed = any(key != UNTYPED_KEY for key in assignment_map)
    if has_untyped and has_typed:
        raise ValueError("Mixed typed and untyped placements are not supported.")

    for assignment in assignments:
        key = assignment.device_type if assignment.device_type is not None else UNTYPED_KEY
        if key not in assignment_map:
            available = ", ".join(sorted(k for k in assignment_map if k != UNTYPED_KEY))
            if assignment.device_type is None:
                raise ValueError("Net assignments must use typed selectors when using --supernodes.")
            raise ValueError(
                f"Unknown net device type '{assignment.device_type}'. Available: {available}"
            )
        if assignment.device_type is not None and has_untyped:
            raise ValueError("Net assignments cannot use typed selectors with untyped supernodes.")
        if assignment.device_type is None and has_typed:
            raise ValueError("Net assignments must use typed selectors with typed supernodes.")

        if assignment.ingress_profile != default_name and assignment.ingress_profile not in ingress_defs:
            available_profiles = ", ".join(sorted(ingress_defs))
            raise ValueError(
                f"Unknown net ingress profile '{assignment.ingress_profile}'. Available: {available_profiles}"
            )
        if assignment.egress_profile != default_name and assignment.egress_profile not in egress_defs:
            available_profiles = ", ".join(sorted(egress_defs))
            raise ValueError(
                f"Unknown net egress profile '{assignment.egress_profile}'. Available: {available_profiles}"
            )

        targets = assignment_map[key]
        ingress_targets = ingress_map[key]
        egress_targets = egress_map[key]
        if assignment.wildcard:
            for idx in range(len(targets)):
                targets[idx] = assignment.egress_profile
                ingress_targets[idx] = assignment.ingress_profile
                egress_targets[idx] = assignment.egress_profile
            continue
        if assignment.index is None:
            raise ValueError("Net assignment index is required.")
        if assignment.index > len(targets):
            raise ValueError(
                f"Net index {assignment.index} out of range for '{key}' ({len(targets)})."
            )
        targets[assignment.index - 1] = assignment.egress_profile
        ingress_targets[assignment.index - 1] = assignment.ingress_profile
        egress_targets[assignment.index - 1] = assignment.egress_profile

    return NetworkPlan(
        scope=scope_value,
        default_profile=default_name,
        profiles=profile_defs,
        ingress_profiles=ingress_defs,
        egress_profiles=egress_defs,
        assignments=assignment_map,
        ingress_assignments=ingress_map,
        egress_assignments=egress_map,
    )


def _parse_selector(selector: str) -> tuple[str | None, str]:
    value = selector.strip()
    if value.startswith("[") and value.endswith("]"):
        return None, value[1:-1].strip()
    if "[" not in value or not value.endswith("]"):
        raise ValueError(f"Invalid net assignment selector: {selector}")
    device_type, idx = value.split("[", 1)
    device_type = device_type.strip()
    if not device_type:
        raise ValueError(f"Invalid net assignment selector: {selector}")
    return device_type, idx[:-1].strip()


def _parse_profile_pair(profile: str) -> tuple[str, str]:
    value = profile.strip()
    if value.startswith("(") and value.endswith(")"):
        inner = value[1:-1].strip()
        parts = [p.strip() for p in inner.split(",")]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(f"Invalid net profile tuple: {profile}")
        return parts[0], parts[1]
    return value, value


def _normalize_profiles(
    profiles: dict[str, dict[str, float | int]] | None,
) -> dict[str, dict[str, float | int]]:
    result: dict[str, dict[str, float | int]] = {}
    if not profiles:
        return result
    for key, val in profiles.items():
        if not isinstance(key, str):
            continue
        if not isinstance(val, dict):
            continue
        cleaned: dict[str, float | int] = {}
        for k, v in val.items():
            if isinstance(v, (int, float)):
                cleaned[str(k)] = v
        result[key] = cleaned
    return result


def _merge_profiles(
    base: dict[str, dict[str, float | int]],
    overrides: dict[str, dict[str, float | int]],
) -> dict[str, dict[str, float | int]]:
    if not overrides:
        return dict(base)
    merged = dict(base)
    for name, values in overrides.items():
        merged[name] = values
    return merged


def _init_assignment_lists(
    placements: list[object],
    default_profile: str,
) -> dict[str, list[str]]:
    sizes: dict[str, int] = {}
    for placement in placements:
        device_type = getattr(placement, "device_type", None)
        instance_idx = getattr(placement, "instance_idx", None)
        if not isinstance(instance_idx, int):
            continue
        key = device_type if isinstance(device_type, str) else UNTYPED_KEY
        sizes[key] = max(sizes.get(key, 0), instance_idx)
    return {key: [default_profile] * size for key, size in sizes.items()}


def assignment_key(device_type: str | None) -> str:
    return device_type if device_type is not None else UNTYPED_KEY
