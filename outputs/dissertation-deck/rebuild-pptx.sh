#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

NODE_BIN="${NODE_BIN:-$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node}"
ARTIFACT_TOOL_MJS="${ARTIFACT_TOOL_MJS:-$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs}"

WORKSPACE="$REPO_ROOT/outputs/019e64f2-ca9b-7981-bcfd-8db409e6988d/presentations/fedctl-dissertation-short-deck"
SLIDES_DIR="$WORKSPACE/slides"
ASSET_DIR="$WORKSPACE/assets"
OUT_DIR="$REPO_ROOT/outputs/dissertation-deck"
FINAL_PPTX="$OUT_DIR/fedctl-dissertation-short-deck.pptx"
NAMED_PPTX="$OUT_DIR/Jie-Haoran.pptx"

mkdir -p "$OUT_DIR"

DECK_REPO_ROOT="$REPO_ROOT" \
DECK_WORKSPACE="$WORKSPACE" \
DECK_SLIDES_DIR="$SLIDES_DIR" \
DECK_ASSET_DIR="$ASSET_DIR" \
DECK_OUT_DIR="$OUT_DIR" \
DECK_FINAL_PPTX="$FINAL_PPTX" \
ARTIFACT_TOOL_MJS="$ARTIFACT_TOOL_MJS" \
"$NODE_BIN" --input-type=module <<'NODE'
import fs from "node:fs/promises";
import path from "node:path";

const { Presentation, PresentationFile } = await import(process.env.ARTIFACT_TOOL_MJS);

const root = process.env.DECK_REPO_ROOT;
const workspace = process.env.DECK_WORKSPACE;
const slidesDir = process.env.DECK_SLIDES_DIR;
const assetDir = process.env.DECK_ASSET_DIR;
const outDir = process.env.DECK_OUT_DIR;
const finalPptx = process.env.DECK_FINAL_PPTX;

const ctx = {
  root,
  workspace,
  slidesDir,
  assetDir,
  previewDir: path.join(workspace, "preview"),
  layoutDir: path.join(workspace, "layout"),
  qaDir: path.join(workspace, "qa"),
  outDir,
};

const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });
// Export only the main talk slides; appendix slide modules remain in source.
const slideNumbers = [
  1,
  2,
  8,
  9,
  24,
  4,
  5,
  6,
  7,
  10,
  // 3,
  // 11,
  12,
  13,
  // 14,
  15,
  16,
];
for (const i of slideNumbers) {
  const slidePath = path.join(slidesDir, `slide-${String(i).padStart(2, "0")}.mjs`);
  const mod = await import(slidePath);
  await mod.default(presentation, ctx);
}

const blob = await PresentationFile.exportPptx(presentation);
await fs.writeFile(finalPptx, Buffer.from(blob.data));
console.log(`wrote ${finalPptx} (${blob.data.length} bytes, ${presentation.slides.count} slides)`);
NODE

python3 - <<'PY' "$FINAL_PPTX"
from pathlib import Path
import re
import sys
import zipfile

pptx = Path(sys.argv[1])
with zipfile.ZipFile(pptx) as zf:
    slides = [name for name in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)]
    notes = [name for name in zf.namelist() if re.match(r"ppt/notesSlides/notesSlide\d+\.xml$", name)]
print(f"verified slides={len(slides)} notes={len(notes)} size={pptx.stat().st_size}")
PY

cp "$FINAL_PPTX" "$NAMED_PPTX"
echo "copied $NAMED_PPTX"
