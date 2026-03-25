# Modern Flower HeteroFL Strategy Skeleton

This note translates the old Flower HeteroFL baseline into the current Flower
framework shape.

It is not intended to be a drop-in implementation. It is the target design for
the experiment app that will run on `fedctl`.

## Target Flower shape

Use the modern Flower Message API:

- `ServerApp` creates the strategy and round configuration
- the custom strategy implements:
  - `configure_train`
  - `aggregate_train`
  - `configure_evaluate`
  - `aggregate_evaluate`
- `ClientApp` handles train/evaluate messages and returns `Message` replies

This matches current Flower framework docs:

- `ServerApp` returns `ServerAppComponents` from `server_fn`
- custom strategies subclass `flwr.serverapp.strategy.Strategy`
- strategy methods operate on `ArrayRecord`, `ConfigRecord`, `MetricRecord`,
  `Message`, and `Grid`

## What to keep from the historical HeteroFL baseline

Keep these ideas from the old implementation:

1. The server decides each client's `model_rate`
2. The server slices the global parameters according to that `model_rate`
3. The client trains only the sliced local model
4. The server aggregates only the parameter entries updated by that client tier

Do **not** carry over:

- old simulation-only `ClientManager` logic
- round-wise random `model_rate` reassignment
- model-specific strategy code mixed with Flower runtime plumbing

## First implementation scope

Use a fixed-rate setup only:

- `rpi4 -> model_rate = 0.5`
- `rpi5 -> model_rate = 1.0`

Read the device type from the env vars injected by `fedctl`:

- `FEDCTL_DEVICE_TYPE`
- `FEDCTL_INSTANCE_IDX`
- `FEDCTL_EXPERIMENT`

## Recommended project structure

The experiment app should look roughly like:

```text
my_heterofl_app/
  heterofl_app/
    __init__.py
    client_app.py
    server_app.py
    task.py
    heterofl_strategy.py
    slicing.py
    config.py
```

Responsibility split:

- `task.py`
  - model definition
  - dataset loading
  - train/eval loops
- `slicing.py`
  - parameter index mapping
  - global-to-local parameter extraction
  - local-to-global masked aggregation helpers
- `heterofl_strategy.py`
  - Flower `Strategy` implementation
- `client_app.py`
  - reads env/config
  - trains one local model slice
- `server_app.py`
  - constructs initial global model
  - wires strategy into `ServerApp`

## Fixed-rate configuration

Use a config block like:

```yaml
heterofl:
  enabled: true
  global_model_rate: 1.0
  fixed_model_rates:
    rpi4: 0.5
    rpi5: 1.0
```

This config belongs to the experiment app, not to `fedctl`.

## Server strategy skeleton

This is the modern shape to implement.

```python
from collections import defaultdict
from typing import Iterable

from flwr.app import ArrayRecord, ConfigRecord, Message, MetricRecord, RecordDict
from flwr.serverapp import Grid
from flwr.serverapp.strategy import Strategy


class FixedRateHeteroFL(Strategy):
    def __init__(
        self,
        *,
        rate_by_node_id: dict[int, float] | None = None,
        global_model_rate: float = 1.0,
        arrayrecord_key: str = "arrays",
        configrecord_key: str = "config",
        weighted_by_key: str = "num-examples",
    ) -> None:
        self.rate_by_node_id = rate_by_node_id or {}
        self.global_model_rate = global_model_rate
        self.arrayrecord_key = arrayrecord_key
        self.configrecord_key = configrecord_key
        self.weighted_by_key = weighted_by_key
        self._active_rate_by_node: dict[int, float] = {}
        self._active_param_idx_by_node: dict[int, dict] = {}

    def summary(self) -> None:
        print("FixedRateHeteroFL")

    def configure_train(
        self,
        server_round: int,
        arrays: ArrayRecord,
        config: ConfigRecord,
        grid: Grid,
    ) -> Iterable[Message]:
        # 1. sample nodes
        # 2. resolve each node's model_rate
        # 3. compute/snapshot parameter indices for that rate
        # 4. slice global arrays into a local subnetwork
        # 5. send local arrays + config to each node
        raise NotImplementedError

    def aggregate_train(
        self,
        server_round: int,
        replies: Iterable[Message],
    ) -> tuple[ArrayRecord | None, MetricRecord | None]:
        # 1. read each reply
        # 2. recover the node's model_rate/param_idx snapshot
        # 3. merge local tensors back into global tensor slots
        # 4. average only across contributing entries
        # 5. aggregate metrics weighted by self.weighted_by_key
        raise NotImplementedError

    def configure_evaluate(
        self,
        server_round: int,
        arrays: ArrayRecord,
        config: ConfigRecord,
        grid: Grid,
    ) -> Iterable[Message]:
        # simplest first version:
        # evaluate the full global model on selected nodes
        raise NotImplementedError

    def aggregate_evaluate(
        self,
        server_round: int,
        replies: Iterable[Message],
    ) -> MetricRecord | None:
        # weighted aggregation of eval metrics
        raise NotImplementedError
```

