from __future__ import annotations

import sys
from pathlib import Path

APP_SRC = Path(__file__).resolve().parents[1] / "apps" / "fedctl_research" / "src"
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from fedctl_research.netem_probe import collect_netem_probe_metrics, netem_payload_from_metrics, parse_qdisc_metrics


def test_parse_qdisc_metrics_extracts_netem_and_tbf_values() -> None:
    text = "\n".join(
        [
            "qdisc tbf 1: root refcnt 2 rate 50Mbit burst 256Kb lat 50ms",
            "qdisc netem 10: parent 1:1 limit 1000 delay 60ms 15ms loss 0.5%",
        ]
    )

    metrics = parse_qdisc_metrics(text, prefix="netem-egress")

    assert metrics["netem-egress-has-netem"] == 1
    assert metrics["netem-egress-has-tbf"] == 1
    assert metrics["netem-egress-delay-ms"] == 60.0
    assert metrics["netem-egress-jitter-ms"] == 15.0
    assert metrics["netem-egress-loss-pct"] == 0.5
    assert metrics["netem-egress-rate-mbit"] == 50.0


def test_parse_qdisc_metrics_converts_kbit_rate_to_mbit() -> None:
    metrics = parse_qdisc_metrics(
        "qdisc tbf 1: root rate 500Kbit burst 32Kb lat 50ms",
        prefix="netem-ingress",
    )

    assert metrics["netem-ingress-has-tbf"] == 1
    assert metrics["netem-ingress-rate-mbit"] == 0.5


def test_netem_payload_from_metrics_keeps_numeric_netem_keys_only() -> None:
    payload = netem_payload_from_metrics(
        {
            "netem-probe-ok": 1,
            "netem-egress-delay-ms": 20.0,
            "netem-profile": "mild",
            "train-loss": 0.3,
        }
    )

    assert payload == {
        "netem_probe_ok": 1,
        "netem_egress_delay_ms": 20.0,
    }


def test_collect_netem_probe_metrics_is_empty_without_netem_env(monkeypatch) -> None:
    collect_netem_probe_metrics.cache_clear()
    for key in list(__import__("os").environ):
        if key == "NET_PROFILE" or key.startswith("NET_INGRESS_") or key.startswith("NET_"):
            monkeypatch.delenv(key, raising=False)

    assert collect_netem_probe_metrics() == {}
