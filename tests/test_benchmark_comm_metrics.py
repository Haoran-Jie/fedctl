from __future__ import annotations

from fedctl.benchmark.comm_metrics import (
    evaluate_ins_proto_bytes,
    evaluate_res_proto_bytes,
    fit_ins_proto_bytes,
    fit_res_proto_bytes,
    model_payload_bytes,
)
from flwr.common import EvaluateIns, EvaluateRes, FitIns, FitRes, Parameters
from flwr.common.typing import Code, Status


def _params(*sizes: int) -> Parameters:
    return Parameters(tensors=[bytes(size) for size in sizes], tensor_type="bytes")


def test_model_payload_bytes_sums_tensor_sizes() -> None:
    assert model_payload_bytes(_params(3, 7, 11)) == 21
    assert model_payload_bytes(None) == 0


def test_fit_and_evaluate_proto_sizes_are_positive() -> None:
    fit_ins = FitIns(parameters=_params(16, 32), config={"round": 1})
    fit_res = FitRes(
        status=Status(code=Code.OK, message=""),
        parameters=_params(64),
        num_examples=10,
        metrics={"train_time_s": 0.1},
    )
    eval_ins = EvaluateIns(parameters=_params(16, 32), config={"round": 1})
    eval_res = EvaluateRes(
        status=Status(code=Code.OK, message=""),
        loss=0.5,
        num_examples=10,
        metrics={"eval_time_s": 0.05},
    )

    assert fit_ins_proto_bytes(fit_ins) > 0
    assert fit_res_proto_bytes(fit_res) > 0
    assert evaluate_ins_proto_bytes(eval_ins) > 0
    assert evaluate_res_proto_bytes(eval_res) > 0


def test_proto_size_reflects_payload_growth() -> None:
    small = FitIns(parameters=_params(8), config={})
    large = FitIns(parameters=_params(8, 1024), config={})
    assert fit_ins_proto_bytes(large) > fit_ins_proto_bytes(small)

