"""FedRolex-style strategy with rolling submodel extraction."""

from __future__ import annotations

from flwr.app import Message

from fedctl_research.methods.heterofl.strategy import HeteroFLStrategy

from .slicing import build_rolling_param_indices_for_rate


class FedRolex(HeteroFLStrategy):
    """FedRolex with rolling submodel extraction and unweighted selective averaging."""

    def __init__(
        self,
        *,
        roll_mode: str = "paper",
        overlap: float | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.roll_mode = roll_mode
        self.overlap = overlap

    def build_param_indices(self, global_state, *, model_rate: float, server_round: int):
        return build_rolling_param_indices_for_rate(
            global_state,
            model_rate,
            server_round=server_round,
            global_model_rate=self.global_model_rate,
            roll_mode=self.roll_mode,
            overlap=self.overlap,
        )

    def weight_for_local_update(self, message: Message) -> float:
        del message
        return 1.0
