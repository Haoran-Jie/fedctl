"""msgbench: message-size benchmark ServerApp."""

import json
import random
import time
from logging import INFO

from flwr.app import ConfigRecord, Context, Message, MessageType, RecordDict
from flwr.common.logger import log
from flwr.serverapp import Grid, ServerApp

app = ServerApp()


@app.main()
def main(grid: Grid, context: Context) -> None:
    num_rounds = int(context.run_config.get("num-server-rounds", 1))
    request_bytes = int(context.run_config.get("msgbench-request-bytes", 65536))
    reply_bytes = int(context.run_config.get("msgbench-reply-bytes", request_bytes))
    fanout = int(context.run_config.get("msgbench-fanout", 1))
    target_mode = str(context.run_config.get("msgbench-target-mode", "fixed"))
    timeout_s = float(context.run_config.get("msgbench-timeout-s", 120.0))
    fixed_nodes = _parse_fixed_nodes(context.run_config.get("msgbench-target-node-ids", ""))

    for server_round in range(1, num_rounds + 1):
        all_node_ids: list[int] = []
        while len(all_node_ids) < fanout:
            all_node_ids = list(grid.get_node_ids())
            if len(all_node_ids) < fanout:
                log(INFO, "Waiting for %s nodes, currently %s", fanout, len(all_node_ids))
                time.sleep(2)

        selected_nodes = _select_nodes(
            all_node_ids=all_node_ids,
            fanout=fanout,
            target_mode=target_mode,
            fixed_nodes=fixed_nodes,
            round_idx=server_round,
        )
        messages = [
            Message(
                content=RecordDict(
                    {
                        "msgbench_config": ConfigRecord(
                            {
                                "request_payload": b"x" * request_bytes,
                                "request_bytes": request_bytes,
                                "reply_bytes": reply_bytes,
                                "round": server_round,
                            }
                        )
                    }
                ),
                message_type=MessageType.QUERY,
                dst_node_id=node_id,
                group_id=str(server_round),
            )
            for node_id in selected_nodes
        ]

        started = time.perf_counter()
        replies = list(grid.send_and_receive(messages, timeout=timeout_s))
        elapsed_s = time.perf_counter() - started

        request_total_bytes = request_bytes * len(messages)
        reply_total_bytes = _sum_reply_payload_bytes(replies)
        goodput_bps = (
            (request_total_bytes + reply_total_bytes) / elapsed_s if elapsed_s > 0 else 0.0
        )

        payload = {
            "round": server_round,
            "fanout_requested": fanout,
            "fanout_actual": len(selected_nodes),
            "replies_received": len(replies),
            "request_bytes": request_bytes,
            "reply_bytes": reply_bytes,
            "request_total_bytes": request_total_bytes,
            "reply_total_bytes": reply_total_bytes,
            "latency_s": elapsed_s,
            "goodput_bps": goodput_bps,
            "target_mode": target_mode,
            "selected_nodes": selected_nodes,
            "timestamp_s": time.time(),
        }
        print(f"[msgbench-json] {json.dumps(payload, separators=(',', ':'))}")


def _parse_fixed_nodes(raw: object) -> list[int]:
    if not isinstance(raw, str) or not raw.strip():
        return []
    result: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            result.append(int(token))
        except ValueError:
            continue
    return result


def _select_nodes(
    *,
    all_node_ids: list[int],
    fanout: int,
    target_mode: str,
    fixed_nodes: list[int],
    round_idx: int,
) -> list[int]:
    unique = sorted(set(all_node_ids))
    if target_mode == "fixed" and fixed_nodes:
        selected = [node_id for node_id in fixed_nodes if node_id in unique]
        return selected[:fanout]

    # Deterministic pseudo-random sampling by round for reproducibility.
    rng = random.Random(round_idx)
    if fanout >= len(unique):
        return unique
    return rng.sample(unique, fanout)


def _sum_reply_payload_bytes(replies: list[Message]) -> int:
    total = 0
    for reply in replies:
        if reply.has_error():
            continue
        try:
            result = reply.content["msgbench_result"]
        except KeyError:
            continue
        if not isinstance(result, ConfigRecord):
            continue
        payload = result.get("response_payload")
        if isinstance(payload, bytes):
            total += len(payload)
    return total

