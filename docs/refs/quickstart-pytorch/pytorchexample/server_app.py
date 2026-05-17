"""pytorchexample: A Flower / PyTorch app."""

import io
import json
import time
from collections.abc import Iterable
from logging import INFO

import torch
from flwr.app import ArrayRecord, ConfigRecord, Context, MetricRecord
from flwr.common import Message, log
from flwr.common.serde import message_to_proto
from flwr.serverapp import Grid, ServerApp
from flwr.serverapp.strategy import FedAvg
from flwr.serverapp.strategy.result import Result
from flwr.serverapp.strategy.strategy_utils import log_strategy_start_info

from pytorchexample.task import Net, load_centralized_dataset, test

# Create ServerApp
app = ServerApp()


class TimedFedAvg(FedAvg):
    """FedAvg strategy with granular timing and communication logging."""

    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    def start(
        self,
        grid: Grid,
        initial_arrays: ArrayRecord,
        num_rounds: int = 3,
        timeout: float = 3600,
        train_config: ConfigRecord | None = None,
        evaluate_config: ConfigRecord | None = None,
        evaluate_fn=None,
    ) -> Result:
        """Execute strategy with granular phase timing and comm logs."""
        log(INFO, "Starting %s strategy:", self.__class__.__name__)
        log_strategy_start_info(num_rounds, initial_arrays, train_config, evaluate_config)
        self.summary()
        log(INFO, "")

        train_config = ConfigRecord() if train_config is None else train_config
        evaluate_config = ConfigRecord() if evaluate_config is None else evaluate_config
        result = Result()
        arrays = initial_arrays
        t_start = time.time()

        if evaluate_fn:
            eval0 = evaluate_fn(0, initial_arrays)
            log(INFO, "Initial global evaluation results: %s", eval0)
            if eval0 is not None:
                result.evaluate_metrics_serverapp[0] = eval0

        for current_round in range(1, num_rounds + 1):
            round_start = time.perf_counter()
            log(INFO, "")
            log(INFO, "[ROUND %s/%s]", current_round, num_rounds)

            # --- TRAINING ---
            t0 = time.perf_counter()
            train_messages = list(
                self.configure_train(current_round, arrays, train_config, grid)
            )
            t_config_train = time.perf_counter() - t0

            ts = time.time()
            for msg in train_messages:
                _emit_comm_json(
                    round_idx=current_round,
                    phase="fit",
                    direction="downlink",
                    client_id=str(msg.metadata.dst_node_id),
                    bytes_proto=len(message_to_proto(msg).SerializeToString()),
                    bytes_model_payload=_model_payload_bytes(msg),
                    timestamp_s=ts,
                )

            t0 = time.perf_counter()
            train_replies = list(grid.send_and_receive(messages=train_messages, timeout=timeout))
            t_send_recv_train = time.perf_counter() - t0

            ts = time.time()
            for reply in train_replies:
                if reply.has_error():
                    continue
                _emit_comm_json(
                    round_idx=current_round,
                    phase="fit",
                    direction="uplink",
                    client_id=str(reply.metadata.src_node_id),
                    bytes_proto=len(message_to_proto(reply).SerializeToString()),
                    bytes_model_payload=_model_payload_bytes(reply),
                    timestamp_s=ts,
                )

            t0 = time.perf_counter()
            agg_arrays, agg_train_metrics = self.aggregate_train(current_round, train_replies)
            t_aggregate_train = time.perf_counter() - t0
            fit_phase = t_config_train + t_send_recv_train + t_aggregate_train

            if agg_arrays is not None:
                result.arrays = agg_arrays
                arrays = agg_arrays
            if agg_train_metrics is not None:
                log(INFO, "\t└──> Aggregated MetricRecord: %s", agg_train_metrics)
                result.train_metrics_clientapp[current_round] = agg_train_metrics

            # --- EVALUATION (CLIENTAPP) ---
            t_config_eval = 0.0
            t_send_recv_eval = 0.0
            t_aggregate_eval = 0.0

            t0 = time.perf_counter()
            evaluate_messages = list(
                self.configure_evaluate(current_round, arrays, evaluate_config, grid)
            )
            t_config_eval = time.perf_counter() - t0

            ts = time.time()
            for msg in evaluate_messages:
                _emit_comm_json(
                    round_idx=current_round,
                    phase="evaluate",
                    direction="downlink",
                    client_id=str(msg.metadata.dst_node_id),
                    bytes_proto=len(message_to_proto(msg).SerializeToString()),
                    bytes_model_payload=_model_payload_bytes(msg),
                    timestamp_s=ts,
                )

            t0 = time.perf_counter()
            evaluate_replies = list(
                grid.send_and_receive(messages=evaluate_messages, timeout=timeout)
            )
            t_send_recv_eval = time.perf_counter() - t0

            ts = time.time()
            for reply in evaluate_replies:
                if reply.has_error():
                    continue
                _emit_comm_json(
                    round_idx=current_round,
                    phase="evaluate",
                    direction="uplink",
                    client_id=str(reply.metadata.src_node_id),
                    bytes_proto=len(message_to_proto(reply).SerializeToString()),
                    bytes_model_payload=0,
                    timestamp_s=ts,
                )

            t0 = time.perf_counter()
            agg_evaluate_metrics = self.aggregate_evaluate(current_round, evaluate_replies)
            t_aggregate_eval = time.perf_counter() - t0
            eval_phase = t_config_eval + t_send_recv_eval + t_aggregate_eval

            if agg_evaluate_metrics is not None:
                log(INFO, "\t└──> Aggregated MetricRecord: %s", agg_evaluate_metrics)
                result.evaluate_metrics_clientapp[current_round] = agg_evaluate_metrics

            # --- EVALUATION (SERVERAPP) ---
            t_server_eval = 0.0
            if evaluate_fn:
                log(INFO, "Global evaluation")
                t0 = time.perf_counter()
                server_eval = evaluate_fn(current_round, arrays)
                t_server_eval = time.perf_counter() - t0
                log(INFO, "\t└──> MetricRecord: %s", server_eval)
                if server_eval is not None:
                    result.evaluate_metrics_serverapp[current_round] = server_eval

            round_total = time.perf_counter() - round_start

            # Parse-friendly summary lines used by benchmark parser
            print(f"[round {current_round}] fit_phase_time_s={fit_phase:.4f}")
            print(f"[round {current_round}] eval_phase_time_s={eval_phase:.4f}")
            print(f"[round {current_round}] total_time_s={round_total:.4f}")
            print(f"[round {current_round}] round_end_to_end_time_s={round_total:.4f}")

            # More granular breakdown
            print(f"[round {current_round}] configure_train_time_s={t_config_train:.4f}")
            print(f"[round {current_round}] train_send_receive_time_s={t_send_recv_train:.4f}")
            print(f"[round {current_round}] aggregate_train_time_s={t_aggregate_train:.4f}")
            print(f"[round {current_round}] configure_evaluate_time_s={t_config_eval:.4f}")
            print(f"[round {current_round}] evaluate_send_receive_time_s={t_send_recv_eval:.4f}")
            print(f"[round {current_round}] aggregate_evaluate_time_s={t_aggregate_eval:.4f}")
            print(f"[round {current_round}] server_eval_time_s={t_server_eval:.4f}")

        log(INFO, "")
        log(INFO, "Strategy execution finished in %.2fs", time.time() - t_start)
        log(INFO, "")
        log(INFO, "Final results:")
        log(INFO, "")
        for line in io.StringIO(str(result)):
            log(INFO, "\t%s", line.strip("\n"))
        log(INFO, "")
        return result


