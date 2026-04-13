"""Method protocol for dissertation Flower experiments."""

from __future__ import annotations

from typing import Protocol

from flwr.app import Context, Message
from flwr.serverapp import Grid


class MethodModule(Protocol):
    def query_app(self, msg: Message, context: Context) -> Message: ...

    def train_app(self, msg: Message, context: Context) -> Message: ...

    def evaluate_app(self, msg: Message, context: Context) -> Message: ...

    def run_server(self, grid: Grid, context: Context) -> None: ...

