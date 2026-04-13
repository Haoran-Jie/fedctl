"""Generic Flower ClientApp that dispatches by method."""

from __future__ import annotations

from flwr.app import Context, Message
from flwr.clientapp import ClientApp

from fedctl_research.config import get_method_name
from fedctl_research.methods.registry import resolve_method

app = ClientApp()


@app.query()
def query_app(msg: Message, context: Context) -> Message:
    method = resolve_method(get_method_name(context.run_config))
    return method.query_app(msg, context)


@app.train()
def train_app(msg: Message, context: Context) -> Message:
    method = resolve_method(get_method_name(context.run_config))
    return method.train_app(msg, context)


@app.evaluate()
def evaluate_app(msg: Message, context: Context) -> Message:
    method = resolve_method(get_method_name(context.run_config))
    return method.evaluate_app(msg, context)

