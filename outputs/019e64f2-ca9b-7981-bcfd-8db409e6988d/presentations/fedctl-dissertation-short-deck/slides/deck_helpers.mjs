import fs from "node:fs/promises";
import path from "node:path";

export const W = 1280;
export const H = 720;

export const C = {
  navy: "#071f46",
  navy2: "#123a66",
  ink: "#111827",
  muted: "#5b6472",
  pale: "#f5f7fb",
  panel: "#ffffff",
  line: "#d5dce8",
  gold: "#f3c432",
  teal: "#43a896",
  green: "#1db954",
  orange: "#f59e0b",
  red: "#f04a23",
  blue: "#1f77b4",
};

const TYPEFACE = "Latin Modern Roman 12 Regular";
const TRANSPARENT = "#00000000";
const EVAL_CLAIM = { y: 150, h: 40 };
const EVAL_SETUP_Y = 200;
const EVAL_PANEL_TITLE_SIZE = 18;
const PPT_11PT_SIZE = 14.7; // Artifact-tool font sizes are CSS px; this resolves to ~11pt in PowerPoint.
const EVAL_CAPTION_SIZE = PPT_11PT_SIZE;

function mimeFromPath(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".png") return "image/png";
  if (ext === ".svg") return "image/svg+xml";
  return "application/octet-stream";
}

export function addShape(slide, { x, y, w, h, fill = C.panel, outline = "none", radius = 0, geometry = "rect" }) {
  const line = outline === "none"
    ? { style: "solid", fill: TRANSPARENT, width: 0 }
    : (() => {
        const match = /^(\d+(?:\.\d+)?)px\s+solid\s+(.+)$/.exec(outline);
        return match
          ? { style: "solid", fill: match[2], width: Number(match[1]) }
          : { style: "solid", fill: outline, width: 1 };
      })();
  const shape = {
    geometry,
    position: { left: x, top: y, width: w, height: h },
    fill,
    line,
  };
  if (geometry === "rect" || geometry === "textbox" || geometry === "roundRect") {
    shape.borderRadius = radius;
  }
  return slide.shapes.add(shape);
}

export function addText(slide, text, {
  x,
  y,
  w,
  h,
  size = 24,
  color = C.ink,
  bold = false,
  align = "left",
  valign = "top",
  line = 1.08,
  fill = "none",
  outline = "none",
  radius = 0,
  inset = 0,
} = {}) {
  const shape = addShape(slide, { x, y, w, h, fill, outline, radius });
  shape.text = text;
  shape.text.typeface = TYPEFACE;
  shape.text.fontSize = size;
  shape.text.color = color;
  shape.text.bold = bold;
  shape.text.alignment = align;
  shape.text.verticalAlignment = valign;
  shape.text.insets = { top: inset, right: inset, bottom: inset, left: inset };
  return shape;
}

export async function addImage(slide, ctx, relPath, {
  x,
  y,
  w,
  h,
  alt = "",
  fit = "contain",
  radius = 0,
} = {}) {
  const filePath = path.join(ctx.assetDir, relPath);
  const data = await fs.readFile(filePath);
  return slide.images.add({
    data,
    contentType: mimeFromPath(filePath),
    position: { left: x, top: y, width: w, height: h },
    fit,
    alt,
    borderRadius: radius,
  });
}