## ClientApp skeleton

Use `ClientApp` with train/evaluate handlers.

```python
import os

from flwr.app import ArrayRecord, ConfigRecord, Context, Message, MetricRecord, RecordDict
from flwr.clientapp import ClientApp

from .task import build_model_for_rate, load_data, set_model_arrays, train_one_round

app = ClientApp()


def _resolve_device_type() -> str:
    return os.environ.get("FEDCTL_DEVICE_TYPE", "unknown")


def _resolve_model_rate(context: Context) -> float:
    device_type = _resolve_device_type()
    rates = context.run_config["heterofl.fixed_model_rates"]
    if device_type not in rates:
        raise ValueError(f"Unknown device type for fixed-rate HeteroFL: {device_type}")
    return float(rates[device_type])


@app.train()
def train(message: Message, context: Context) -> Message:
    arrays = message.content["arrays"]
    config = message.content["config"]

    model_rate = _resolve_model_rate(context)
    model = build_model_for_rate(model_rate)
    set_model_arrays(model, arrays)

    trainloader = load_data(context=context, split="train")
    num_examples, loss = train_one_round(model, trainloader, config)

    reply = RecordDict(
        {
            "arrays": ArrayRecord(model.state_dict()),
            "metrics": MetricRecord(
                {
                    "num-examples": num_examples,
                    "train-loss": float(loss),
                    "model-rate": float(model_rate),
                }
            ),
        }
    )
    return Message(content=reply, reply_to=message)
```

## Slicing module skeleton

This module should contain the algorithmic HeteroFL logic.

The minimum API should be:

```python
def build_param_idx_for_rate(global_state: dict, model_rate: float, *, global_model_rate: float) -> dict:
    ...


def slice_state_dict(global_state: dict, param_idx: dict) -> dict:
    ...


def merge_local_state_into_global(
    global_state: dict,
    contribution_sum: dict,
    contribution_count: dict,
    local_state: dict,
    param_idx: dict,
) -> None:
    ...
```

For the first implementation:

- support one model family only
- use channel-prefix slicing
- keep the final classifier output dimension fixed

This is directly analogous to the old HeteroFL baseline, which computed
parameter-index mappings and then extracted local parameters based on those
indices.

## Mapping nodes to model rates

Avoid the old simulation-style `ClientManager` mapping.

Use one of these instead:

1. Fixed env-based mapping
   - client reads `FEDCTL_DEVICE_TYPE`
   - server gets node metadata from the `Grid`/message metadata if available
   - if not available, keep the server-side selected-node to rate mapping as part of
     the round configuration

2. Explicit config in train messages
   - server sends `model-rate` in `ConfigRecord`
   - client uses that rate directly

The second option is usually the cleaner first implementation.

Recommended first version:

- server determines `model-rate`
- server sends it in `ConfigRecord`
- client logs both:
  - `FEDCTL_DEVICE_TYPE`
  - `model-rate`

That makes the training trace auditable.

## First milestone

Before full experiments, prove:

- one CNN
- `Fashion-MNIST`
- IID partition
- fixed rates:
  - `rpi4=0.5`
  - `rpi5=1.0`
- 3 to 5 rounds

Compare:

- `fedavg-full`
- `fedavg-small`
- `heterofl-fixed`

Success means:

- sliced parameter shapes are valid
- training completes end-to-end
- aggregation is stable
- logs make each node's assigned rate explicit

## Why this design is better than copying the old baseline

The old Flower HeteroFL baseline is the correct algorithmic reference, but it is
not the right software shape for this project. The modern Flower framework already
expects:

- a `ServerApp`
- a custom `Strategy`
- `ClientApp` handlers working on `Message` objects

So the migration target should be:

- old HeteroFL slicing and masked aggregation logic
- wrapped in modern Flower strategy/message abstractions
- with `fedctl` only handling deployment metadata
