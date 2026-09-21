import type {
  FigureDocument,
  FigurePage,
  PanelFrame,
  PanelGeometry,
} from "../../api/schemas/figureCompositions";
import type { PlotResult } from "../../api/schemas/plotRun";

export const MM_PER_INCH = 25.4;
export const MM_PER_POINT = MM_PER_INCH / 72;
/** CSS pixels per millimetre at 100% zoom. */
export const PX_PER_MM = 96 / MM_PER_INCH;
const IMAGE_DPI = 300;
const GUTTER_MM = 4;
const MIN_SCALE = 0.05;

export type Size = { width: number; height: number };
export type Guides = { x: number | null; y: number | null };

export const PAGE_PRESETS: { id: string; label: string; page: FigurePage }[] = [
  {
    id: "a4-page",
    label: "A4 page (210 × 297 mm)",
    page: { width_mm: 210, height_mm: 297, height_mode: "fixed", margin_mm: 5 },
  },
  {
    id: "a4-width",
    label: "A4 width, auto height",
    page: { width_mm: 210, height_mm: 297, height_mode: "auto", margin_mm: 5 },
  },
  {
    id: "single-column",
    label: "Single column (89 mm)",
    page: { width_mm: 89, height_mm: 297, height_mode: "auto", margin_mm: 3 },
  },
  {
    id: "one-half-column",
    label: "1.5 column (120 mm)",
    page: { width_mm: 120, height_mm: 297, height_mode: "auto", margin_mm: 4 },
  },
  {
    id: "double-column",
    label: "Double column (183 mm)",
    page: { width_mm: 183, height_mm: 297, height_mode: "auto", margin_mm: 5 },
  },
];

export function presetId(page: FigurePage): string {
  return (
    PAGE_PRESETS.find(
      (preset) =>
        preset.page.width_mm === page.width_mm &&
        preset.page.height_mm === page.height_mm &&
        preset.page.height_mode === page.height_mode,
    )?.id ?? "custom"
  );
}

/** Round to a step without binary floating-point residue (27.9, not 27.900000000000002). */
export function round(value: number, step = 0.1): number {
  const decimals = Math.max(0, Math.ceil(-Math.log10(step)));
  return Number((Math.round(value / step) * step).toFixed(decimals));
}

export function plotNaturalSize(figure: PlotResult | undefined): Size | null {
  const size = figure?.figure_size;
  return size
    ? { width: size.width * MM_PER_INCH, height: size.height * MM_PER_INCH }
    : null;
}

export function imageNaturalSize(image: Size): Size {
  return {
    width: (image.width / IMAGE_DPI) * MM_PER_INCH,
    height: (image.height / IMAGE_DPI) * MM_PER_INCH,
  };
}

export function frameAt(geometry: PanelGeometry, natural: Size): PanelFrame {
  return {
    x_mm: geometry.x_mm,
    y_mm: geometry.y_mm,
    width_mm: natural.width * geometry.scale,
    height_mm: natural.height * geometry.scale,
  };
}

/** The largest scale that keeps a panel inside the page from its position. */
export function maxScale(
  geometry: PanelGeometry,
  natural: Size,
  page: FigurePage,
): number {
  return Math.min(
    10,
    (page.width_mm - geometry.x_mm) / natural.width,
    (page.height_mm - geometry.y_mm) / natural.height,
  );
}

export function clampScale(
  geometry: PanelGeometry,
  natural: Size,
  page: FigurePage,
  scale: number,
): number {
  return Math.max(
    MIN_SCALE,
    Math.min(maxScale(geometry, natural, page), round(scale, 0.001)),
  );
}

/** Snap lines: page edges, margins and centre, and the edges and centres of other panels. */
export function snapTargets(
  page: FigurePage,
  pageHeight: number,
  others: PanelFrame[],
): { x: number[]; y: number[] } {
  const margin = page.margin_mm;
  return {
    x: [
      0,
      margin,
      page.width_mm / 2,
      page.width_mm - margin,
      page.width_mm,
      ...others.flatMap((f) => [
        f.x_mm,
        f.x_mm + f.width_mm / 2,
        f.x_mm + f.width_mm,
        f.x_mm - GUTTER_MM,
        f.x_mm + f.width_mm + GUTTER_MM,
      ]),
    ],
    y: [
      0,
      margin,
      pageHeight - margin,
      ...others.flatMap((f) => [
        f.y_mm,
        f.y_mm + f.height_mm / 2,
        f.y_mm + f.height_mm,
        f.y_mm - GUTTER_MM,
        f.y_mm + f.height_mm + GUTTER_MM,
      ]),
    ],
  };
}

function nearest(edges: number[], targets: number[], threshold: number) {
  let best: { delta: number; line: number } | null = null;
  for (const edge of edges)
    for (const line of targets) {
      const delta = line - edge;
      if (
        Math.abs(delta) <= threshold &&
        (!best || Math.abs(delta) < Math.abs(best.delta))
      )
        best = { delta, line };
    }
  return best;
}

/** Move a frame so its nearest edge or centre lands on a snap line within the threshold. */
export function snapFrame(
  frame: PanelFrame,
  targets: { x: number[]; y: number[] },
  threshold: number,
): { dx: number; dy: number; guides: Guides } {
  const x = nearest(
    [frame.x_mm, frame.x_mm + frame.width_mm / 2, frame.x_mm + frame.width_mm],
    targets.x,
    threshold,
  );
  const y = nearest(
    [
      frame.y_mm,
      frame.y_mm + frame.height_mm / 2,
      frame.y_mm + frame.height_mm,
    ],
    targets.y,
    threshold,
  );
  return {
    dx: x?.delta ?? 0,
    dy: y?.delta ?? 0,
    guides: { x: x?.line ?? null, y: y?.line ?? null },
  };
}

