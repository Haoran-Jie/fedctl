from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fedctl.deploy.network import assignment_key, parse_net_assignments
from fedctl.deploy.plan import SupernodePlacement, parse_supernodes

COMM_PREFIX = "[comm-json]"
MSGBENCH_PREFIX = "[msgbench-json]"
ROUND_TIMING_RE = re.compile(
    r"^\[round\s+(?P<round>\d+)\]\s+"
    r"(?P<metric>fit_phase_time_s|eval_phase_time_s|round_end_to_end_time_s|total_time_s)"
    r"=(?P<value>[0-9.]+)\s*$"
)
QDISC_LINE_RE = re.compile(r"\bqdisc\b.*\b(netem|tbf)\b")
DELAY_RE = re.compile(r"\bdelay\s+([0-9.]+)ms(?:\s+([0-9.]+)ms)?")
LOSS_RE = re.compile(r"\bloss\s+([0-9.]+)%")
RATE_RE = re.compile(r"\brate\s+([0-9.]+)\s*([KMG])bit", re.IGNORECASE)
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


@dataclass(frozen=True)
class RunContext:
    scenario: str
    replicate: str
    submission_id: str


def parse_benchmark_dir(
    input_root: Path,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    runs, round_timing, round_comm, qdisc, _msgbench = parse_benchmark_dir_extended(
        input_root
    )
    return runs, round_timing, round_comm, qdisc


def parse_benchmark_dir_extended(
    input_root: Path,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    raw_root = input_root / "raw" if (input_root / "raw").exists() else input_root
    runs: list[dict[str, Any]] = []
    round_timing: list[dict[str, Any]] = []
    round_comm: list[dict[str, Any]] = []
    qdisc: list[dict[str, Any]] = []
    msgbench: list[dict[str, Any]] = []

    if not raw_root.exists():
        return runs, round_timing, round_comm, qdisc, msgbench

    for scenario_dir in sorted(p for p in raw_root.iterdir() if p.is_dir()):
        for replicate_dir in sorted(p for p in scenario_dir.iterdir() if p.is_dir()):
            run_rows, timing_rows, comm_rows, qdisc_rows, msgbench_rows = _parse_run_dir(
                scenario_dir.name,
                replicate_dir.name,
                replicate_dir,
            )
            runs.extend(run_rows)
            round_timing.extend(timing_rows)
            round_comm.extend(comm_rows)
            qdisc.extend(qdisc_rows)
            msgbench.extend(msgbench_rows)
    return runs, round_timing, round_comm, qdisc, msgbench


def _parse_run_dir(
    scenario: str,
    replicate: str,
    run_dir: Path,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    submission = _load_submission(run_dir / "submission.json")
    submission_id = str(submission.get("submission_id") or submission.get("id") or "")
    ctx = RunContext(
        scenario=scenario,
        replicate=replicate,
        submission_id=submission_id,
    )

    submit_log = run_dir / "submit.stdout.log"
    timing_rows, comm_rows = _parse_submit_log(ctx, submit_log)
    msgbench_rows = _parse_msgbench_logs(ctx, run_dir)
    run_row = _build_run_row(ctx, submission, timing_rows, comm_rows, msgbench_rows)
    qdisc_rows = _parse_qdisc_rows(ctx, run_dir, submission)

    runs = [run_row] if run_row else []
    return runs, timing_rows, comm_rows, qdisc_rows, msgbench_rows


def _load_submission(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_submit_log(
    ctx: RunContext,
    path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not path.exists():
        return [], []

    timing_by_round: dict[int, dict[str, Any]] = {}
    comm_rows: list[dict[str, Any]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    idx = 0
    while idx < len(lines):
        clean = _clean_log_line(lines[idx]).strip()
        timing_match = ROUND_TIMING_RE.match(clean)
        if timing_match:
            round_idx = int(timing_match.group("round"))
            metric = timing_match.group("metric")
            value = float(timing_match.group("value"))
            row = timing_by_round.setdefault(
                round_idx,
                {
                    "scenario": ctx.scenario,
                    "replicate": ctx.replicate,
                    "submission_id": ctx.submission_id,
                    "round": round_idx,
                    "fit_phase_time_s": None,
                    "eval_phase_time_s": None,
                    "round_end_to_end_time_s": None,
                    "total_time_s": None,
                },
            )
            row[metric] = value
            idx += 1
            continue

        json_blob, end_idx = _extract_prefixed_json_blob(lines, idx, COMM_PREFIX)
        if json_blob is not None:
            parsed = _parse_comm_line(json_blob)
            if parsed is not None:
                comm_rows.append(
                    {
                        "scenario": ctx.scenario,
                        "replicate": ctx.replicate,
                        "submission_id": ctx.submission_id,
                        **parsed,
                    }
                )
            idx = end_idx + 1
            continue
        idx += 1

    timing_rows = [timing_by_round[k] for k in sorted(timing_by_round)]
    return timing_rows, comm_rows


def _parse_comm_line(blob: str) -> dict[str, Any] | None:
    if not blob:
        return None
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return {
        "round": int(payload.get("round", 0)),
        "phase": str(payload.get("phase", "")),
        "direction": str(payload.get("direction", "")),
        "client_id": str(payload.get("client_id", "")),
        "bytes_proto": int(payload.get("bytes_proto", 0)),
        "bytes_model_payload": int(payload.get("bytes_model_payload", 0)),
        "timestamp_s": float(payload.get("timestamp_s", 0.0)),
    }


def _build_run_row(
    ctx: RunContext,
    submission: dict[str, Any],
    timing_rows: list[dict[str, Any]],
    comm_rows: list[dict[str, Any]],
    msgbench_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    status = submission.get("status")
    started_at = submission.get("started_at")
    finished_at = submission.get("finished_at")
    e2e_runtime_s = _duration_s(started_at, finished_at)
    if comm_rows:
        total_uplink = sum(
            row["bytes_proto"] for row in comm_rows if row.get("direction") == "uplink"
        )
        total_downlink = sum(
            row["bytes_proto"] for row in comm_rows if row.get("direction") == "downlink"
        )
    else:
        total_uplink = sum(row.get("reply_total_bytes", 0) for row in msgbench_rows)
        total_downlink = sum(row.get("request_total_bytes", 0) for row in msgbench_rows)

    timing_rounds = {row["round"] for row in timing_rows}
    msgbench_rounds = {
        int(row.get("round", 0))
        for row in msgbench_rows
        if isinstance(row.get("round"), int)
    }
    round_count = len(timing_rounds | msgbench_rounds)

    return {
        "scenario": ctx.scenario,
        "replicate": ctx.replicate,
        "submission_id": ctx.submission_id,
        "status": status or "",
        "e2e_runtime_s": e2e_runtime_s,
        "total_uplink_bytes_proto": total_uplink,
        "total_downlink_bytes_proto": total_downlink,
        "total_bytes_proto": total_uplink + total_downlink,
        "round_count": round_count,
    }


def _duration_s(started_at: Any, finished_at: Any) -> float | None:
    if not isinstance(started_at, str) or not isinstance(finished_at, str):
        return None
    try:
        start = _parse_iso(started_at)
        end = _parse_iso(finished_at)
    except ValueError:
        return None
    return max(0.0, (end - start).total_seconds())


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_qdisc_rows(
    ctx: RunContext,
    run_dir: Path,
    submission: dict[str, Any],
) -> list[dict[str, Any]]:
    expected = _expected_profiles(submission)
    rows: list[dict[str, Any]] = []
    for path in sorted(run_dir.glob("supernodes.*.log")):
        task = _task_from_filename(path.name)
        if not task:
            continue
        expected_ingress = expected.get(task, {}).get("ingress_profile")
        expected_egress = expected.get(task, {}).get("egress_profile")
        stream = "stderr" if ".stderr." in path.name else "stdout"
        for line in path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_qdisc_line(line)
            if not parsed:
                continue
            rows.append(
                {
                    "scenario": ctx.scenario,
                    "replicate": ctx.replicate,
                    "submission_id": ctx.submission_id,
                    "task": task,
                    "stream": stream,
                    "direction": parsed["direction"],
                    "qdisc_applied": True,
                    "delay_ms_applied": parsed["delay_ms"],
                    "jitter_ms_applied": parsed["jitter_ms"],
                    "loss_pct_applied": parsed["loss_pct"],
                    "rate_mbit_applied": parsed["rate_mbit"],
                    "expected_ingress_profile": expected_ingress,
                    "expected_egress_profile": expected_egress,
                    "raw_line": line.strip(),
                }
            )
    return rows


def _parse_msgbench_logs(ctx: RunContext, run_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    log_files = _iter_msgbench_log_files(run_dir)
    seen: set[tuple[Any, ...]] = set()
    for path in log_files:
        lines = path.read_text(encoding="utf-8").splitlines()
        idx = 0
        while idx < len(lines):
            json_blob, end_idx = _extract_prefixed_json_blob(
                lines, idx, MSGBENCH_PREFIX
            )
            if json_blob is None:
                idx += 1
                continue
            parsed = _parse_msgbench_line(json_blob)
            if parsed is None:
                idx = end_idx + 1
                continue
            fingerprint = (
                parsed.get("round"),
                parsed.get("fanout_requested"),
                parsed.get("fanout_actual"),
                parsed.get("replies_received"),
                parsed.get("request_total_bytes"),
                parsed.get("reply_total_bytes"),
                parsed.get("latency_s"),
                parsed.get("goodput_bps"),
                parsed.get("target_mode"),
                parsed.get("selected_nodes_json"),
                parsed.get("timestamp_s"),
            )
            if fingerprint not in seen:
                rows.append(
                    {
                        "scenario": ctx.scenario,
                        "replicate": ctx.replicate,
                        "submission_id": ctx.submission_id,
                        "source_log": path.name,
                        **parsed,
                    }
                )
                seen.add(fingerprint)
            idx = end_idx + 1
    return rows


def _iter_log_files(run_dir: Path) -> list[Path]:
    return sorted(p for p in run_dir.glob("*.log") if p.is_file())


def _iter_msgbench_log_files(run_dir: Path) -> list[Path]:
    files = _iter_log_files(run_dir)
    preferred = [p for p in files if "superexec_serverapp" in p.name]
    return preferred if preferred else files


def _extract_prefixed_json_blob(
    lines: list[str],
    start_idx: int,
    prefix: str,
) -> tuple[str | None, int]:
    """Extract JSON following a log prefix, tolerating wrapped/multiline output."""
    head = _clean_log_line(lines[start_idx]).strip()
    if prefix not in head:
        return None, start_idx

    _, _, tail = head.partition(prefix)
    tail = tail.strip()
    if tail:
        parsed, end_idx = _collect_json_blob(lines, start_idx, initial=tail)
        if parsed is not None:
            return parsed, end_idx

    parsed, end_idx = _collect_json_blob(lines, start_idx + 1, initial="")
    return parsed, end_idx


def _collect_json_blob(
    lines: list[str],
    start_idx: int,
    *,
    initial: str,
) -> tuple[str | None, int]:
    if start_idx >= len(lines):
        return None, max(start_idx - 1, 0)

    parts: list[str] = []
    depth = 0
    started = False
    idx = start_idx

    if initial:
        parts.append(initial)
        depth += initial.count("{") - initial.count("}")
        started = "{" in initial
        if started and depth <= 0:
            candidate = "".join(parts).strip()
            if _json_is_object(candidate):
                return candidate, start_idx

    while idx < len(lines):
        current = _clean_log_line(lines[idx]).strip()
        if not current:
            idx += 1
            continue
        if not started:
            if not current.startswith("{"):
                idx += 1
                continue
            started = True
        parts.append(current)
        depth += current.count("{") - current.count("}")
        if started and depth <= 0:
            candidate = "".join(parts).strip()
            if _json_is_object(candidate):
                return candidate, idx
        idx += 1

    return None, max(start_idx - 1, 0)


def _clean_log_line(value: str) -> str:
    return ANSI_ESCAPE_RE.sub("", value)


def _json_is_object(blob: str) -> bool:
    if not blob or not blob.startswith("{"):
        return False
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict)


def _parse_msgbench_line(blob: str) -> dict[str, Any] | None:
    if not blob:
        return None
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    selected_nodes = payload.get("selected_nodes")
    clean_nodes: list[int] = []
    if isinstance(selected_nodes, list):
        for node in selected_nodes:
            node_id = _as_int(node)
            if node_id is not None:
                clean_nodes.append(node_id)

    request_total = _as_int(payload.get("request_total_bytes")) or 0
    reply_total = _as_int(payload.get("reply_total_bytes")) or 0
    return {
        "round": _as_int(payload.get("round")) or 0,
        "fanout_requested": _as_int(payload.get("fanout_requested")) or 0,
        "fanout_actual": _as_int(payload.get("fanout_actual")) or 0,
        "replies_received": _as_int(payload.get("replies_received")) or 0,
        "request_bytes": _as_int(payload.get("request_bytes")) or 0,
        "reply_bytes": _as_int(payload.get("reply_bytes")) or 0,
        "request_total_bytes": request_total,
        "reply_total_bytes": reply_total,
        "total_bytes": request_total + reply_total,
        "latency_s": _as_float(payload.get("latency_s")) or 0.0,
        "goodput_bps": _as_float(payload.get("goodput_bps")) or 0.0,
        "target_mode": str(payload.get("target_mode", "")),
        "selected_nodes_json": json.dumps(clean_nodes, separators=(",", ":")),
        "timestamp_s": _as_float(payload.get("timestamp_s")) or 0.0,
    }


def _task_from_filename(name: str) -> str | None:
    # Expected shape: supernodes.<task>.stdout.log
    if not name.startswith("supernodes."):
        return None
    parts = name.split(".")
    if len(parts) < 4:
        return None
    return parts[1]


def _parse_qdisc_line(line: str) -> dict[str, Any] | None:
    if not QDISC_LINE_RE.search(line):
        return None
    delay = DELAY_RE.search(line)
    loss = LOSS_RE.search(line)
    rate = RATE_RE.search(line)
    direction = "ingress" if "ifb" in line or "ffff:" in line else "egress"
    return {
        "direction": direction,
        "delay_ms": float(delay.group(1)) if delay else None,
        "jitter_ms": float(delay.group(2)) if delay and delay.group(2) else None,
        "loss_pct": float(loss.group(1)) if loss else None,
        "rate_mbit": _to_mbit(rate.group(1), rate.group(2)) if rate else None,
    }


def _to_mbit(value: str, unit: str) -> float:
    number = float(value)
    multiplier = {"K": 0.001, "M": 1.0, "G": 1000.0}
    return number * multiplier[unit.upper()]


def _expected_profiles(submission: dict[str, Any]) -> dict[str, dict[str, str]]:
    args = submission.get("args")
    if not isinstance(args, list):
        return {}

    parsed = _extract_runner_args([str(a) for a in args])
    placements = _placements(parsed["supernodes"], parsed["num_supernodes"])
    ingress: dict[str, list[str]] = {}
    egress: dict[str, list[str]] = {}
    for placement in placements:
        key = assignment_key(placement.device_type)
        size = max(placement.instance_idx, len(egress.get(key, [])))
        ingress.setdefault(key, ["none"] * size)
        egress.setdefault(key, ["none"] * size)
        if len(ingress[key]) < size:
            ingress[key].extend(["none"] * (size - len(ingress[key])))
            egress[key].extend(["none"] * (size - len(egress[key])))

    try:
        assignments = parse_net_assignments(parsed["net"])
    except ValueError:
        assignments = []

    for assignment in assignments:
        key = assignment_key(assignment.device_type)
        if key not in ingress:
            continue
        if assignment.wildcard:
            ingress[key] = [assignment.ingress_profile] * len(ingress[key])
            egress[key] = [assignment.egress_profile] * len(egress[key])
            continue
        if assignment.index is None:
            continue
        idx = assignment.index - 1
        if idx < 0 or idx >= len(ingress[key]):
            continue
        ingress[key][idx] = assignment.ingress_profile
        egress[key][idx] = assignment.egress_profile

    expected: dict[str, dict[str, str]] = {}
    for placement in placements:
        key = assignment_key(placement.device_type)
        task = _supernode_task_name(placement.device_type, placement.instance_idx)
        expected[task] = {
            "ingress_profile": ingress[key][placement.instance_idx - 1],
            "egress_profile": egress[key][placement.instance_idx - 1],
        }
    return expected


def _extract_runner_args(argv: list[str]) -> dict[str, Any]:
    supernodes: list[str] = []
    net: list[str] = []
    num_supernodes = 2
    idx = 0
    while idx < len(argv):
        token = argv[idx]
        if token == "--supernodes" and idx + 1 < len(argv):
            supernodes.append(argv[idx + 1])
            idx += 2
            continue
        if token == "--net" and idx + 1 < len(argv):
            net.append(argv[idx + 1])
            idx += 2
            continue
        if token == "--num-supernodes" and idx + 1 < len(argv):
            try:
                num_supernodes = int(argv[idx + 1])
            except ValueError:
                pass
            idx += 2
            continue
        idx += 1
    return {"supernodes": supernodes, "net": net, "num_supernodes": num_supernodes}


def _placements(supernodes: list[str], num_supernodes: int) -> list[SupernodePlacement]:
    placements: list[SupernodePlacement] = []
    if supernodes:
        counts = parse_supernodes(supernodes)
        for device_type, count in counts.items():
            for instance_idx in range(1, count + 1):
                placements.append(SupernodePlacement(device_type=device_type, instance_idx=instance_idx, node_id=None))
        return placements
    for instance_idx in range(1, max(num_supernodes, 0) + 1):
        placements.append(SupernodePlacement(device_type=None, instance_idx=instance_idx, node_id=None))
    return placements


def _supernode_task_name(device_type: str | None, instance_idx: int) -> str:
    suffix = f"{device_type}-{instance_idx}" if device_type else str(instance_idx)
    return f"supernode-{suffix}"


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in fieldnames})


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse fedctl submit benchmark logs into CSV tables.")
    parser.add_argument("--input", required=True, help="Input root directory (raw/.. or root containing raw/).")
    parser.add_argument("--output", required=True, help="Output directory for parsed CSV files.")
    args = parser.parse_args()

    runs, round_timing, round_comm, qdisc, msgbench = parse_benchmark_dir_extended(
        Path(args.input)
    )
    out = Path(args.output)

    _write_csv(
        out / "runs.csv",
        runs,
        [
            "scenario",
            "replicate",
            "submission_id",
            "status",
            "e2e_runtime_s",
            "total_uplink_bytes_proto",
            "total_downlink_bytes_proto",
            "total_bytes_proto",
            "round_count",
        ],
    )
    _write_csv(
        out / "round_timing.csv",
        round_timing,
        [
            "scenario",
            "replicate",
            "submission_id",
            "round",
            "fit_phase_time_s",
            "eval_phase_time_s",
            "round_end_to_end_time_s",
            "total_time_s",
        ],
    )
    _write_csv(
        out / "round_comm.csv",
        round_comm,
        [
            "scenario",
            "replicate",
            "submission_id",
            "round",
            "phase",
            "direction",
            "client_id",
            "bytes_proto",
            "bytes_model_payload",
            "timestamp_s",
        ],
    )
    _write_csv(
        out / "qdisc.csv",
        qdisc,
        [
            "scenario",
            "replicate",
            "submission_id",
            "task",
            "stream",
            "direction",
            "qdisc_applied",
            "delay_ms_applied",
            "jitter_ms_applied",
            "loss_pct_applied",
            "rate_mbit_applied",
            "expected_ingress_profile",
            "expected_egress_profile",
            "raw_line",
        ],
    )
    _write_csv(
        out / "msgbench.csv",
        msgbench,
        [
            "scenario",
            "replicate",
            "submission_id",
            "source_log",
            "round",
            "fanout_requested",
            "fanout_actual",
            "replies_received",
            "request_bytes",
            "reply_bytes",
            "request_total_bytes",
            "reply_total_bytes",
            "total_bytes",
            "latency_s",
            "goodput_bps",
            "target_mode",
            "selected_nodes_json",
            "timestamp_s",
        ],
    )
    return 0


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


if __name__ == "__main__":
    raise SystemExit(main())
