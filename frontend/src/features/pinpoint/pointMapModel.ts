import type {
  PointColumns,
  PointView,
  SelectionMark,
} from "../../api/pinpoint";

export type { PointColumns };
export type Box = Pick<SelectionMark, "x_from" | "x_to" | "y_from" | "y_to">;

const DEFAULT_COLOR = "#1f77b4";

function rgb(hex: string): [number, number, number] {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

/** x and y side by side, as the GPU reads positions. */
export function interleave(x: Float32Array, y: Float32Array): Float32Array {
  const positions = new Float32Array(x.length * 2);
  for (let index = 0; index < x.length; index += 1) {
    positions[index * 2] = x[index]!;
    positions[index * 2 + 1] = y[index]!;
  }
  return positions;
}

/** One RGBA colour per point, the same colours as the saved figure. */
export function pointColors(
  view: PointView,
  columns: PointColumns,
): Uint8Array {
  const colors = new Uint8Array(view.count * 4);
  const values = columns.color;
  const color = view.color;
  const plain = rgb(DEFAULT_COLOR);
  const categories =
    color?.type === "categorical"
      ? color.categories.map((item) => rgb(item.color))
      : [];
  const missing =
    color?.type === "categorical" ? rgb(color.missing_color) : [189, 189, 189];
  const stops = color?.type === "continuous" ? color.stops.map(rgb) : [];
  for (let index = 0; index < view.count; index += 1) {
    let value: [number, number, number] | number[] = plain;
    if (color && values) {
      const raw = values[index]!;
      if (Number.isNaN(raw)) value = missing;
      else if (color.type === "categorical") value = categories[raw] ?? missing;
      else value = ramp(stops, color.domain, raw);
    }
    colors.set([value[0]!, value[1]!, value[2]!, 255], index * 4);
  }
  return colors;
}

function ramp(
  stops: [number, number, number][],
  [low, high]: [number, number],
  value: number,
): [number, number, number] {
  const share =
    high > low ? Math.min(1, Math.max(0, (value - low) / (high - low))) : 0;
  const position = share * (stops.length - 1);
  const lower = Math.min(Math.floor(position), stops.length - 2);
  const weight = position - lower;
  const [a, b] = [stops[lower]!, stops[lower + 1]!];
  return [0, 1, 2].map((channel) =>
    Math.round(a[channel]! * (1 - weight) + b[channel]! * weight),
  ) as [number, number, number];
}

/** How many points fall in a box, for feedback while selecting. */
export function countInBox(columns: PointColumns, box: Box): number {
  const { x, y } = columns;
  let count = 0;
  for (let index = 0; index < x.length; index += 1) {
    const px = x[index]!;
    const py = y[index]!;
    if (
      px >= box.x_from &&
      px <= box.x_to &&
      py >= box.y_from &&
      py <= box.y_to
    )
      count += 1;
  }
  return count;
}

/** The view that shows the whole map in a width × height area. */
export function fitView(
  view: PointView,
  width: number,
  height: number,
): MapCamera {
  const [x0, x1] = view.x.domain;
  const [y0, y1] = view.y.domain;
  const zoomX = Math.log2(Math.max(1, width) / (x1 - x0));
  const zoomY = Math.log2(Math.max(1, height) / (y1 - y0));
  const equal = Math.min(zoomX, zoomY);
  return {
    target: [(x0 + x1) / 2, (y0 + y1) / 2],
    zoomX: view.equal_aspect ? equal : zoomX,
    zoomY: view.equal_aspect ? equal : zoomY,
  };
}

/** Round tick values between low and high, as on the saved figure. */
export function niceTicks(low: number, high: number, count = 5): number[] {
  const span = high - low;
  if (!Number.isFinite(span) || span <= 0) return [low];
  let step = 10 ** Math.floor(Math.log10(span / count));
  const error = span / count / step;
  step *= error >= 7.5 ? 10 : error >= 3.5 ? 5 : error >= 1.5 ? 2 : 1;
  const first = Math.ceil(low / step - 1e-9) * step;
  const ticks = [];
  for (let value = first; value <= high + step * 1e-9; value += step)
    ticks.push(Number(value.toPrecision(12)));
  return ticks;
}

export function tickLabel(value: number, ticks: number[]): string {
  const step = ticks.length > 1 ? Math.abs(ticks[1]! - ticks[0]!) : 1;
  const decimals = Math.max(0, -Math.floor(Math.log10(step)));
  const text = value.toFixed(decimals);
  return Number(text) === 0 ? "0" : text;
}

/** A dragged box in data units, from its two corners. */
export function boxBetween(a: [number, number], b: [number, number]): Box {
  return {
    x_from: Math.min(a[0], b[0]),
    x_to: Math.max(a[0], b[0]),
    y_from: Math.min(a[1], b[1]),
    y_to: Math.max(a[1], b[1]),
  };
}

/** Where the map is looking: its centre and zoom per axis (2^zoom pixels per data unit). */
export type MapCamera = {
  target: [number, number];
  zoomX: number;
  zoomY: number;
};
export type Size = { width: number; height: number };

/** Screen position of a data point; y grows downward on screen when `down` is set. */
export function project(
  camera: MapCamera,
  size: Size,
  down: boolean,
  [x, y]: [number, number],
): [number, number] {
  return [
    size.width / 2 + (x - camera.target[0]) * 2 ** camera.zoomX,
    size.height / 2 +
      (y - camera.target[1]) * 2 ** camera.zoomY * (down ? 1 : -1),
  ];
}

export function unproject(
  camera: MapCamera,
  size: Size,
  down: boolean,
  [px, py]: [number, number],
): [number, number] {
  return [
    camera.target[0] + (px - size.width / 2) / 2 ** camera.zoomX,
    camera.target[1] +
      ((py - size.height / 2) / 2 ** camera.zoomY) * (down ? 1 : -1),
  ];
}

/**
 * Points sorted into a grid over the data window, so the point under the pointer is found by
 * looking at a few nearby cells instead of every point, and without a GPU read.
 */
export type PointIndex = {
  x: Float32Array;
  y: Float32Array;
  x0: number;
  y0: number;
  cellWidth: number;
  cellHeight: number;
  columns: number;
  rows: number;
  /** Points of cell c are order[starts[c]] up to order[starts[c + 1]]. */
  starts: Uint32Array;
  order: Uint32Array;
};

export function buildIndex(
  view: PointView,
  columns: PointColumns,
  cells = 256,
): PointIndex {
  const { x, y } = columns;
  const [x0, x1] = view.x.domain;
  const [y0, y1] = view.y.domain;
  const cellWidth = (x1 - x0) / cells || 1;
  const cellHeight = (y1 - y0) / cells || 1;
  const cellOf = new Uint32Array(x.length);
  const counts = new Uint32Array(cells * cells + 1);
  for (let index = 0; index < x.length; index += 1) {
    const column = Math.min(
      cells - 1,
      Math.max(0, Math.floor((x[index]! - x0) / cellWidth)),
    );
    const row = Math.min(
      cells - 1,
      Math.max(0, Math.floor((y[index]! - y0) / cellHeight)),
    );
    const cell = row * cells + column;
    cellOf[index] = cell;
    counts[cell + 1]! += 1;
  }
  for (let cell = 1; cell < counts.length; cell += 1)
    counts[cell]! += counts[cell - 1]!;
  const starts = counts.slice();
  const fill = counts.slice(0, -1);
  const order = new Uint32Array(x.length);
  for (let index = 0; index < x.length; index += 1)
    order[fill[cellOf[index]!]!++] = index;
  return {
    x,
    y,
    x0,
    y0,
    cellWidth,
    cellHeight,
    columns: cells,
    rows: cells,
    starts,
    order,
  };
}

/**
 * The point nearest [px, py] within an ellipse of radii rx, ry (data units), or -1. Among
 * equally near points, the one drawn last (on top) wins.
 */
export function nearest(
  index: PointIndex,
  [px, py]: [number, number],
  rx: number,
  ry: number,
): number {
  const cell = (value: number, origin: number, size: number, limit: number) =>
    Math.min(limit - 1, Math.max(0, Math.floor((value - origin) / size)));
  const [c0, c1] = [
    cell(px - rx, index.x0, index.cellWidth, index.columns),
    cell(px + rx, index.x0, index.cellWidth, index.columns),
  ];
  const [r0, r1] = [
    cell(py - ry, index.y0, index.cellHeight, index.rows),
    cell(py + ry, index.y0, index.cellHeight, index.rows),
  ];
  let best = -1;
  let bestDistance = 1;
  for (let row = r0; row <= r1; row += 1)
    for (let column = c0; column <= c1; column += 1) {
      const cellIndex = row * index.columns + column;
      for (
        let slot = index.starts[cellIndex]!;
        slot < index.starts[cellIndex + 1]!;
        slot += 1
      ) {
        const point = index.order[slot]!;
        const dx = (index.x[point]! - px) / rx;
        const dy = (index.y[point]! - py) / ry;
        const distance = dx * dx + dy * dy;
        if (
          distance < bestDistance ||
          (distance === bestDistance && point > best)
        ) {
          best = point;
          bestDistance = distance;
        }
      }
    }
  return best;
}
