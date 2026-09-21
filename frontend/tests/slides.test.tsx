import { describe, expect, it } from "vitest";
import { defaultFrames } from "../src/features/slides/SlideCanvas";
import {
  reportContentSchema,
  slideFrameSchema,
  type ReportSection,
} from "../src/api/schemas/reports";
import { slideDeckSchema } from "../src/api/slides";

describe("slide layout and import contracts", () => {
  it.each([
    "title",
    "figure-summary",
    "two-column",
    "statement",
    "table",
  ] as const)("keeps %s layout elements inside the slide", (layout) => {
    const section: ReportSection = {
      id: "s",
      title: "Findings",
      level: 1,
      parent_id: null,
      slide: { layout, notes: "", frames: {} },
      blocks: [
        {
          id: "f",
          type: "figure",
          version_id: "v1",
          image_id: null,
          caption: "",
        },
        { id: "t", type: "text", body: "Finding", evidence_version_ids: [] },
      ],
    };
    const frames = defaultFrames(section);
    for (const frame of Object.values(frames))
      expect(slideFrameSchema.safeParse(frame).success).toBe(true);
    expect(frames.f!.x + frames.f!.width).toBeLessThanOrEqual(1);
  });
  it("preserves explicit placements and speaker notes on import", () => {
    const deck = slideDeckSchema.parse({
      title: "Study",
      slides: [
        {
          id: "s",
          title: "Findings",
          settings: {
            notes: "Context",
            frames: { text: { x: 0.1, y: 0.4, width: 0.7, height: 0.3 } },
          },
          elements: [{ id: "text", type: "text", body: "Finding" }],
        },
      ],
    });
    expect(deck.slides[0]!.settings.notes).toBe("Context");
    expect(deck.slides[0]!.settings.frames.text!.x).toBe(0.1);
    expect(
      slideFrameSchema.safeParse({ x: 0.9, y: 0, width: 0.5, height: 0.4 })
        .success,
    ).toBe(false);
  });
  it("continues to read old report documents", () => {
    const report = reportContentSchema.parse({ title: "Report", sections: [] });
    expect(report.kind).toBe("report");
  });
});
