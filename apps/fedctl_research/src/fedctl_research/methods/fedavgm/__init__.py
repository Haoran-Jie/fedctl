"""FedAvgM method implementation using shared task code."""

from __future__ import annotations

from flwr.app import Context, Message
from flwr.serverapp import Grid

from fedctl_research.config import get_fedavgm_momentum, get_float
from fedctl_research.methods.runtime import client_evaluate, client_train, query_capabilities, run_server_loop

from .strategy import FedAvgMStrategy


def _global_model_rate(msg: Message, context: Context) -> float:
    return float(msg.content["config"].get("model-rate", get_float(context.run_config, "global-model-rate")))


def query_app(msg: Message, context: Context) -> Message:
    return query_capabilities(msg, context)


def train_app(msg: Message, context: Context) -> Message:
    return client_train(msg, context, method_label="fedavgm", resolve_model_rate=_global_model_rate)


def evaluate_app(msg: Message, context: Context) -> Message:
    return client_evaluate(msg, context, method_label="fedavgm", resolve_model_rate=_global_model_rate)


def run_server(grid: Grid, context: Context) -> None:
    run_server_loop(
        grid,
        context,
        method_label="fedavgm",
        strategy_factory=FedAvgMStrategy,
        needs_capabilities=True,
        server_momentum=get_fedavgm_momentum(context.run_config),
    )
