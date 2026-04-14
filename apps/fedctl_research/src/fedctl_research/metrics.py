"""Shared metric formatting helpers."""

from __future__ import annotations

from collections.abc import Mapping


def normalize_metric_mapping(
    metrics: Mapping[str, int | float],
    *,
    model_rate_digits: int = 6,
    model_rate_tol: float = 1e-12,
) -> dict[str, int | float]:
    """Normalize presentation-only float noise in aggregated metrics."""
    normalized: dict[str, int | float] = {}
    for key, value in metrics.items():
        if isinstance(value, float) and "model-rate" in key:
            rounded = round(value, model_rate_digits)
            nearest_int = round(rounded)
            if abs(rounded - nearest_int) < model_rate_tol:
                normalized[key] = float(nearest_int)
            else:
                normalized[key] = rounded
            continue
        normalized[key] = value
    return normalized
