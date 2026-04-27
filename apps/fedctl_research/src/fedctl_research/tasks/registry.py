"""Resolve research tasks by runtime name."""

from __future__ import annotations

from fedctl_research.tasks.base import TaskSpec
from fedctl_research.tasks.appliances_energy.mlp import TASK as APPLIANCES_ENERGY_MLP_TASK
from fedctl_research.tasks.california_housing.mlp import TASK as CALIFORNIA_HOUSING_MLP_TASK
from fedctl_research.tasks.cifar10.cnn import TASK as CIFAR10_CNN_TASK
from fedctl_research.tasks.cifar10.preresnet18 import TASK as CIFAR10_PRERESNET18_TASK
from fedctl_research.tasks.fashion_mnist.cnn import TASK as FASHION_MNIST_CNN_TASK
from fedctl_research.tasks.fashion_mnist.mlp import TASK as FASHION_MNIST_MLP_TASK

_TASKS: dict[str, TaskSpec] = {
    "appliances_energy_mlp": APPLIANCES_ENERGY_MLP_TASK,
    "california_housing_mlp": CALIFORNIA_HOUSING_MLP_TASK,
    "cifar10_cnn": CIFAR10_CNN_TASK,
    "cifar10_preresnet18": CIFAR10_PRERESNET18_TASK,
    "fashion_mnist_cnn": FASHION_MNIST_CNN_TASK,
    "fashion_mnist_mlp": FASHION_MNIST_MLP_TASK,
}


def resolve_task(name: str) -> TaskSpec:
    try:
        return _TASKS[name]
    except KeyError as exc:
        known = ", ".join(sorted(_TASKS))
        raise ValueError(f"Unknown task '{name}'. Known tasks: {known}") from exc