@app.main()
def main(grid: Grid, context: Context) -> None:
    """Main entry point for the ServerApp."""

    # Read run config
    fraction_evaluate: float = context.run_config["fraction-evaluate"]
    num_rounds: int = context.run_config["num-server-rounds"]
    lr: float = context.run_config["learning-rate"]

    # Load global model
    global_model = Net()
    arrays = ArrayRecord(global_model.state_dict())

    # Initialize FedAvg strategy
    strategy = TimedFedAvg(fraction_evaluate=fraction_evaluate)

    # Start strategy, run FedAvg for `num_rounds`
    result = strategy.start(
        grid=grid,
        initial_arrays=arrays,
        train_config=ConfigRecord({"lr": lr}),
        num_rounds=num_rounds,
        evaluate_fn=global_evaluate,
    )

    # Save final model to disk
    print("\nSaving final model to disk...")
    state_dict = result.arrays.to_torch_state_dict()
    torch.save(state_dict, "final_model.pt")


def global_evaluate(server_round: int, arrays: ArrayRecord) -> MetricRecord:
    """Evaluate model on central data."""

    # Load the model and initialize it with the received weights
    model = Net()
    model.load_state_dict(arrays.to_torch_state_dict())
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    model.to(device)

    # Load entire test set
    test_dataloader = load_centralized_dataset()

    # Evaluate the global model on the test set
    test_loss, test_acc = test(model, test_dataloader, device)

    # Return the evaluation metrics
    return MetricRecord({"accuracy": test_acc, "loss": test_loss})


def _model_payload_bytes(msg: Message) -> int:
    if msg.has_error():
        return 0
    arrays = msg.content.get("arrays")
    if not isinstance(arrays, ArrayRecord):
        return 0
    return arrays.count_bytes()


def _emit_comm_json(
    *,
    round_idx: int,
    phase: str,
    direction: str,
    client_id: str,
    bytes_proto: int,
    bytes_model_payload: int,
    timestamp_s: float,
) -> None:
    payload = {
        "round": round_idx,
        "phase": phase,
        "direction": direction,
        "client_id": client_id,
        "bytes_proto": bytes_proto,
        "bytes_model_payload": bytes_model_payload,
        "timestamp_s": timestamp_s,
    }
    print(f"[comm-json] {json.dumps(payload, separators=(',', ':'))}")
