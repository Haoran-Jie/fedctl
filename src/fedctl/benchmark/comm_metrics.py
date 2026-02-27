from __future__ import annotations

from flwr.common import EvaluateIns, EvaluateRes, FitIns, FitRes, Parameters
from flwr.common.serde import (
    evaluate_ins_to_proto,
    evaluate_res_to_proto,
    fit_ins_to_proto,
    fit_res_to_proto,
)


def model_payload_bytes(parameters: Parameters | None) -> int:
    if parameters is None:
        return 0
    total = 0
    for tensor in parameters.tensors:
        total += len(tensor)
    return total


def fit_ins_proto_bytes(ins: FitIns) -> int:
    return len(fit_ins_to_proto(ins).SerializeToString())


def fit_res_proto_bytes(res: FitRes) -> int:
    return len(fit_res_to_proto(res).SerializeToString())


def evaluate_ins_proto_bytes(ins: EvaluateIns) -> int:
    return len(evaluate_ins_to_proto(ins).SerializeToString())


def evaluate_res_proto_bytes(res: EvaluateRes) -> int:
    return len(evaluate_res_to_proto(res).SerializeToString())

