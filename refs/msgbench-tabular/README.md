# Message-Size Benchmark (msgbench)

Standalone Flower project for communication-only benchmarking using
`Grid.send_and_receive`.

This project is intentionally separate from `quickstart-pytorch` so it can
have its own `pyproject.toml` and run-config surface.

## Run (simulation)

```bash
flwr run .
```

## Example run-config override

```bash
flwr run . --run-config "num-server-rounds=3 msgbench-request-bytes=1048576 msgbench-reply-bytes=1048576 msgbench-fanout=3 msgbench-target-mode='fixed'"
```

The server emits per-round structured records prefixed with:

- `[msgbench-json]`
