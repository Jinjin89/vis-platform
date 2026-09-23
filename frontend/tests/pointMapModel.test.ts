import { expect, test } from "vitest";
import type { PointView } from "../src/api/pinpoint";
import {
  boxBetween,
  buildIndex,
  countInBox,
  fitView,
  interleave,
  nearest,
  niceTicks,
  pointColors,
  project,
  tickLabel,
  unproject,
} from "../src/features/pinpoint/pointMapModel";

function view(overrides: Partial<PointView> = {}): PointView {
  return {
    title: "Tissue domains",
    count: 3,
    dropped: 0,
    x: { field: "x_px", title: "x", domain: [0, 200] },
    y: { field: "y_px", title: "y", domain: [0, 100], direction: "down" },
    equal_aspect: true,
    color: {
      type: "categorical",
      field: "domain",
      title: "Domain",
      categories: [
        { value: "Cortex", color: "#ff0000" },
        { value: "Medulla", color: "#00ff00" },
      ],
      missing_color: "#bdbdbd",
    },
    columns: ["x", "y", "color"],
    point_size: 0.8,
    opacity: 1,
    image: null,
    links: { columns: "/columns", image: null },
    ...overrides,
  };
}

const columns = {
  x: new Float32Array([10, 50, 150]),
  y: new Float32Array([10, 60, 90]),
  color: new Float32Array([1, 0, NaN]),
};

test("points take the saved figure's colours, grey when missing", () => {
  expect(Array.from(pointColors(view(), columns))).toEqual([
    0, 255, 0, 255, 255, 0, 0, 255, 189, 189, 189, 255,
  ]);
  const scale = pointColors(
    view({
      color: {
        type: "continuous",
        field: "marker",
        title: "Marker",
        domain: [0, 2],
        stops: ["#000000", "#ffffff"],
      },
    }),
    { ...columns, color: new Float32Array([0, 1, 2]) },
  );
  expect(Array.from(scale.slice(0, 12))).toEqual([
    0, 0, 0, 255, 128, 128, 128, 255, 255, 255, 255, 255,
  ]);
  expect(Array.from(interleave(columns.x, columns.y))).toEqual([
    10, 10, 50, 60, 150, 90,
  ]);
});

test("a dragged box counts the points inside it", () => {
  const box = boxBetween([160, 100], [0, 50]);
  expect(box).toEqual({ x_from: 0, x_to: 160, y_from: 50, y_to: 100 });
  expect(countInBox(columns, box)).toBe(2);
});

test("the map fits its window and screen positions round-trip", () => {
  const camera = fitView(view(), 400, 400);
  expect(camera.target).toEqual([100, 50]);
  // One scale for both axes: the wider x domain decides.
  expect(camera.zoomX).toBe(camera.zoomY);
  expect(2 ** camera.zoomX).toBe(2);
  const size = { width: 400, height: 400 };
  // With y downward, larger y is lower on screen.
  expect(project(camera, size, true, [100, 100])).toEqual([200, 300]);
  expect(project(camera, size, false, [100, 100])).toEqual([200, 100]);
  expect(unproject(camera, size, true, [0, 300])).toEqual([0, 100]);
  const stretched = fitView(view({ equal_aspect: false }), 400, 400);
  expect(2 ** stretched.zoomY).toBe(4);
});

test("ticks match the saved figure's", () => {
  expect(niceTicks(-40, 2040)).toEqual([0, 500, 1000, 1500, 2000]);
  expect(niceTicks(0.013, 0.087, 4)).toEqual([0.02, 0.04, 0.06, 0.08]);
  expect(tickLabel(0.04, [0.02, 0.04])).toBe("0.04");
  expect(tickLabel(-0, [0, 500])).toBe("0");
});

test("the point under the pointer is found through the grid, preferring the top one", () => {
  const index = buildIndex(view(), columns, 8);
  expect(nearest(index, [52, 58], 5, 5)).toBe(1);
  expect(nearest(index, [80, 30], 5, 5)).toBe(-1);
  // An ellipse follows unequal axis scales.
  expect(nearest(index, [60, 60], 5, 5)).toBe(-1);
  expect(nearest(index, [60, 60], 11, 5)).toBe(1);
  const stacked = buildIndex(view({ count: 3 }), {
    x: new Float32Array([5, 5, 5]),
    y: new Float32Array([5, 5, 5]),
  });
  expect(nearest(stacked, [5, 5], 1, 1)).toBe(2);
  // Many points: the grid answers the same as looking at every point.
  const count = 50_000;
  const x = Float32Array.from({ length: count }, (_, i) => (i * 7919) % 200);
  const y = Float32Array.from({ length: count }, (_, i) => (i * 104729) % 100);
  const large = buildIndex(view({ count }), { x, y });
  for (const probe of [
    [13.3, 71.1],
    [150, 2],
    [199, 99],
  ] as [number, number][]) {
    let expected = -1;
    let best = 1;
    for (let i = 0; i < count; i += 1) {
      const d = ((x[i]! - probe[0]) / 2) ** 2 + ((y[i]! - probe[1]) / 2) ** 2;
      if (d < best || (d === best && i > expected)) [expected, best] = [i, d];
    }
    expect(nearest(large, probe, 2, 2)).toBe(expected);
  }
});
