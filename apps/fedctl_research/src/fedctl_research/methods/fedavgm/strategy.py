"""FedAvgM synchronous baseline using Flower's built-in strategy."""

from __future__ import annotations

from flwr.serverapp.strategy import FedAvgM as FlowerFedAvgM

from fedctl_research.methods.fedavg.strategy import SyncLoggingMixin


class FedAvgMStrategy(SyncLoggingMixin, FlowerFedAvgM):
    """FedAvgM with dissertation-specific logging and artifact hooks."""

    pass
