from __future__ import annotations

import json
from pathlib import Path

from fedctl.benchmark.parse_submit_logs import (
    parse_benchmark_dir,
    parse_benchmark_dir_extended,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_parse_benchmark_dir_outputs_tables(tmp_path: Path) -> None:
    run_dir = tmp_path / "raw" / "S2_med_all" / "r1"
    submission = {
        "id": "sub-123",
        "status": "completed",
        "started_at": "2026-02-27T10:00:00+00:00",
        "finished_at": "2026-02-27T10:05:00+00:00",
        "args": [
            "-m",
            "fedctl.submit.runner",
            "--num-supernodes",
            "2",
            "--net",
            "[1]=med,[2]=(low,high)",
        ],
    }
    _write(run_dir / "submission.json", json.dumps(submission))
    _write(
        run_dir / "submit.stdout.log",
        "\n".join(
            [
                "[round 1] fit_phase_time_s=2.1000",
                "[round 1] eval_phase_time_s=0.5000",
                "[round 1] round_end_to_end_time_s=2.6000",
                '[comm-json] {"round":1,"phase":"fit","direction":"downlink","client_id":"c1","bytes_proto":123,"bytes_model_payload":64,"timestamp_s":1.1}',
                '[comm-json] {"round":1,"phase":"fit","direction":"uplink","client_id":"c1","bytes_proto":80,"bytes_model_payload":64,"timestamp_s":1.3}',
            ]
        ),
    )
    _write(
        run_dir / "supernodes.supernode-1.stdout.log",
        "qdisc tbf 1: root refcnt 2 rate 20Mbit burst 256Kb lat 50.0ms\n"
        "qdisc netem 10: parent 1:1 limit 1000 delay 120ms 25ms loss 2.5%\n",
    )

    runs, round_timing, round_comm, qdisc = parse_benchmark_dir(tmp_path)

    assert len(runs) == 1
    assert runs[0]["scenario"] == "S2_med_all"
    assert runs[0]["e2e_runtime_s"] == 300.0
    assert runs[0]["total_bytes_proto"] == 203

    assert len(round_timing) == 1
    assert round_timing[0]["round"] == 1
    assert round_timing[0]["fit_phase_time_s"] == 2.1
    assert round_timing[0]["eval_phase_time_s"] == 0.5

    assert len(round_comm) == 2
    assert {row["direction"] for row in round_comm} == {"downlink", "uplink"}

    assert qdisc
    assert qdisc[0]["task"] == "supernode-1"
    assert qdisc[0]["verification_source"] == "raw_qdisc"


def test_parse_benchmark_dir_extended_parses_msgbench(tmp_path: Path) -> None:
    run_dir = tmp_path / "raw" / "S_msgbench" / "r1"
    submission = {
        "id": "sub-msgbench-1",
        "status": "completed",
        "started_at": "2026-02-27T10:00:00+00:00",
        "finished_at": "2026-02-27T10:00:10+00:00",
        "args": ["-m", "fedctl.submit.runner", "--num-supernodes", "1"],
    }
    _write(run_dir / "submission.json", json.dumps(submission))
    _write(run_dir / "submit.stdout.log", "submit wrapper header\n")
    _write(
        run_dir / "superexec_serverapp.stdout.log",
        '[msgbench-json] {"round":1,"fanout_requested":3,"fanout_actual":2,'
        '"replies_received":2,"request_bytes":65536,"reply_bytes":1048576,'
        '"request_total_bytes":131072,"reply_total_bytes":2097152,'
        '"latency_s":1.25,"goodput_bps":1780000.0,"target_mode":"fixed",'
        '"selected_nodes":[1001,1002],"timestamp_s":1700000000.0}\n',
    )

    runs, round_timing, round_comm, qdisc, msgbench = parse_benchmark_dir_extended(tmp_path)

    assert len(runs) == 1
    assert runs[0]["scenario"] == "S_msgbench"
    assert runs[0]["total_downlink_bytes_proto"] == 131072
    assert runs[0]["total_uplink_bytes_proto"] == 2097152
    assert runs[0]["total_bytes_proto"] == 2228224
    assert runs[0]["round_count"] == 1

    assert round_timing == []
    assert round_comm == []
    assert qdisc == []

    assert len(msgbench) == 1
    row = msgbench[0]
    assert row["source_log"] == "superexec_serverapp.stdout.log"
    assert row["round"] == 1
    assert row["fanout_requested"] == 3
    assert row["fanout_actual"] == 2
    assert row["request_total_bytes"] == 131072
    assert row["reply_total_bytes"] == 2097152
    assert row["total_bytes"] == 2228224
    assert row["selected_nodes_json"] == "[1001,1002]"


def test_parse_benchmark_dir_extended_parses_wrapped_msgbench(tmp_path: Path) -> None:
    run_dir = tmp_path / "raw" / "S_msgbench_wrapped" / "r1"
    submission = {
        "id": "sub-msgbench-wrap-1",
        "status": "completed",
        "started_at": "2026-02-27T10:00:00+00:00",
        "finished_at": "2026-02-27T10:00:12+00:00",
        "args": ["-m", "fedctl.submit.runner", "--num-supernodes", "1"],
    }
    _write(run_dir / "submission.json", json.dumps(submission))
    _write(
        run_dir / "submit.stdout.log",
        "\n".join(
            [
                "submit wrapper header",
                "[msgbench-json] ",
                '{"round":1,"fanout_requested":1,"fanout_actual":1,"replies_received":1,'
                '"request_bytes":65536,"reply_bytes":65536,'
                '"request_total_bytes":65536,"reply_total_bytes":65536,'
                '"latency_s":21.0,"goodput_bps":6231.7,'
                '"target_mode":"fixed","selected_nodes":[6329075323605005275],'
                '"timestamp_s":1772210105.27}',
            ]
        ),
    )
    _write(
        run_dir / "superexec_serverapp.stdout.log",
        "\n".join(
            [
                "[msgbench-json] ",
                '{"round":1,"fanout_requested":1,"fanout_actual":1,"replies_received":1,'
                '"request_bytes":65536,"reply_bytes":65536,'
                '"request_total_bytes":65536,"reply_total_bytes":65536,'
                '"latency_s":21.0,"goodput_bps":6231.7,'
                '"target_mode":"fixed","selected_nodes":[6329075323605005275],'
                '"timestamp_s":1772210105.27}',
                "",
            ]
        ),
    )

    runs, _round_timing, _round_comm, _qdisc, msgbench = parse_benchmark_dir_extended(
        tmp_path
    )

    assert len(runs) == 1
    assert runs[0]["total_downlink_bytes_proto"] == 65536
    assert runs[0]["total_uplink_bytes_proto"] == 65536
    assert runs[0]["total_bytes_proto"] == 131072

    assert len(msgbench) == 1
    assert msgbench[0]["round"] == 1
    assert msgbench[0]["request_total_bytes"] == 65536
    assert msgbench[0]["reply_total_bytes"] == 65536
    assert msgbench[0]["source_log"] == "superexec_serverapp.stdout.log"


def test_parse_benchmark_dir_prefers_structured_netem_verification_rows(tmp_path: Path) -> None:
    run_dir = tmp_path / "raw" / "S_netem_json" / "r1"
    submission = {
        "id": "sub-netem-1",
        "status": "completed",
        "started_at": "2026-02-27T10:00:00+00:00",
        "finished_at": "2026-02-27T10:02:00+00:00",
        "args": ["-m", "fedctl.submit.runner", "--num-supernodes", "1"],
    }
    _write(run_dir / "submission.json", json.dumps(submission))
    _write(run_dir / "submit.stdout.log", "submit wrapper header\n")
    _write(
        run_dir / "supernodes.supernode-1.stdout.log",
        "\n".join(
            [
                '[netem-json] {"event":"verify","direction":"egress","iface":"eth0","source_iface":"eth0","enabled":true,"observed_profile":"mild","expected_egress_profile":"mild","expected_ingress_profile":"none","delay_ms_expected":20.0,"jitter_ms_expected":5.0,"loss_pct_expected":1.5,"rate_mbit_expected":50.0,"qdisc_applied":true,"delay_ms_applied":20.0,"jitter_ms_applied":5.0,"loss_pct_applied":1.5,"rate_mbit_applied":50.0,"raw_lines":["qdisc tbf 1: root refcnt 2 rate 50Mbit burst 32Kb lat 400.0ms","qdisc netem 10: parent 1:1 limit 1000 delay 20ms 5ms loss 1.5%"]}',
                '[netem-json] {"event":"verify","direction":"ingress","iface":"ifb0","source_iface":"eth0","enabled":false,"observed_profile":"none","expected_egress_profile":"mild","expected_ingress_profile":"none","delay_ms_expected":null,"jitter_ms_expected":null,"loss_pct_expected":null,"rate_mbit_expected":null,"qdisc_applied":false,"delay_ms_applied":null,"jitter_ms_applied":null,"loss_pct_applied":null,"rate_mbit_applied":null,"raw_lines":[]}',
                "qdisc netem 10: parent 1:1 limit 1000 delay 999ms 999ms loss 99%",
            ]
        ),
    )

    _runs, _round_timing, _round_comm, qdisc = parse_benchmark_dir(tmp_path)

    assert len(qdisc) == 2
    egress = next(row for row in qdisc if row["direction"] == "egress")
    ingress = next(row for row in qdisc if row["direction"] == "ingress")
    assert egress["verification_source"] == "netem_json"
    assert egress["observed_profile"] == "mild"
    assert egress["iface"] == "eth0"
    assert egress["rate_mbit_expected"] == 50.0
    assert egress["rate_mbit_applied"] == 50.0
    assert egress["expected_egress_profile"] == "mild"
    assert "qdisc tbf 1: root" in egress["raw_line"]
    assert ingress["verification_source"] == "netem_json"
    assert ingress["enabled"] is False
    assert ingress["qdisc_applied"] is False
