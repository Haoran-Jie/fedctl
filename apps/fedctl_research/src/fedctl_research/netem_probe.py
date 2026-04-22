"""Best-effort netem verification metrics collected inside client tasks."""

from __future__ import annotations

from functools import lru_cache
from collections.abc import Mapping
import os
import re
import shutil
import subprocess

ScalarMetric = int | float

_RATE_RE = re.compile(r"\brate\s+([0-9.]+)\s*([kKmMgG]?)(?:bit|bps)\b")
_DELAY_RE = re.compile(r"\bdelay\s+([0-9.]+)ms(?:\s+([0-9.]+)ms)?")
_LOSS_RE = re.compile(r"\bloss\s+([0-9.]+)%")


def _env_float(name: str) -> float:
    value = os.environ.get(name)
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def _run_text(args: list[str], *, timeout_s: float = 0.5) -> str:
    try:
        completed = subprocess.run(
            args,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()


def _default_route_iface() -> str:
    output = _run_text(["ip", "route", "show", "default"])
    for line in output.splitlines():
        parts = line.split()
        if "dev" in parts:
            idx = parts.index("dev")
            if idx + 1 < len(parts):
                return parts[idx + 1]
    return "eth0"


def _resolve_iface(raw: str | None) -> str:
    value = (raw or "").strip()
    if value and value.lower() not in {"auto", "default"}:
        return value
    return _default_route_iface()


def _rate_to_mbit(match: re.Match[str] | None) -> float:
    if match is None:
        return 0.0
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "g":
        return value * 1000.0
    if unit == "k":
        return value / 1000.0
    return value


def parse_qdisc_metrics(text: str, *, prefix: str) -> dict[str, ScalarMetric]:
    """Extract a small stable numeric summary from `tc qdisc show` output."""
    delay_match = _DELAY_RE.search(text)
    loss_match = _LOSS_RE.search(text)
    return {
        f"{prefix}-has-netem": int("netem" in text),
        f"{prefix}-has-tbf": int("tbf" in text),
        f"{prefix}-has-ingress": int("ingress" in text),
        f"{prefix}-delay-ms": float(delay_match.group(1)) if delay_match else 0.0,
        f"{prefix}-jitter-ms": float(delay_match.group(2)) if delay_match and delay_match.group(2) else 0.0,
        f"{prefix}-loss-pct": float(loss_match.group(1)) if loss_match else 0.0,
        f"{prefix}-rate-mbit": _rate_to_mbit(_RATE_RE.search(text)),
    }


@lru_cache(maxsize=1)
def collect_netem_probe_metrics() -> dict[str, ScalarMetric]:
    """Return scalar metrics safe to attach to Flower train replies.

    The probe is intentionally best-effort: missing `tc`, missing `iproute2`, or
    unsupported qdisc output should not fail client training.
    """
    if not any(key == "NET_PROFILE" or key.startswith("NET_INGRESS_") for key in os.environ):
        return {}

    egress_iface = _resolve_iface(os.environ.get("NET_IFACE"))
    ingress_ifb = os.environ.get("NET_INGRESS_IFB", "ifb0").strip() or "ifb0"
    tc_available = shutil.which("tc") is not None
    expected_enabled = 0 if os.environ.get("NET_PROFILE", "none").strip().lower() == "none" else 1
    expected_ingress_enabled = int(os.environ.get("NET_INGRESS_ENABLED", "0").strip() == "1")

    metrics: dict[str, ScalarMetric] = {
        "netem-probe-attempted": 1,
        "netem-tc-available": int(tc_available),
        "netem-expected-enabled": expected_enabled,
        "netem-expected-delay-ms": _env_float("NET_DELAY_MS"),
        "netem-expected-jitter-ms": _env_float("NET_JITTER_MS"),
        "netem-expected-loss-pct": _env_float("NET_LOSS_PCT"),
        "netem-expected-rate-mbit": _env_float("NET_RATE_MBIT"),
        "netem-expected-ingress-enabled": expected_ingress_enabled,
        "netem-expected-ingress-delay-ms": _env_float("NET_INGRESS_DELAY_MS"),
        "netem-expected-ingress-jitter-ms": _env_float("NET_INGRESS_JITTER_MS"),
        "netem-expected-ingress-loss-pct": _env_float("NET_INGRESS_LOSS_PCT"),
        "netem-expected-ingress-rate-mbit": _env_float("NET_INGRESS_RATE_MBIT"),
    }
    if not tc_available:
        metrics["netem-probe-ok"] = 0
        return metrics

    egress_text = _run_text(["tc", "qdisc", "show", "dev", egress_iface])
    ingress_text = _run_text(["tc", "qdisc", "show", "dev", ingress_ifb])
    metrics.update(parse_qdisc_metrics(egress_text, prefix="netem-egress"))
    metrics.update(parse_qdisc_metrics(ingress_text, prefix="netem-ingress"))

    actual_enabled = int(bool(metrics.get("netem-egress-has-netem") or metrics.get("netem-egress-has-tbf")))
    actual_ingress_enabled = int(bool(metrics.get("netem-ingress-has-netem") or metrics.get("netem-ingress-has-tbf")))
    metrics["netem-probe-ok"] = int(
        actual_enabled == expected_enabled and actual_ingress_enabled == expected_ingress_enabled
    )
    return metrics


def netem_payload_from_metrics(metrics: Mapping[str, object] | None) -> dict[str, ScalarMetric]:
    if metrics is None:
        return {}
    payload: dict[str, ScalarMetric] = {}
    for key, value in metrics.items():
        if not str(key).startswith("netem-") or not isinstance(value, (int, float)):
            continue
        payload[str(key).replace("-", "_")] = value
    return payload
