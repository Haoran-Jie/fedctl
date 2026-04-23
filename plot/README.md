# Plot Pipeline

This folder contains the reproducible plotting pipeline for dissertation figures.

## Structure
- `common.py`: shared output/path helpers
- `output/`: local plot artifacts
- `*.py`: plot entrypoints

## Entrypoints
- `compute_cifar10_submodels.py`: CIFAR-10 local submodel accuracy grid
- `compute_california_submodels.py`: California Housing local submodel R2 grid
- `compute_cifar10_client_time.py`: per-client CIFAR-10 training-time curves
- `compute_fedrolex_submodels.py`: FedRolex local submodel histogram
- `compute_runtime.py`: compute-main runtime decomposition table
- `slow_client_tradeoff.py`: slow-client inclusion trade-off plot/table data
- `fixed_pair_interp.py`: fixed-pair interpolation triptych
- `network_client_trips.py`: network-main accuracy versus client trips
- `network_wall_clock.py`: network-main accuracy versus wall-clock time
- `network_common.py`: shared network-main W&B loading/aggregation helpers

## Output policy
Plot scripts keep raw data and diagnostics in:
- `plot/output/`

Only the final publication PDF is mirrored into:
- `writeup/figures/`

LaTeX embeds the `writeup/figures/` PDFs directly. Do not mirror CSV,
JSON, or PNG diagnostics into the writeup tree.