function imageDimensions(filePath, data) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".png" && data.length >= 24) {
    return { w: data.readUInt32BE(16), h: data.readUInt32BE(20) };
  }
  if (ext === ".svg") {
    const svg = data.toString("utf8", 0, Math.min(data.length, 4096));
    const viewBox = /viewBox=["']\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)\s*["']/i.exec(svg);
    if (viewBox) {
      return { w: Number(viewBox[1]), h: Number(viewBox[2]) };
    }
    const width = /width=["']([\d.]+)/i.exec(svg);
    const height = /height=["']([\d.]+)/i.exec(svg);
    if (width && height) {
      return { w: Number(width[1]), h: Number(height[1]) };
    }
  }
  return null;
}

export async function addImageContained(slide, ctx, relPath, {
  x,
  y,
  w,
  h,
  alt = "",
  alignX = 0.5,
  alignY = 0.5,
  radius = 0,
} = {}) {
  const filePath = path.join(ctx.assetDir, relPath);
  const data = await fs.readFile(filePath);
  const dims = imageDimensions(filePath, data);
  if (!dims || dims.w <= 0 || dims.h <= 0) {
    return slide.images.add({
      data,
      contentType: mimeFromPath(filePath),
      position: { left: x, top: y, width: w, height: h },
      fit: "contain",
      alt,
      borderRadius: radius,
    });
  }

  const scale = Math.min(w / dims.w, h / dims.h);
  const displayW = dims.w * scale;
  const displayH = dims.h * scale;
  return slide.images.add({
    data,
    contentType: mimeFromPath(filePath),
    position: {
      left: x + (w - displayW) * alignX,
      top: y + (h - displayH) * alignY,
      width: displayW,
      height: displayH,
    },
    fit: "contain",
    alt,
    borderRadius: radius,
  });
}

export async function addImageAtNativeScale(slide, ctx, relPath, {
  centerX,
  centerY,
  scale = 1,
  alt = "",
  radius = 0,
} = {}) {
  const filePath = path.join(ctx.assetDir, relPath);
  const data = await fs.readFile(filePath);
  const dims = imageDimensions(filePath, data);
  if (!dims || dims.w <= 0 || dims.h <= 0) {
    throw new Error(`Cannot determine native image dimensions for ${relPath}`);
  }
  const displayW = dims.w * scale;
  const displayH = dims.h * scale;
  return slide.images.add({
    data,
    contentType: mimeFromPath(filePath),
    position: {
      left: centerX - displayW / 2,
      top: centerY - displayH / 2,
      width: displayW,
      height: displayH,
    },
    fit: "contain",
    alt,
    borderRadius: radius,
  });
}

export async function addImageByNativeRatio(slide, ctx, relPath, {
  x,
  y,
  w,
  alt = "",
  radius = 0,
} = {}) {
  const filePath = path.join(ctx.assetDir, relPath);
  const data = await fs.readFile(filePath);
  const dims = imageDimensions(filePath, data);
  if (!dims || dims.w <= 0 || dims.h <= 0) {
    throw new Error(`Cannot determine native image dimensions for ${relPath}`);
  }
  const h = w * (dims.h / dims.w);
  return slide.images.add({
    data,
    contentType: mimeFromPath(filePath),
    position: { left: x, top: y, width: w, height: h },
    fit: "stretch",
    alt,
    borderRadius: radius,
  });
}

export function addRule(slide, x, y, w, color = C.line, h = 2) {
  return addShape(slide, { x, y, w, h, fill: color });
}

export async function addFooter(slide, ctx, slideNumber, label = "fedctl dissertation") {
  addRule(slide, 70, 661, 1140, "#e6ebf3", 1);
  await addImage(slide, ctx, "logos/cambridge_crest.png", { x: 73.9, y: 675, w: 20.5, h: 24, alt: "Cambridge logo" });
  addText(slide, label, { x: 104, y: 678, w: 420, h: 24, size: 13, color: C.muted });
  addText(slide, String(slideNumber).padStart(2, "0"), {
    x: 1160,
    y: 678,
    w: 50,
    h: 24,
    size: 13,
    color: C.muted,
    align: "right",
  });
}

export function addHeader(slide, kicker, title) {
  addText(slide, kicker.toUpperCase(), { x: 70, y: 36, w: 520, h: 20, size: 13, color: C.teal, bold: true });
  addText(slide, title, { x: 70, y: 62, w: 970, h: 68, size: 30, color: C.navy, bold: true });
  addRule(slide, 70, 105.6, 120, C.gold, 5);
}

export function addBullets(slide, items, { x, y, w, size = 20, gap = 46, color = C.ink } = {}) {
  items.forEach((item, index) => {
    const top = y + index * gap;
    addShape(slide, { x, y: top + 8, w: 8, h: 8, fill: C.gold, radius: 4 });
    addText(slide, item, { x: x + 22, y: top, w: w - 22, h: gap - 2, size, color, line: 1.08 });
  });
}

export function addMetric(slide, value, label, { x, y, w, color = C.navy, accent = C.gold, labelSize = 13 } = {}) {
  addShape(slide, { x, y, w, h: 116, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  addShape(slide, { x, y, w: 8, h: 116, fill: accent, radius: 4 });
  addText(slide, value, { x: x + 22, y: y + 14, w: w - 36, h: 38, size: 29, color, bold: true });
  addText(slide, label, { x: x + 22, y: y + 58, w: w - 36, h: 42, size: labelSize, color: C.muted });
}

export async function addLogoRail(slide, ctx, y = 610) {
  const logos = [
    ["logos/cambridge_crest.png", "Cambridge", 208, 243],
    ["logos/fedctl.png", "fedctl", 784, 666],
    ["logos/flower.png", "Flower", 1024, 902],
    ["logos/camlsys.png", "CaMLSys", 1015, 1016],
  ];
  const startX = 256;
  const slot = 190;
  const displayH = 68;
  for (let i = 0; i < logos.length; i += 1) {
    const [rel, label, naturalW, naturalH] = logos[i];
    const displayW = (displayH * naturalW) / naturalH;
    const cx = startX + i * slot + 50;
    await addImage(slide, ctx, rel, { x: cx - displayW / 2, y, w: displayW, h: displayH, alt: `${label} logo` });
  }
}

export function addClaimBand(slide, text, { x = 70, y = 144, w = 1140, h = 64, accent = C.teal } = {}) {
  addShape(slide, { x, y, w, h, fill: "#eef7f5", outline: `1px solid ${C.line}`, radius: 7 });
  addShape(slide, { x, y, w: 8, h, fill: accent, radius: 4 });
  addText(slide, text, { x: x + 24, y: y + 6, w: w - 42, h: h - 10, size: 22, color: C.navy, bold: true });
}

function addEvalClaimBand(slide, text, { accent = C.teal } = {}) {
  addClaimBand(slide, text, { y: EVAL_CLAIM.y, h: EVAL_CLAIM.h, accent });
}

function addSetupRibbon(slide, text, { y = 214, accent = C.teal } = {}) {
  const h = 30;
  const parts = text.split("|").map((part) => part.trim()).filter(Boolean);
  const code = parts.shift() || text;
  const detail = parts.join("  |  ");
  const chipW = Math.min(112, Math.max(72, code.length * 9 + 28));

  addShape(slide, { x: 70, y, w: 1140, h, fill: "#f8fafc", outline: `1px solid ${C.line}`, radius: 6 });
  addShape(slide, { x: 70, y, w: 7, h, fill: accent, radius: 4 });
  addShape(slide, { x: 94, y: y + 5, w: chipW, h: 20, fill: "#eef2f7", outline: "none", radius: 5 });
  addText(slide, code, {
    x: 100,
    y: y + 8,
    w: chipW - 12,
    h: 14,
    size: 14,
    color: accent,
    bold: true,
    align: "center",
  });
  addText(slide, detail, {
    x: 108 + chipW,
    y: y + 7,
    w: 1084 - chipW,
    h: 16,
    size: 14,
    color: C.muted,
    bold: true,
    align: "left",
  });
}

export function addHorizontalBars(slide, rows, {
  x,
  y,
  w,
  rowH = 34,
  max,
  colors,
  unit = "",
  valueDecimals = 0,
}) {
  rows.forEach((row, i) => {
    const top = y + i * rowH;
    addText(slide, row.label, { x, y: top, w: 140, h: 24, size: 15, color: C.ink, bold: row.bold || false });
    addShape(slide, { x: x + 150, y: top + 5, w, h: 14, fill: "#e8edf5", radius: 7 });
    const bw = Math.max(2, Math.min(w, (row.value / max) * w));
    addShape(slide, { x: x + 150, y: top + 5, w: bw, h: 14, fill: colors[row.color] || row.color || C.blue, radius: 7 });
    const shown = Number(row.value).toFixed(valueDecimals);
    addText(slide, `${shown}${unit}`, { x: x + 158 + w, y: top - 1, w: 74, h: 24, size: 14, color: C.muted });
  });
}

export function addSectionTag(slide, text, { x, y, color = C.navy } = {}) {
  addShape(slide, { x, y, w: 120, h: 28, fill: "#eef2f7", outline: "none", radius: 6 });
  addText(slide, text, { x: x + 10, y: y + 5, w: 100, h: 18, size: 12, color, bold: true, align: "center" });
}

function baseSlide(presentation) {
  const slide = presentation.slides.add();
  slide.background.fill = "#fbfcfd";
  return slide;
}

export async function buildSlide(presentation, ctx, n) {
  const slide = baseSlide(presentation);
  const builders = {
    1: titleSlide,
    2: problemSlide,
    3: evaluationMapSlide,
    4: submodelMethodsSlide,
    5: asyncMethodsSlide,
    6: fedcoverMismatchSlide,
    7: fedcoverMechanismSlide,
    8: systemSlide,
    9: heterogeneityControlsSlide,
    10: weakClientSlide,
    11: computeFrontierSlide,
    12: computeDiagnosticSlide,
    13: stragglerResultSlide,
    14: networkFairnessSlide,
    15: fedcoverFeasibilitySlide,
    16: conclusionSlide,
    // Appendix slides are kept in source but omitted from the exported short deck.
    17: appendixDividerSlide,
    18: testbedSlide,
    19: appendixQueueSlide,
    20: appendixConfigsSlide,
    21: appendixPlacementSlide,
    22: appendixNetworkSlide,
    23: appendixAsyncDiagnosticsSlide,
    24: clusterTestbedSlide,
  };
  if (!builders[n]) {
    throw new Error(`No slide builder for slide ${n}`);
  }
  await builders[n](slide, ctx);
  return slide;
}

function addSmallLabel(slide, text, { x, y, w = 90, fill = "#eef2f7", color = C.navy } = {}) {
  addShape(slide, { x, y, w, h: 24, fill, outline: "none", radius: 5 });
  addText(slide, text, { x: x + 8, y: y + 4, w: w - 16, h: 16, size: 11, color, bold: true, align: "center" });
}

function addCard(slide, { x, y, w, h, title, body, accent = C.teal, fill = C.panel, titleSize = 19, bodySize = 14 }) {
  addShape(slide, { x, y, w, h, fill, outline: `1px solid ${C.line}`, radius: 7 });
  addShape(slide, { x, y, w: 7, h, fill: accent, radius: 4 });
  addText(slide, title, { x: x + 20, y: y + 16, w: w - 34, h: 30, size: titleSize, color: C.navy, bold: true });
  addText(slide, body, { x: x + 20, y: y + 52, w: w - 34, h: h - 62, size: bodySize, color: C.ink, line: 1.12 });
}

function addConnector(slide, x1, y1, x2, y2, color = "#a8b2c2") {
  const left = Math.min(x1, x2);
  const width = Math.abs(x2 - x1);
  addText(slide, "→", {
    x: left,
    y: y1 - 15,
    w: width,
    h: 30,
    size: 21,
    color,
    bold: true,
    align: "center",
  });
}

function addSimpleBarChart(slide, rows, {
  x,
  y,
  w,
  rowH = 42,
  max,
  unit = "",
  valueFormatter = (v) => String(v),
  colors = {},
  labelW = 170,
  valueW = 64,
}) {
  rows.forEach((row, i) => {
    const top = y + i * rowH;
    addText(slide, row.label, { x, y: top - 1, w: labelW, h: 24, size: row.labelSize || 13, color: row.muted ? C.muted : C.ink, bold: row.bold || false });
    addShape(slide, { x: x + labelW, y: top + 4, w, h: 16, fill: "#e7edf6", radius: 8 });
    const bw = Math.max(2, Math.min(w, (row.value / max) * w));
    addShape(slide, { x: x + labelW, y: top + 4, w: bw, h: 16, fill: colors[row.color] || row.color || C.teal, radius: 8 });
    addText(slide, `${valueFormatter(row.value)}${unit}`, { x: x + labelW + w + 10, y: top - 1, w: valueW, h: 24, size: 12, color: C.muted });
  });
}

function addTwoBarRows(slide, rows, {
  x,
  y,
  w,
  rowH = 58,
  max,
  aLabel,
  bLabel,
  aColor = "#aeb8c8",
  bColor = C.red,
  labelW = 166,
  unit = "",
}) {
  rows.forEach((row, i) => {
    const top = y + i * rowH;
    addText(slide, row.label, { x, y: top, w: labelW, h: 24, size: 13, color: C.ink, bold: true });
    addText(slide, aLabel, { x: x + labelW, y: top - 17, w: 110, h: 16, size: 9, color: C.muted });
    addShape(slide, { x: x + labelW, y: top, w, h: 12, fill: "#e7edf6", radius: 6 });
    addShape(slide, { x: x + labelW, y: top, w: (row.a / max) * w, h: 12, fill: aColor, radius: 6 });
    addText(slide, `${row.a}${unit}`, { x: x + labelW + w + 8, y: top - 5, w: 54, h: 20, size: 11, color: C.muted });
    addText(slide, bLabel, { x: x + labelW, y: top + 18, w: 110, h: 16, size: 9, color: C.muted });
    addShape(slide, { x: x + labelW, y: top + 32, w, h: 12, fill: "#e7edf6", radius: 6 });
    addShape(slide, { x: x + labelW, y: top + 32, w: (row.b / max) * w, h: 12, fill: bColor, radius: 6 });
    addText(slide, `${row.b}${unit}`, { x: x + labelW + w + 8, y: top + 27, w: 54, h: 20, size: 11, color: C.muted });
  });
}

function addSourceNote(slide, text) {
  // Source notes are retained in source calls, but not rendered in the spoken deck.
}

function addAppendixHeader(slide, title, subtitle) {
  addText(slide, "APPENDIX", { x: 70, y: 36, w: 300, h: 20, size: 13, color: C.teal, bold: true });
  addText(slide, title, { x: 70, y: 62, w: 930, h: 48, size: 30, color: C.navy, bold: true });
  addText(slide, subtitle, { x: 70, y: 112, w: 760, h: 26, size: 15, color: C.muted });
  addRule(slide, 70, 132.48, 120, C.gold, 5);
}

async function titleSlide(slide, ctx) {
  addShape(slide, { x: 0, y: 0, w: W, h: 110, fill: C.navy });
  addShape(slide, { x: 0, y: 110, w: W, h: 8, fill: C.gold });
  addText(slide, "PART III DISSERTATION PRESENTATION", {
    x: 76,
    y: 154,
    w: 520,
    h: 22,
    size: 14,
    color: C.teal,
    bold: true,
  });
  addText(slide, "Fedctl: A Heterogeneous Testbed for Realistic Federated Learning", {
    x: 74,
    y: 194,
    w: 785,
    h: 155,
    size: 43,
    color: C.navy,
    bold: true,
    line: 1.02,
  });
  addText(slide, "Haoran Jie", { x: 77, y: 374, w: 310, h: 34, size: 24, color: C.ink, bold: true });
  addText(slide, "Department of Computer Science and Technology | University of Cambridge | June 2026", {
    x: 77,
    y: 412,
    w: 720,
    h: 28,
    size: 17,
    color: C.muted,
  });
  addText(slide, "fedctl.cl.cam.ac.uk", {
    x: 77,
    y: 444,
    w: 260,
    h: 22,
    size: 14,
    color: C.teal,
    bold: true,
  });
  addShape(slide, { x: 930, y: 178, w: 230, h: 230, fill: "#ffffff", outline: `1px solid ${C.line}`, radius: 8 });
  await addImage(slide, ctx, "logos/fedctl.png", { x: 965, y: 219, w: 160.1, h: 136, alt: "fedctl logo" });
  addText(slide, "Deployment-aware evaluation of heterogeneous FL", {
    x: 900,
    y: 430,
    w: 290,
    h: 52,
    size: 18,
    color: C.navy,
    bold: true,
    align: "center",
  });
  addRule(slide, 70, 548, 1140, "#e6ebf3", 1);
  await addLogoRail(slide, ctx, 576);
}

async function problemSlide(slide, ctx) {
  addHeader(slide, "Rationale", "Heterogeneous FL Needs Deployment-Aware Evaluation");
  addClaimBand(slide, "In deployed FL, a client is a device—not just a data partition. Device capability, update timing, network conditions, influence, submodel quality, and parameter coverage all shape outcomes.", { y: 156, h: 72 });
  await addImageContained(slide, ctx, "figures_svg/evaluation_environment_simulation.svg", {
    x: 72,
    y: 258,
    w: 330,
    h: 377,
    alt: "Simulation evaluation setting",
  });
  await addImageContained(slide, ctx, "figures_svg/evaluation_environment_homogeneous.svg", {
    x: 475,
    y: 258,
    w: 330,
    h: 377,
    alt: "Homogeneous hardware evaluation setting",
  });
  await addImageContained(slide, ctx, "figures_svg/evaluation_environment_heterogeneous.svg", {
    x: 878,
    y: 258,
    w: 330,
    h: 377,
    alt: "Heterogeneous hardware evaluation setting",
  });
  addText(slide, "data split on one machine", { x: 92, y: 616, w: 290, h: 24, size: 18.7, color: C.muted, align: "center" });
  addText(slide, "one network; equal devices", { x: 495, y: 616, w: 290, h: 24, size: 18.7, color: C.muted, align: "center" });
  addText(slide, "mixed devices and networks", { x: 898, y: 616, w: 290, h: 24, size: 18.7, color: C.muted, align: "center" });
  await addFooter(slide, ctx, 2, "Takeaway: deployment behaviour is part of the experiment");
}

async function evaluationMapSlide(slide, ctx) {
  addHeader(slide, "Evaluation map", "Two System Heterogeneities and Their Intersections");
  const cols = [
    {
      x: 70,
      color: C.teal,
      title: "Compute heterogeneity",
      objectives: "C1-C4",
      definition: "Clients differ in local speed and memory, so weak devices may need smaller deployable models or longer training time.",
      methods: "FedAvg, HeteroFL, FedRolex, FIARSE",
      controls: "weak-client inclusion; 20-node mixed testbed; model-rate sweeps",
      metrics: "global score, runtime, train-round latency, local submodel quality",
    },
    {
      x: 455,
      color: C.orange,
      title: "Straggler-induced heterogeneity",
      objectives: "S1-S3",
      definition: "Clients complete at different times, so synchronous rounds wait and asynchronous aggregation can skew toward fast arrivals.",
      methods: "FedAvg, FedAsync, FedBuff, FedStaleWeight",
      controls: "all-rpi5 negative control; mixed topology; netem profiles; device-correlated skew",
      metrics: "time/trips to target, update share, aggregate weight share, staleness",
    },
    {
      x: 840,
      color: C.red,
      title: "Asynchronous submodel FL",
      objectives: "A1-A2",
      definition: "Asynchronous arrivals combine with heterogeneous submodel rates, so accepted buffers cover different parameter subsets.",
      methods: "HeteroFL, Async-HeteroFL, FedCover, contextual FedBuff",
      controls: "same nested rate assignment; gamma sweep with fixed kappa max",
      metrics: "target time, speedup, rpi4 weight, coverage gain",
    },
  ];
  cols.forEach((col) => {
    addShape(slide, { x: col.x, y: 148, w: 350, h: 438, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
    addShape(slide, { x: col.x, y: 148, w: 350, h: 8, fill: col.color, radius: 4 });
    addSmallLabel(slide, col.objectives, { x: col.x + 22, y: 174, w: 76, fill: "#f1f5f9", color: col.color });
    addText(slide, col.title, { x: col.x + 22, y: 206, w: 300, h: 54, size: 21, color: C.navy, bold: true });
    addText(slide, "Definition", { x: col.x + 22, y: 270, w: 100, h: 20, size: 14.7, color: col.color, bold: true });
    addText(slide, col.definition, { x: col.x + 22, y: 294, w: 300, h: 70, size: 14.7, color: C.ink, line: 0.98 });
    addText(slide, "Methods", { x: col.x + 22, y: 366, w: 100, h: 20, size: 14.7, color: col.color, bold: true });
    addText(slide, col.methods, { x: col.x + 22, y: 390, w: 300, h: 48, size: 14.7, color: C.ink, line: 0.98 });
    addText(slide, "Controls", { x: col.x + 22, y: 438, w: 100, h: 20, size: 14.7, color: col.color, bold: true });
    addText(slide, col.controls, { x: col.x + 22, y: 462, w: 300, h: 44, size: 14.7, color: C.ink, line: 0.98 });
    addText(slide, "Metrics", { x: col.x + 22, y: 508, w: 100, h: 20, size: 14.7, color: col.color, bold: true });
    addText(slide, col.metrics, { x: col.x + 22, y: 532, w: 300, h: 38, size: 14.7, color: C.ink, line: 0.98 });
  });
  addShape(slide, { x: 166, y: 594, w: 948, h: 38, fill: "#f1f5f9", outline: "none", radius: 7 });
  addText(slide, "Same run path, different controlled deployment pressures.", { x: 206, y: 602, w: 870, h: 22, size: 18, color: C.navy, bold: true, align: "center" });
  await addFooter(slide, ctx, 3, "evaluation map: objectives C1-C4, S1-S3, A1-A2");
}

async function submodelMethodsSlide(slide, ctx) {
  addText(slide, "BACKGROUND", { x: 70, y: 36, w: 520, h: 20, size: 13, color: C.teal, bold: true });
  addText(slide, "Submodel FL for Compute Heterogeneity", { x: 70, y: 62, w: 1120, h: 42, size: 30, color: C.navy, bold: true });
  addRule(slide, 70, 105.6, 120, C.gold, 5);
  await addImageContained(slide, ctx, "figures_svg/model_heterogeneity_method_overview.svg", {
    x: 70,
    y: 140,
    w: 1140,
    h: 470,
    alt: "HeteroFL, FedRolex, and FIARSE submodel extraction overview",
  });

  addSourceNote(slide, "Source: related work chapter, Figure 3.1.");
  await addFooter(slide, ctx, 6, "method background: submodel FL baselines");
}

async function asyncMethodsSlide(slide, ctx) {
  addText(slide, "BACKGROUND", { x: 70, y: 36, w: 520, h: 20, size: 13, color: C.teal, bold: true });
  addText(slide, "Asynchronous FL for Straggler-Induced Heterogeneity", { x: 70, y: 62, w: 1120, h: 42, size: 30, color: C.navy, bold: true });
  addRule(slide, 70, 105.6, 120, C.gold, 5);
  await addImageContained(slide, ctx, "figures_svg/async_method_overview.svg", {
    x: 70,
    y: 140,
    w: 1140,
    h: 470,
    alt: "FedAsync, FedBuff, and FedStaleWeight asynchronous execution overview",
  });

  addSourceNote(slide, "Source: related work chapter, Figure 3.2.");
  await addFooter(slide, ctx, 7, "method background: asynchronous FL baselines");
}

async function systemSlide(slide, ctx) {
  addHeader(slide, "Implementation", "fedctl Run Lifecycle");
  addShape(slide, { x: 70, y: 150, w: 1140, h: 498, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  await addImageContained(slide, ctx, "figures_svg/remote_execution_lifecycle_clean.svg", {
    x: 80,
    y: 160,
    w: 1120,
    h: 480,
    alt: "remote execution lifecycle",
  });
  await addFooter(slide, ctx, 3, "implementation: reusable control plane for Flower experiments");
}

async function clusterTestbedSlide(slide, ctx) {
  addHeader(slide, "Implementation", "Physical Heterogeneous Cluster");

  addShape(slide, { x: 70, y: 150, w: 640, h: 496, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  await addImageContained(slide, ctx, "figures/clusterpicture.png", {
    x: 86,
    y: 166,
    w: 608,
    h: 464,
    alt: "Photograph of the physical Raspberry Pi cluster used for fedctl experiments",
    radius: 4,
  });

  function addClusterFact({ y, accent, title, body }) {
    const x = 780;
    const w = 380;
    const h = 82;
    const textX = x + 26;
    addShape(slide, { x, y, w, h, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
    addShape(slide, { x, y, w: 7, h, fill: accent, radius: 4 });
    addText(slide, title, { x: textX, y: y + 12, w: w - 52, h: 28, size: 22, color: C.navy, bold: true });
    addText(slide, body, { x: textX, y: y + 42, w: w - 52, h: 32, size: 14, color: C.muted, line: 1.04 });
  }

  addClusterFact({ y: 158, accent: C.teal, title: "50-device worker pool", body: "30 rpi4 + 20 rpi5 for real heterogeneous execution" });
  addClusterFact({ y: 262, accent: C.gold, title: "repeatable deployment", body: "rerun the same workload with controlled placement and network conditions" });
  addClusterFact({ y: 366, accent: C.red, title: "shared-lab control", body: "queueing, resource checks, and artifacts replace manual SSH deployment" });
  addClusterFact({ y: 470, accent: C.navy2, title: "extensible devices", body: "add a Jetson class and image; reuse placement and network controls" });

  await addFooter(slide, ctx, 5, "implementation: physical heterogeneous testbed");
}

async function testbedSlide(slide, ctx) {
  addHeader(slide, "Testbed and controls", "Deployment conditions are first-class variables");
  addMetric(slide, "30 x rpi4", "slower worker pool; used as the weak-device class", { x: 80, y: 168, w: 270, accent: C.orange });
  addMetric(slide, "20 x rpi5", "faster worker pool; used for controls and mixed slices", { x: 80, y: 292, w: 270, accent: C.teal });
  addMetric(slide, "typed slices", "e.g. 10 rpi4 + 10 rpi5 without changing app code", { x: 80, y: 416, w: 270, accent: C.navy2 });

  addCard(slide, {
    x: 396,
    y: 168,
    w: 328,
    h: 150,
    title: "Run config",
    body: "Scientific definition: task, model, partitioner, method, seed, local budget, evaluation.",
    accent: C.teal,
  });
  addCard(slide, {
    x: 770,
    y: 168,
    w: 328,
    h: 150,
    title: "Deploy config",
    body: "Execution definition: device counts, placement, resource reservations, images, registry, network profiles.",
    accent: C.gold,
  });
  addConnector(slide, 724, 244, 770, 244, "#9aa6b8");
  addShape(slide, { x: 396, y: 358, w: 704, h: 202, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  addText(slide, "Controlled heterogeneity", { x: 426, y: 386, w: 300, h: 30, size: 23, color: C.navy, bold: true });
  addBullets(slide, [
    "Placement records which logical clients ran on which device class.",
    "netem profiles add delay, jitter, loss, and bandwidth limits at deployment time.",
    "Logs, W&B metrics, artifacts, and runtime metadata preserve the run record.",
  ], { x: 430, y: 432, w: 620, size: 15, gap: 36 });
  addSourceNote(slide, "Full device-placement and network-impairment diagrams are in the appendix.");
  await addFooter(slide, ctx, 18, "appendix: testbed and controls");
}

async function heterogeneityControlsSlide(slide, ctx) {
  addHeader(slide, "Implementation", "Controlling Heterogeneity");

  function addFlowStep({ x, y, w, title, body, accent }) {
    addShape(slide, { x, y, w, h: 112, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
    addShape(slide, { x, y, w, h: 6, fill: accent, radius: 3 });
    addText(slide, title, { x: x + 12, y: y + 16, w: w - 24, h: 30, size: 17, color: C.navy, bold: true, align: "center" });
    addText(slide, body, { x: x + 12, y: y + 58, w: w - 24, h: 42, size: 16, color: C.muted, align: "center" });
  }

  function addFlowArrow(x, y) {
    addText(slide, "→", { x, y, w: 18, h: 24, size: 20, color: "#8d9aac", bold: true, align: "center" });
  }

  const panels = [
    {
      x: 150,
      y: 150,
      w: 980,
      h: 224,
      title: "Typed client placement",
      subtitle: "Assign logical clients to device classes.",
      accent: C.teal,
      steps: [
        ["--supernodes", "rpi4=10, rpi5=10"],
        ["Scheduler", "device-type constraints"],
        ["Runtime pair", "SuperNode + ClientApp"],
        ["Evidence", "device-labelled metrics"],
      ],
    },
    {
      x: 150,
      y: 406,
      w: 980,
      h: 222,
      title: "Network impairment",
      subtitle: "Apply controlled network conditions per client.",
      accent: C.orange,
      steps: [
        ["Deploy config", "define network profile"],
        ["--net", "rpi4[∗]=mild,\nrpi5[1]=none"],
        ["Wrapper:", "apply tc/netem before SuperNode"],
        ["Runtime:", "unchanged Flower interface"],
      ],
    },
  ];

  panels.forEach((panel) => {
    const innerX = panel.x + 24;
    const titleY = panel.y + 24;
    const stepY = panel.y + 92;
    const gap = 28;
    const stepW = (panel.w - 72 - 3 * gap) / 4;
    addShape(slide, { x: panel.x, y: panel.y, w: panel.w, h: panel.h, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
    addShape(slide, { x: panel.x, y: panel.y, w: 8, h: panel.h, fill: panel.accent, radius: 4 });
    addText(slide, panel.title, { x: innerX, y: titleY, w: panel.w - 48, h: 30, size: 24, color: C.navy, bold: true });
    addText(slide, panel.subtitle, { x: innerX, y: titleY + 36, w: panel.w - 48, h: 22, size: 15.5, color: C.muted });

    panel.steps.forEach(([title, body], index) => {
      const stepX = innerX + index * (stepW + gap);
      addFlowStep({ x: stepX, y: stepY, w: stepW, title, body, accent: panel.accent });
      if (index < panel.steps.length - 1) {
        addFlowArrow(stepX + stepW + (gap - 18) / 2, stepY + 47);
      }
    });
  });

  addSourceNote(slide, "Full typed-placement and network-impairment diagrams are retained in the appendix.");
  await addFooter(slide, ctx, 4, "implementation: deployment-side heterogeneity controls");
}

async function weakClientSlide(slide, ctx) {
  addHeader(slide, "Evaluation", "Weak-Client Inclusion Without Full-Model Cost");
  addEvalClaimBand(slide, "Reduced-rate submodels include weaker clients without the full-model runtime cost.");
  addSetupRibbon(slide, "C1 | CIFAR-10 non-IID | 5 rpi5 + 10 rpi4 | 20 rounds | compare exclusion, full inclusion, reduced-rate inclusion", { y: EVAL_SETUP_Y, accent: C.teal });
  addShape(slide, { x: 630, y: 252, w: 580, h: 354, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  addText(slide, "Measured trade-off", { x: 654, y: 262, w: 260, h: 24, size: EVAL_PANEL_TITLE_SIZE, color: C.navy, bold: true });
  await addImageContained(slide, ctx, "figures_svg/slow_client_inclusion_table.svg", {
    x: 654,
    y: 294,
    w: 532,
    h: 188,
    alt: "LaTeX table for slow-client inclusion trade-off",
  });
  addText(slide, "HeteroFL/FedRolex keep all partitions at much lower runtime; FIARSE gives stronger reduced-rate accuracy, but no dense-kernel speedup.", {
    x: 682,
    y: 500,
    w: 474,
    h: 44,
    size: EVAL_CAPTION_SIZE,
    color: C.muted,
    align: "center",
    line: 1.12,
  });

  addShape(slide, { x: 70, y: 252, w: 540, h: 354, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  addText(slide, "Realistic non-IID deployment", { x: 94, y: 262, w: 430, h: 24, size: EVAL_PANEL_TITLE_SIZE, color: C.navy, bold: true });
  await addImageContained(slide, ctx, "figures_svg/compute_slow_majority_scenario.svg", {
    x: 82,
    y: 284,
    w: 518,
    h: 266,
    alt: "Realistic non-IID deployment choices behind weak-client inclusion ablation",
  });
  addSourceNote(slide, "Source: evaluation chapter, Figure 5.1 and Table 5.1.");
  await addFooter(slide, ctx, 10, "C1: weak-client inclusion decision");
}

async function computeFrontierSlide(slide, ctx) {
  addHeader(slide, "Evaluation", "Submodel FL Performance-Speed Comparison");
  addEvalClaimBand(slide, "Submodel FL trades wall-clock speed against the utility of deployed client models.");
  addSetupRibbon(slide, "C2 | 20 logical clients | 10 rpi4 + 10 rpi5 | rates 1/8, 1/4, 1/2, 1 | California Housing, Fashion-MNIST, CIFAR-10", { y: EVAL_SETUP_Y, accent: C.teal });
  addShape(slide, { x: 655, y: 252, w: 555, h: 354, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  addText(slide, "Quality-speed frontier", { x: 681, y: 266, w: 500, h: 24, size: EVAL_PANEL_TITLE_SIZE, color: C.navy, bold: true });
  await addImageContained(slide, ctx, "figures/compute_main_quality_speed_tradeoff.png", {
    x: 677,
    y: 302,
    w: 511,
    h: 210,
    alt: "quality speed trade-off relative to FedAvg",
  });
  addText(slide, "Rightward points save wall-clock time; upward points improve score. No method dominates both axes across tasks.", {
    x: 681,
    y: 528,
    w: 500,
    h: 42,
    size: EVAL_CAPTION_SIZE,
    color: C.muted,
    align: "center",
    line: 1.12,
  });
  addShape(slide, { x: 70, y: 252, w: 555, h: 354, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  addText(slide, "Rate assignment", { x: 96, y: 266, w: 500, h: 24, size: EVAL_PANEL_TITLE_SIZE, color: C.navy, bold: true });
  await addImageContained(slide, ctx, "figures_svg/compute_model_rate_assignment.svg", {
    x: 96,
    y: 308,
    w: 503,
    h: 198,
    alt: "device-aware model-rate assignment",
  });
  addText(slide, "Rate assignment creates the frontier: weak clients train smaller models, so deployed utility must be checked.", {
    x: 96,
    y: 528,
    w: 500,
    h: 32,
    size: EVAL_CAPTION_SIZE,
    color: C.muted,
    align: "center",
  });
  await addFooter(slide, ctx, 11, "C2: quality-speed frontier");
}

async function computeDiagnosticSlide(slide, ctx) {
  addHeader(slide, "Evaluation", "Local Submodel Performance Diagnostics");
  addEvalClaimBand(slide, "Local submodel evaluation reveals client-side quality gaps across submodel FL methods.");
  addSetupRibbon(slide, "C3 | CIFAR-10 non-IID + California Housing | local evaluation of extracted rate-specific submodels", { y: EVAL_SETUP_Y, accent: C.teal });
  addShape(slide, { x: 70, y: 250, w: 560, h: 360, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  addText(slide, "CIFAR-10 local accuracy", { x: 100, y: 266, w: 330, h: 24, size: EVAL_PANEL_TITLE_SIZE, color: C.navy, bold: true });
  await addImageContained(slide, ctx, "figures_svg/compute_main_cifar10_seed1340_local_submodel_grid.svg", {
    x: 92,
    y: 302,
    w: 516,
    h: 230,
    alt: "CIFAR-10 local submodel accuracy distributions",
  });
  addText(slide, "FIARSE gives higher and more balanced accuracy across submodel sizes.", {
    x: 106,
    y: 548,
    w: 488,
    h: 38,
    size: EVAL_CAPTION_SIZE,
    color: C.muted,
    align: "center",
    line: 1.12,
  });

  addShape(slide, { x: 650, y: 250, w: 560, h: 360, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  addText(slide, "California Housing local R²", { x: 680, y: 266, w: 360, h: 24, size: EVAL_PANEL_TITLE_SIZE, color: C.navy, bold: true });
  await addImageContained(slide, ctx, "figures_svg/compute_main_california_local_submodel_distributions.svg", {
    x: 674,
    y: 302,
    w: 512,
    h: 230,
    alt: "California Housing local submodel score distributions",
  });
  addText(slide, "Smaller submodels often underperform larger ones; FIARSE narrows this gap.", {
    x: 686,
    y: 548,
    w: 488,
    h: 38,
    size: EVAL_CAPTION_SIZE,
    color: C.muted,
    align: "center",
    line: 1.12,
  });
  addSourceNote(slide, "Sources: evaluation chapter, Figures 5.7 and 5.8.");
  await addFooter(slide, ctx, 11, "C3: local submodel quality");
}

async function stragglerResultSlide(slide, ctx) {
  addHeader(slide, "Evaluation", "Asynchronous FL Under Stragglers");
  addEvalClaimBand(slide, "Asynchronous FL helps only when client completion times are genuinely unequal.", { accent: C.orange });
  addSetupRibbon(slide, "S1 | CIFAR-10 | IID/non-IID × homogeneous/mixed | target: 60% | FedAvg, FedAsync, FedBuff, FedStaleWeight", { y: EVAL_SETUP_Y, accent: C.orange });

  addShape(slide, { x: 70, y: 252, w: 320, h: 334, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  addText(slide, "Homogeneous control", { x: 98, y: 272, w: 250, h: 28, size: EVAL_PANEL_TITLE_SIZE, color: C.navy, bold: true });
  [
    ["IID", "FedAvg", "651s", "best async", "715s"],
    ["Non-IID", "FedAvg", "1320s", "best async", "1486s"],
  ].forEach(([regime, syncLabel, syncValue, asyncLabel, asyncValue], index) => {
    const cardY = 322 + index * 96;
    addShape(slide, { x: 92, y: cardY, w: 270, h: 76, fill: "#f1f5f9", outline: `1px solid ${C.line}`, radius: 6 });
    addText(slide, regime, { x: 112, y: cardY + 10, w: 106, h: 22, size: 16, color: C.navy, bold: true });
    addText(slide, `${syncLabel} ${syncValue}`, { x: 112, y: cardY + 42, w: 112, h: 22, size: 15, color: C.navy, bold: true });
    addText(slide, `${asyncLabel} ${asyncValue}`, { x: 232, y: cardY + 42, w: 116, h: 22, size: 14.5, color: C.muted });
  });
  addText(slide, "Asynchronous FL is slower in the homogeneous case.", {
    x: 98,
    y: 510,
    w: 244,
    h: 48,
    size: EVAL_CAPTION_SIZE,
    color: C.muted,
    align: "center",
    line: 1.12,
  });

  addShape(slide, { x: 430, y: 252, w: 780, h: 334, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  addText(slide, "Mixed topology: time to 60% target", { x: 460, y: 272, w: 500, h: 28, size: EVAL_PANEL_TITLE_SIZE, color: C.navy, bold: true });
  addSectionTag(slide, "IID", { x: 460, y: 312 });
  addSimpleBarChart(slide, [
    { label: "FedAvg", value: 2097, color: C.blue },
    { label: "FedAsync", value: 622, color: C.green, bold: true },
    { label: "FedBuff", value: 1138, color: C.orange },
    { label: "FedSW", value: 865, color: C.red },
  ], { x: 460, y: 344, w: 180, max: 4200, unit: "s", valueFormatter: (v) => String(v), colors: {}, labelW: 100, rowH: 32, valueW: 54 });
  addSectionTag(slide, "Non-IID", { x: 870, y: 312 });
  addSimpleBarChart(slide, [
    { label: "FedAvg", value: 4043, color: C.blue },
    { label: "FedAsync", value: 1264, color: C.green, bold: true },
    { label: "FedBuff", value: 2388, color: C.orange },
    { label: "FedSW", value: 1771, color: C.red },
  ], { x: 870, y: 344, w: 170, max: 4200, unit: "s", valueFormatter: (v) => String(v), colors: {}, labelW: 100, rowH: 32, valueW: 54 });
  addText(slide, "Mixed topology: asynchronous FL reduces time to target.", {
    x: 470,
    y: 510,
    w: 700,
    h: 48,
    size: EVAL_CAPTION_SIZE,
    color: C.muted,
    align: "center",
    line: 1.12,
  });
  addSourceNote(slide, "Source: evaluation chapter, Table 5.6 target-attainment matrix.");
  await addFooter(slide, ctx, 12, "S1: target time and slow-device influence");
}

async function networkFairnessSlide(slide, ctx) {
  addHeader(slide, "Network and fairness stress", "Network and Fairness Stress");
  addEvalClaimBand(slide, "Stale-aware weighting improves slow-device influence, not arrivals or data skew.", { accent: C.orange });
  addSetupRibbon(slide, "S2/S3 | mixed CIFAR-10 non-IID | netem profiles + device-correlated skew | separate update share from aggregate weight", { y: EVAL_SETUP_Y, accent: C.orange });
  const leftPanel = { x: 70, y: 250, w: 540, h: 334 };
  const rightPanel = { x: 640, y: 250, w: 570, h: 334 };
  addShape(slide, { ...leftPanel, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  addText(slide, "Network perturbation", { x: leftPanel.x + 30, y: 272, w: leftPanel.w - 60, h: 28, size: EVAL_PANEL_TITLE_SIZE, color: C.navy, bold: true });
  await addImageContained(slide, ctx, "figures_svg/network_stressor_profile_bars.svg", {
    x: leftPanel.x + 24,
    y: 314,
    w: leftPanel.w - 48,
    h: 184,
    alt: "Network stressor profile wall-clock target-time bars",
  });
  addText(slide, "Network stress mainly stretches elapsed time and arrival order; it does not overturn the target-trip story.", {
    x: leftPanel.x + 30,
    y: 506,
    w: leftPanel.w - 60,
    h: 48,
    size: EVAL_CAPTION_SIZE,
    color: C.muted,
    align: "center",
  });

  addShape(slide, { ...rightPanel, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  addText(slide, "Device-correlated skew", { x: rightPanel.x + 30, y: 272, w: rightPanel.w - 60, h: 28, size: EVAL_PANEL_TITLE_SIZE, color: C.navy, bold: true });
  addText(slide, "FedStaleWeight restores applied influence after updates arrive, but cannot make slow devices arrive more often.", {
    x: rightPanel.x + 30,
    y: 306,
    w: rightPanel.w - 60,
    h: 40,
    size: EVAL_CAPTION_SIZE,
    color: C.muted,
  });
  const metricCardW = 160;
  const metricGap = 18;
  [
    ["rpi4 aggregate weight", "12.2%", "31.0%", "+18.8 pp", C.red],
    ["rpi4-held accuracy", "0.0%", "12.9%", "+12.9 pp", C.orange],
    ["global accuracy", "40.8%", "45.9%", "+5.1 pp", C.teal],
  ].forEach(([label, before, after, delta, accent], index) => {
    const x = rightPanel.x + 30 + index * (metricCardW + metricGap);
    addShape(slide, { x, y: 354, w: metricCardW, h: 114, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
    addShape(slide, { x, y: 354, w: 7, h: 114, fill: accent, radius: 4 });
    addText(slide, label, { x: x + 14, y: 366, w: metricCardW - 28, h: 22, size: 11.5, color: C.muted, bold: true, align: "center" });
    addText(slide, before, { x: x + 14, y: 396, w: 50, h: 24, size: 16, color: C.muted, bold: true, align: "center" });
    addText(slide, "→", { x: x + 65, y: 398, w: 24, h: 20, size: 16, color: C.muted, align: "center" });
    addText(slide, after, { x: x + 90, y: 396, w: 56, h: 24, size: 16, color: C.navy, bold: true, align: "center" });
    addText(slide, delta, { x: x + 18, y: 432, w: metricCardW - 36, h: 22, size: 14, color: accent, bold: true, align: "center" });
  });
  addText(slide, "FedBuff → FedStaleWeight improves influence and accuracy, but rpi4 accepted-update share stays flat (15.9% → 15.7%).", {
    x: rightPanel.x + 42,
    y: 500,
    w: rightPanel.w - 84,
    h: 40,
    size: EVAL_CAPTION_SIZE,
    color: C.muted,
    align: "center",
    line: 1.12,
  });
  addSourceNote(slide, "Sources: evaluation chapter, Figure 5.10 network stressor profile bars and device-correlated non-IID ablation.");
  await addFooter(slide, ctx, 14, "S2-S3: network stress and device-correlated skew");
}

async function fedcoverMismatchSlide(slide, ctx) {
  addHeader(slide, "FedCover", "Coverage Mismatch in Asynchronous Submodel FL");
  await addImageContained(slide, ctx, "figures_svg/async_submodel_coverage_mismatch.svg", {
    x: 70,
    y: 132,
    w: 1140,
    h: 392,
    alt: "Coverage mismatch in asynchronous submodel aggregation",
  });
  addText(slide, "Low-coverage parameter blocks can skew the buffered update direction.", {
    x: 140,
    y: 536,
    w: 1000,
    h: 26,
    size: 18,
    color: C.muted,
    align: "center",
  });
  addText(slide, "FedCover treats coverage as an aggregation variable: amplify observed under-covered deltas without imputing missing updates.", {
    x: 130,
    y: 586,
    w: 1020,
    h: 28,
    size: 18,
    color: C.navy,
    bold: true,
    align: "center",
  });
  addSourceNote(slide, "Source: related work chapter, asynchronous submodel coverage mismatch.");
  await addFooter(slide, ctx, 8, "method: FedCover coverage mismatch");
}

async function fedcoverMechanismSlide(slide, ctx) {
  addHeader(slide, "FedCover", "FedCover Coverage Correction");
  await addImageContained(slide, ctx, "figures_svg/fedcover_coverage_gain.svg", {
    x: 70,
    y: 142,
    w: 1140,
    h: 336,
    alt: "FedCover coverage mass and capped inverse-coverage gain",
  });

  addShape(slide, { x: 70, y: 500, w: 1140, h: 126, fill: "#f1f5f9", outline: "none", radius: 7 });
  addText(slide, "Server-side correction", { x: 92, y: 512, w: 220, h: 22, size: 16, color: C.navy, bold: true });
  addText(slide, "Scale only covered deltas; do not impute missing updates.", {
    x: 292,
    y: 514,
    w: 850,
    h: 18,
    size: PPT_11PT_SIZE,
    color: C.navy,
    bold: true,
    align: "right",
  });
  const eqCards = [
    ["stale-weighted buffer weight", "equations/fedcover_buffer_weight.svg"],
    ["observed coverage mass", "equations/fedcover_coverage_mass.svg"],
    ["capped coverage gain", "equations/fedcover_coverage_gain.svg"],
  ];
  for (let index = 0; index < eqCards.length; index += 1) {
    const [label, equationPath] = eqCards[index];
    const x = 92 + index * 368;
    addShape(slide, { x, y: 544, w: 340, h: 74, fill: C.panel, outline: `1px solid ${C.line}`, radius: 6 });
    addText(slide, label, { x: x + 18, y: 548, w: 304, h: 18, size: PPT_11PT_SIZE, color: C.teal, bold: true, align: "center" });
    await addImageAtNativeScale(slide, ctx, equationPath, {
      centerX: x + 170,
      centerY: 592,
      scale: 1.55,
      alt: `${label} equation`,
    });
  }
  addSourceNote(slide, "Source: implementation chapter, FedCover aggregation rule.");
  await addFooter(slide, ctx, 9, "method: FedCover coverage correction");
}

async function fedcoverFeasibilitySlide(slide, ctx) {
  addHeader(slide, "FedCover evidence", "FedCover Improves Time to Target");
  addEvalClaimBand(slide, "FedCover improves target time; the ablation links correction strength to speedup.", { accent: C.red });
  addSetupRibbon(slide, "A1/A2 | CIFAR-10/Fashion-MNIST | IID/non-IID | async submodel FL | target time + gamma sweep", { y: EVAL_SETUP_Y, accent: C.red });
  const rows = [
    ["CIFAR-10 IID", "24.2 ± 2.9", "33.9 ± 16.0", "13.7 ± 2.1"],
    ["CIFAR-10 non-IID", "51.6 ± 19.2†", "38.2 ± 9.1", "16.3 ± 0.3"],
    ["Fashion-MNIST IID", "12.9 ± 1.1", "11.8 ± 1.4", "6.0 ± 0.7"],
    ["Fashion-MNIST non-IID", "22.6 ± 2.8†", "20.5 ± 6.4†", "11.0 ± 2.3"],
  ];
  const x = 86;
  const y = 284;
  const colW = [142, 112, 136, 120];
  const headers = ["Task / data", "HeteroFL", "Async-HeteroFL", "FedCover gamma=1.5"];
  addShape(slide, { x: 70, y: 252, w: 555, h: 334, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  addText(slide, "Time to task-specific target (min)", { x, y: 258, w: 400, h: 22, size: EVAL_PANEL_TITLE_SIZE, color: C.navy, bold: true });
  let cursor = x;
  headers.forEach((h, i) => {
    addShape(slide, { x: cursor, y, w: colW[i], h: 36, fill: i === 0 ? C.navy : "#eef2f7", outline: "none", radius: i === 0 ? 5 : 0 });
    addText(slide, h, { x: cursor + 6, y: y + 9, w: colW[i] - 12, h: 18, size: i === 2 ? 10.2 : 10.8, color: i === 0 ? "#ffffff" : C.navy, bold: true, align: i === 0 ? "left" : "center" });
    cursor += colW[i] + 2;
  });
  rows.forEach((row, r) => {
    cursor = x;
    row.forEach((cell, c) => {
      const isFedCover = c === 3;
      const isLowerBound = String(cell).includes("†");
      const fill = c === 0 ? "#ffffff" : isFedCover ? "#eef7f5" : isLowerBound ? "#fff7ed" : "#f8fafc";
      const color = c === 0 ? C.ink : isFedCover ? C.teal : isLowerBound ? C.orange : C.navy;
      addShape(slide, { x: cursor, y: y + 40 + r * 42, w: colW[c], h: 38, fill, outline: `1px solid ${C.line}`, radius: 4 });
      addText(slide, cell, { x: cursor + 6, y: y + 50 + r * 42, w: colW[c] - 12, h: 18, size: c === 0 ? 11.2 : 11.8, color, bold: c > 0, align: c === 0 ? "left" : "center" });
      cursor += colW[c] + 2;
    });
  });
  addText(slide, "Among capacity-matched methods, FedCover reaches target fastest in all four settings.", {
    x: 86,
    y: 520,
    w: 500,
    h: 42,
    size: EVAL_CAPTION_SIZE,
    color: C.muted,
    align: "center",
    line: 1.12,
  });
  addText(slide, "† target not reached in all seeds", {
    x: 86,
    y: 560,
    w: 500,
    h: 18,
    size: 10.5,
    color: C.muted,
    align: "center",
  });
  addShape(slide, { x: 655, y: 252, w: 555, h: 334, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  addText(slide, "FedCover Correction-Strength Ablation", { x: 681, y: 258, w: 500, h: 22, size: EVAL_PANEL_TITLE_SIZE, color: C.navy, bold: true });
  await addImageContained(slide, ctx, "figures_svg/fedcover_post_warmup_speedup.svg", {
    x: 663,
    y: 282,
    w: 538,
    h: 258,
    alt: "FedCover post-warm-up speedup over Async-HeteroFL",
  });
  addText(slide, "Speedup generally grows with correction strength, supporting coverage correction as the mechanism.", {
    x: 681,
    y: 548,
    w: 503,
    h: 32,
    size: EVAL_CAPTION_SIZE,
    color: C.muted,
    align: "center",
    line: 1.12,
  });
  addSourceNote(slide, "Sources: evaluation chapter, Table 5.10 and Figure 5.17; all FedCover rows use kappa_max=3.");
  await addFooter(slide, ctx, 13, "A1-A2: FedCover target-time evidence");
}

async function conclusionSlide(slide, ctx) {
  addShape(slide, { x: 0, y: 0, w: W, h: 84, fill: C.navy });
  addText(slide, "Conclusions", { x: 76, y: 28, w: 500, h: 38, size: 32, color: "#ffffff", bold: true });
  addShape(slide, { x: 90, y: 98, w: 1060, h: 58, fill: "#eef7f5", outline: `1px solid ${C.line}`, radius: 7 });
  addShape(slide, { x: 90, y: 98, w: 8, h: 58, fill: C.teal, radius: 4 });
  addText(slide, "Heterogeneous FL must be evaluated through both model performance and deployment behaviour.", {
    x: 118,
    y: 108,
    w: 1000,
    h: 42,
    size: 18,
    color: C.navy,
    bold: true,
    align: "center",
  });
  const claims = [
    ["Deployment-aware evaluation", "Compute and straggler-induced heterogeneity create trade-offs between wall-clock time, participation, submodel quality, and fairness."],
    ["fedctl contribution", "Repeatable Flower-to-Nomad runs preserve run/deploy configs, typed placement, network profiles, logs, metrics, and artefacts."],
    ["FedCover contribution", "Async submodel FL is feasible, but stale partial replies make parameter coverage an aggregation variable; capped inverse coverage improves time to target."],
  ];
  claims.forEach(([title, body], i) => {
    const y = 166 + i * 112;
    addShape(slide, { x: 92, y, w: 752, h: 100, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
    addShape(slide, { x: 92, y, w: 8, h: 100, fill: i === 0 ? C.teal : i === 1 ? C.gold : C.red, radius: 4 });
    addText(slide, title, { x: 122, y: y + 14, w: 220, h: 42, size: 18, color: C.navy, bold: true });
    addText(slide, body, { x: 362, y: y + 14, w: 474, h: 64, size: 15.5, color: C.ink, line: 1.08 });
  });
  addShape(slide, { x: 890, y: 166, w: 250, h: 312, fill: "#f1f5f9", outline: "none", radius: 7 });
  addText(slide, "Future work", { x: 915, y: 190, w: 200, h: 32, size: 21, color: C.navy, bold: true, align: "center" });
  addBullets(slide, [
    "Broader workloads, devices, and runtimes.",
    "Representation-aware async training.",
    "Hardware-aware sparse submodel execution.",
    "Trace-driven straggler evaluation.",
  ], { x: 918, y: 242, w: 198, size: PPT_11PT_SIZE, gap: 47 });
  addRule(slide, 70, 548, 1140, "#e6ebf3", 1);
  await addLogoRail(slide, ctx, 576);
}

async function appendixDividerSlide(slide, ctx) {
  addShape(slide, { x: 0, y: 0, w: W, h: 110, fill: C.navy });
  addShape(slide, { x: 0, y: 110, w: W, h: 8, fill: C.gold });
  addText(slide, "Appendix", { x: 82, y: 170, w: 500, h: 56, size: 42, color: C.navy, bold: true });
  addText(slide, "Backup evidence for Q&A", { x: 84, y: 238, w: 560, h: 34, size: 24, color: C.muted });
  addBullets(slide, [
    "fedctl queue, configuration, placement, and network-control diagrams.",
    "Full compute diagnostics for local submodels and client timing.",
    "Async staleness, update-share, device-correlated skew, and FedCover gamma evidence.",
  ], { x: 100, y: 330, w: 830, size: 21, gap: 56 });
  await addFooter(slide, ctx, 17, "appendix");
}

async function appendixQueueSlide(slide, ctx) {
  addAppendixHeader(slide, "Queue admission and dispatch", "Full systems lifecycle behind shared cluster execution.");
  addShape(slide, { x: 62, y: 168, w: 1156, h: 440, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  await addImageContained(slide, ctx, "figures_svg/queue_admission_dispatch_clean.svg", {
    x: 86,
    y: 188,
    w: 1108,
    h: 398,
    alt: "queue admission and dispatch path",
  });
  await addFooter(slide, ctx, 19, "appendix: queue admission and dispatch");
}

async function appendixConfigsSlide(slide, ctx) {
  addAppendixHeader(slide, "Run config and deploy config", "The split prevents method choices from being mixed with execution conditions.");
  addShape(slide, { x: 70, y: 180, w: 520, h: 376, fill: "#0f172a", outline: "none", radius: 7 });
  addText(slide, "run config", { x: 96, y: 204, w: 200, h: 24, size: 18, color: "#ffffff", bold: true });
  addText(slide, "[run]\nmethod = \"fedavg\"\ntask = \"fashion_mnist\"\nseed = 1337\n\n[server]\nnum-server-rounds = 20\n\n[client]\nlocal-epochs = 1\nlearning-rate = 0.01", {
    x: 96,
    y: 248,
    w: 440,
    h: 260,
    size: 16,
    color: "#dbeafe",
  });
  addShape(slide, { x: 690, y: 180, w: 520, h: 376, fill: "#0f172a", outline: "none", radius: 7 });
  addText(slide, "deploy config", { x: 716, y: 204, w: 220, h: 24, size: 18, color: "#ffffff", bold: true });
  addText(slide, "deploy:\n  supernodes:\n    rpi4: 10\n    rpi5: 10\n  placement:\n    spread_across_hosts: true\n  network:\n    default_profile: none\n    profiles:\n      mild:\n        delay_ms: 20\n        jitter_ms: 5", {
    x: 716,
    y: 248,
    w: 440,
    h: 260,
    size: 16,
    color: "#dbeafe",
  });
  await addFooter(slide, ctx, 20, "appendix: configuration surfaces");
}

async function appendixPlacementSlide(slide, ctx) {
  addAppendixHeader(slide, "Typed client placement", "Typed logical clients are tied back to device-labelled metrics.");
  addShape(slide, { x: 70, y: 168, w: 1140, h: 440, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  await addImageContained(slide, ctx, "figures_svg/device_placement_clean.svg", {
    x: 96,
    y: 188,
    w: 1088,
    h: 396,
    alt: "device-aware placement and metadata flow",
  });
  await addFooter(slide, ctx, 21, "appendix: device placement");
}

async function appendixNetworkSlide(slide, ctx) {
  addAppendixHeader(slide, "Network impairment", "netem profiles are deployment-side controls, not application-code changes.");
  addShape(slide, { x: 60, y: 168, w: 1160, h: 440, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  await addImageContained(slide, ctx, "figures_svg/network_impairment_clean.svg", {
    x: 82,
    y: 190,
    w: 1116,
    h: 394,
    alt: "network profile resolution and enforcement",
  });
  await addFooter(slide, ctx, 22, "appendix: network impairment");
}

async function appendixComputeDiagnosticsSlide(slide, ctx) {
  addAppendixHeader(slide, "Compute diagnostics", "Full thesis figures for local submodel quality and client timing.");
  addShape(slide, { x: 62, y: 168, w: 556, h: 224, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  await addImageContained(slide, ctx, "figures_svg/compute_main_cifar10_seed1340_local_submodel_grid.svg", {
    x: 82,
    y: 184,
    w: 516,
    h: 190,
    alt: "CIFAR-10 local submodel accuracy distributions",
  });
  addShape(slide, { x: 662, y: 168, w: 556, h: 224, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  await addImageContained(slide, ctx, "figures_svg/compute_main_cifar10_seed1340_client_train_time.svg", {
    x: 682,
    y: 184,
    w: 516,
    h: 190,
    alt: "CIFAR-10 client training time by device and model rate",
  });
  addShape(slide, { x: 126, y: 430, w: 1028, h: 78, fill: "#f1f5f9", outline: "none", radius: 7 });
  addText(slide, "Use this slide if asked whether the compute result is a global-score artifact. The left figure checks local submodel utility; the right figure shows which device/rate groups gate synchronous rounds.", {
    x: 164,
    y: 452,
    w: 950,
    h: 44,
    size: 17,
    color: C.navy,
    bold: true,
    align: "center",
  });
  await addFooter(slide, ctx, 21, "appendix: compute diagnostics");
}

async function appendixAsyncDiagnosticsSlide(slide, ctx) {
  addAppendixHeader(slide, "Asynchronous diagnostics", "Device-correlated skew separates update frequency from aggregate influence.");
  addShape(slide, { x: 62, y: 168, w: 1156, h: 300, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  await addImageContained(slide, ctx, "figures_svg/network_device_correlated.svg", {
    x: 88,
    y: 188,
    w: 1104,
    h: 256,
    alt: "device-correlated non-IID accuracy and device-share diagnostics",
  });
  addShape(slide, { x: 160, y: 506, w: 960, h: 72, fill: "#fff7ed", outline: "none", radius: 7 });
  addText(slide, "FedStaleWeight lifts rpi4 aggregate weight near population share, but rpi4 update share remains low and rpi4-held accuracy remains weak.", {
    x: 194,
    y: 520,
    w: 890,
    h: 40,
    size: 17,
    color: C.navy,
    bold: true,
    align: "center",
  });
  await addFooter(slide, ctx, 23, "appendix: async diagnostics and fairness");
}

async function appendixFedcoverSlide(slide, ctx) {
  addAppendixHeader(slide, "FedCover gamma sweep", "Full post-warm-up speedup figure with seed-level points.");
  addShape(slide, { x: 70, y: 168, w: 1140, h: 330, fill: C.panel, outline: `1px solid ${C.line}`, radius: 7 });
  await addImageContained(slide, ctx, "figures_svg/fedcover_post_warmup_speedup.svg", {
    x: 96,
    y: 188,
    w: 1088,
    h: 300,
    alt: "FedCover gamma sweep post-warm-up speedup",
  });
  addShape(slide, { x: 132, y: 530, w: 1016, h: 68, fill: "#f1f5f9", outline: "none", radius: 7 });
  addText(slide, "Across task-regime pairs, every gamma setting has positive mean post-warm-up speedup over uncorrected Async-HeteroFL; gamma=1.5 is strongest under non-IID data.", {
    x: 166,
    y: 542,
    w: 948,
    h: 42,
    size: 16,
    color: C.navy,
    bold: true,
    align: "center",
  });
  await addFooter(slide, ctx, 23, "appendix: FedCover gamma sweep");
}
