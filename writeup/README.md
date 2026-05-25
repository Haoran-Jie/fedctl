# Writeup Skeleton

This directory contains the dissertation writeup scaffold for the `fedctl` project.

## Files

- `main.tex`: main LaTeX entry point
- `references.bib`: bibliography
- `1_introduction.tex` to `6_conclusions.tex`: main chapters
- `Appendix_*.tex`: appendix placeholders
- `../apps/fedctl_research/run_configs/`: dissertation experiment TOMLs
- `../apps/fedctl_research/deploy_configs/`: deployment config templates for the dissertation studies

## Suggested build

From `writeup/`:

```bash
latexmk -pdf -outdir=out main.tex
```

This will run LaTeX, `biber`, and the required follow-up passes automatically.

If you prefer XeLaTeX:

```bash
latexmk -xelatex -outdir=out main.tex
```

If you run the steps manually, keep the output directory consistent:

```bash
pdflatex -output-directory=out main.tex
biber out/main
pdflatex -output-directory=out main.tex
pdflatex -output-directory=out main.tex
```