export function bounds(frames: PanelFrame[]): PanelFrame {
  const left = Math.min(...frames.map((f) => f.x_mm));
  const top = Math.min(...frames.map((f) => f.y_mm));
  const right = Math.max(...frames.map((f) => f.x_mm + f.width_mm));
  const bottom = Math.max(...frames.map((f) => f.y_mm + f.height_mm));
  return {
    x_mm: left,
    y_mm: top,
    width_mm: right - left,
    height_mm: bottom - top,
  };
}

/** Limit a group move so every frame remains on the page. */
export function clampMove(
  frames: PanelFrame[],
  dx: number,
  dy: number,
  page: FigurePage,
): { dx: number; dy: number } {
  const box = bounds(frames);
  return {
    dx: Math.min(
      Math.max(dx, -box.x_mm),
      page.width_mm - box.x_mm - box.width_mm,
    ),
    dy: Math.min(
      Math.max(dy, -box.y_mm),
      page.height_mm - box.y_mm - box.height_mm,
    ),
  };
}

export type Alignment =
  "left" | "center" | "right" | "top" | "middle" | "bottom";

export function align(
  frames: Record<string, PanelFrame>,
  alignment: Alignment,
): Record<string, { x_mm: number; y_mm: number }> {
  const box = bounds(Object.values(frames));
  const result: Record<string, { x_mm: number; y_mm: number }> = {};
  for (const [id, f] of Object.entries(frames)) {
    const x = {
      left: box.x_mm,
      center: box.x_mm + (box.width_mm - f.width_mm) / 2,
      right: box.x_mm + box.width_mm - f.width_mm,
    };
    const y = {
      top: box.y_mm,
      middle: box.y_mm + (box.height_mm - f.height_mm) / 2,
      bottom: box.y_mm + box.height_mm - f.height_mm,
    };
    result[id] = {
      x_mm: round(alignment in x ? x[alignment as keyof typeof x] : f.x_mm),
      y_mm: round(alignment in y ? y[alignment as keyof typeof y] : f.y_mm),
    };
  }
  return result;
}

/** Keep the outer panels fixed and make the gaps between neighbours equal. */
export function distribute(
  frames: Record<string, PanelFrame>,
  axis: "x" | "y",
): Record<string, { x_mm: number; y_mm: number }> {
  const start = axis === "x" ? "x_mm" : "y_mm";
  const size = axis === "x" ? "width_mm" : "height_mm";
  const ordered = Object.entries(frames).sort(
    (a, b) => a[1][start] - b[1][start],
  );
  const first = ordered[0]![1];
  const last = ordered.at(-1)![1];
  const occupied = ordered.reduce((sum, [, f]) => sum + f[size], 0);
  const gap =
    (last[start] + last[size] - first[start] - occupied) /
    Math.max(ordered.length - 1, 1);
  const result: Record<string, { x_mm: number; y_mm: number }> = {};
  let cursor = first[start];
  for (const [id, f] of ordered) {
    result[id] = {
      x_mm: round(axis === "x" ? cursor : f.x_mm),
      y_mm: round(axis === "y" ? cursor : f.y_mm),
    };
    cursor += f[size] + gap;
  }
  return result;
}

function overlaps(a: PanelFrame, b: PanelFrame): boolean {
  return (
    a.x_mm < b.x_mm + b.width_mm &&
    b.x_mm < a.x_mm + a.width_mm &&
    a.y_mm < b.y_mm + b.height_mm &&
    b.y_mm < a.y_mm + a.height_mm
  );
}

/**
 * Place new content at the first free spot in reading order, sized to at most half the
 * printable width so a second panel can sit beside it.
 */
export function placeNewPanel(
  document: FigureDocument,
  natural: Size,
): PanelGeometry {
  const page = document.content.page;
  const margin = page.margin_mm;
  const printable = page.width_mm - 2 * margin;
  const frames = Object.values(document.panels).map((panel) => panel.frame);
  // Round down so two half-width panels always fit side by side.
  const scale = Math.max(
    MIN_SCALE,
    Math.floor(
      Math.min(
        1,
        (printable - GUTTER_MM) / 2 / natural.width,
        (page.height_mm - 2 * margin) / natural.height,
      ) * 1000,
    ) / 1000,
  );
  const width = natural.width * scale;
  const height = natural.height * scale;
  const candidates = [
    { x_mm: margin, y_mm: margin },
    ...frames.flatMap((f) => [
      { x_mm: f.x_mm + f.width_mm + GUTTER_MM, y_mm: f.y_mm },
      { x_mm: margin, y_mm: f.y_mm + f.height_mm + GUTTER_MM },
    ]),
  ].sort((a, b) => a.y_mm - b.y_mm || a.x_mm - b.x_mm);
  const free = candidates.find((spot) => {
    const frame = { ...spot, width_mm: width, height_mm: height };
    return (
      spot.x_mm + width <= page.width_mm - margin + 0.01 &&
      spot.y_mm + height <= page.height_mm - margin + 0.01 &&
      frames.every((other) => !overlaps(frame, other))
    );
  });
  const spot = free ?? { x_mm: margin, y_mm: margin };
  return { x_mm: round(spot.x_mm), y_mm: round(spot.y_mm), scale };
}
