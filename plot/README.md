# Plot Pipeline

This folder contains the reproducible plotting pipeline for dissertation figures.

## Structure
- `common.py`: shared output/path helpers
- `output/`: local plot artifacts
- `*.py`: plot entrypoints

## Output policy
Plot scripts keep raw data and diagnostics in:
- `plot/output/`

Only the final publication PDF is mirrored into:
- `writeup/figures/`

LaTeX embeds the `writeup/figures/` PDFs directly. Do not mirror CSV,
JSON, or PNG diagnostics into the writeup tree.
