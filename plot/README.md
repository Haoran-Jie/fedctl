# Plot Pipeline

This folder contains the reproducible plotting pipeline for dissertation figures.

## Structure
- `common.py`: shared output/path helpers
- `output/`: local plot artifacts
- `*.py`: plot entrypoints

## Output policy
Each plot writes artifacts to both:
- `plot/output/`
- `writeup/figures/generated/`

The `writeup` copy is what LaTeX embeds. The `plot/output` copy is the local plotting workspace.
