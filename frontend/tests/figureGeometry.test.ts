import { describe, expect, it } from "vitest";
import {
  figureContentSchema,
  figureDocumentSchema,
  type FigureDocument,
} from "../src/api/schemas/figureCompositions";
import {
  PAGE_PRESETS,
  align,
  clampMove,
  clampScale,
  distribute,
  imageNaturalSize,
  newPanelId,
  placeNewPanel,
  placeNewSlot,
  presetId,
  round,
  snapFrame,
  snapTargets,
} from "../src/features/figures/figureGeometry";
import { legendText } from "../src/features/figures/FigureLegendEditor";

const page = PAGE_PRESETS[1]!.page;
const frame = (x: number, y: number, width: number, height: number) => ({
  x_mm: x,
  y_mm: y,
  width_mm: width,
  height_mm: height,
});

function document(
  panels: { id: string; frame: ReturnType<typeof frame>; label?: string }[],
): FigureDocument {
  return figureDocumentSchema.parse({
    schema_version: "1.0",
    composition_id: "figure",
    project_id: "project",
    title: "Figure 2",
    revision: 1,
    created_at: "2026-09-21T00:00:00Z",
    updated_at: "2026-09-21T00:00:00Z",
    page_height_mm: 150,
    content: {
      title: "Figure 2",
      page,
      panels: panels.map((panel) => ({
        id: panel.id,
        content: { type: "plot", version_id: `v-${panel.id}` },
        x_mm: panel.frame.x_mm,
        y_mm: panel.frame.y_mm,
      })),
      legend: {
        title: "Treated samples.",
        entries: Object.fromEntries(
          panels.map((panel) => [panel.id, `Panel ${panel.id} text.`]),
        ),
      },
    },
    panels: Object.fromEntries(
      panels.map((panel) => [
        panel.id,
        {
          label: panel.label ?? null,
          frame: panel.frame,
          natural_width_mm: panel.frame.width_mm,
          natural_height_mm: panel.frame.height_mm,
        },
      ]),
    ),
    figures: {},
    images: {},
  });
}

describe("figure contracts", () => {
  it("applies defaults and rejects inconsistent content", () => {
    const content = figureContentSchema.parse({ title: "Figure", page });
    expect(content.labels.case).toBe("upper");
    expect(content.panels).toEqual([]);
    expect(
      figureContentSchema.safeParse({
        title: "Figure",
        page,
        legend: { entries: { missing: "text" } },
      }).success,
    ).toBe(false);
    expect(
      figureContentSchema.safeParse({
        title: "Figure",
        page: { ...page, margin_mm: 200 },
      }).success,
    ).toBe(false);
  });
  it("recognises presets and custom pages", () => {
    expect(presetId(page)).toBe("a4-width");
    expect(presetId({ ...page, width_mm: 150 })).toBe("custom");
  });
});

describe("figure geometry", () => {
  it("snaps the nearest edge or centre within the threshold", () => {
    const targets = snapTargets(page, 150, [frame(100, 10, 50, 40)]);
    const snapped = snapFrame(frame(51.2, 11, 45, 30), targets, 2);
    // The right edge (96.2) snaps to the gutter before the other panel (96).
    expect(snapped.dx).toBeCloseTo(-0.2);
    expect(snapped.guides.x).toBe(96);
    expect(snapped.dy).toBeCloseTo(-1);
    expect(snapFrame(frame(30, 60, 10, 10), targets, 1).guides).toEqual({
      x: null,
      y: null,
    });
  });
  it("keeps group moves and scales on the page", () => {
    expect(
      clampMove([frame(5, 5, 50, 50), frame(150, 5, 50, 50)], 20, -10, page),
    ).toEqual({ dx: 10, dy: -5 });
    const natural = { width: 100, height: 50 };
    expect(
      clampScale({ x_mm: 150, y_mm: 0, scale: 1 }, natural, page, 2),
    ).toBeCloseTo(0.6);
    expect(clampScale({ x_mm: 0, y_mm: 0, scale: 1 }, natural, page, 0)).toBe(
      0.05,
    );
  });
  it("aligns and distributes selected panels", () => {
    const frames = {
      a: frame(10, 10, 40, 20),
      b: frame(70, 30, 20, 40),
      c: frame(150, 20, 30, 30),
    };
    expect(align(frames, "left").b).toEqual({ x_mm: 10, y_mm: 30 });
    expect(align(frames, "bottom").a).toEqual({ x_mm: 10, y_mm: 50 });
    expect(align(frames, "middle").c!.y_mm).toBeCloseTo(25);
    const spaced = distribute(frames, "x");
    expect(spaced.a!.x_mm).toBe(10);
    expect(spaced.c!.x_mm).toBe(150);
    // Gaps: (180 - 10 - 90) / 2 = 40 mm.
    expect(spaced.b!.x_mm).toBe(90);
  });
  it("places new content in the first free spot", () => {
    const natural = { width: 203.2, height: 139.7 };
    const empty = placeNewPanel(document([]), natural);
    expect(empty).toMatchObject({ x_mm: 5, y_mm: 5 });
    expect(empty.scale * natural.width).toBeLessThanOrEqual(200);
    const beside = placeNewPanel(
      document([{ id: "a", frame: frame(5, 5, 98, 67) }]),
      natural,
    );
    expect(beside.x_mm).toBe(107);
    expect(beside.y_mm).toBe(5);
    const below = placeNewPanel(
      document([
        { id: "a", frame: frame(5, 5, 98, 67) },
        { id: "b", frame: frame(107, 5, 98, 67) },
      ]),
      natural,
    );
    expect(below).toMatchObject({ x_mm: 5, y_mm: 76 });
  });
  it("shrinks a new slot into the space left on the page", () => {
    expect(placeNewSlot(document([]))).toEqual({
      x_mm: 5,
      y_mm: 5,
      scale: 1,
      width: 90,
      height: 67,
    });
    // Only 66 mm remain below these panels on a 297 mm page.
    const full = document([
      { id: "a", frame: frame(5, 5, 200, 142) },
      { id: "b", frame: frame(5, 151, 98, 71) },
      { id: "c", frame: frame(107, 151, 98, 71) },
    ]);
    expect(placeNewSlot(full)).toEqual({
      x_mm: 5,
      y_mm: 226,
      scale: 1,
      width: 90,
      height: 66,
    });
  });
  it("numbers new panels without repeating an ID", () => {
    expect(newPanelId(document([]))).toBe("panel-1");
    const used = document([
      { id: "panel-1", frame: frame(5, 5, 50, 50) },
      { id: "umap", frame: frame(60, 5, 50, 50) },
      { id: "panel-3", frame: frame(115, 5, 50, 50) },
    ]);
    expect(newPanelId(used)).toBe("panel-2");
    expect(newPanelId(used)).toBe("panel-2");
  });
  it("rounds to steps without floating-point residue", () => {
    expect(round(27.9)).toBe(27.9);
    expect(String(round(27.9000000001))).toBe("27.9");
    expect(round(0.41584, 0.001)).toBe(0.416);
    expect(round(12.5, 0.5)).toBe(12.5);
  });
  it("places uploaded images at print resolution", () => {
    expect(imageNaturalSize({ width: 600, height: 300 })).toEqual({
      width: 50.8,
      height: 25.4,
    });
  });
});

describe("figure legend", () => {
  it("orders entries by panel label", () => {
    const text = legendText(
      document([
        { id: "b", frame: frame(100, 5, 50, 50), label: "B" },
        { id: "a", frame: frame(5, 5, 50, 50), label: "A" },
      ]),
    );
    expect(text).toBe(
      "Figure 2. Treated samples. (A) Panel a text. (B) Panel b text.",
    );
  });
});
