import { expect, test } from "vitest";
import { reportContentSchema } from "../src/api/schemas/reports";

test("a data-only report and a partially prepared report share one contract", () => {
  const empty = reportContentSchema.parse({
    title: "Study",
    datasets: [{ dataset_id: "data_1" }],
    sections: [{ id: "topic", title: "Findings" }],
  });
  expect(empty.sections[0]!.blocks).toEqual([]);
  const prepared = reportContentSchema.parse({
    ...empty,
    sections: [
      {
        id: "topic",
        title: "Findings",
        blocks: [
          { id: "intro", type: "text", body: "Measured findings." },
          { id: "plot", type: "figure", version_id: "version_1" },
          {
            id: "summary",
            type: "table",
            columns: ["Group", "Mean"],
            rows: [["A", 2]],
          },
        ],
      },
      { id: "discussion", title: "Discussion" },
    ],
  });
  expect(prepared.sections[0]!.blocks).toHaveLength(3);
  expect(prepared.sections[1]!.blocks).toEqual([]);
});

test("pre-report imports reject ambiguous images, duplicate IDs, and malformed tables", () => {
  const parseBlock = (block: unknown) =>
    reportContentSchema.safeParse({
      title: "Report",
      sections: [{ id: "topic", title: "Results", blocks: [block] }],
    });
  expect(
    parseBlock({ id: "figure", type: "figure", version_id: "v", image_id: "i" })
      .success,
  ).toBe(false);
  expect(
    parseBlock({ id: "figure", type: "figure", href: "/private/file.png" })
      .success,
  ).toBe(false);
  expect(
    parseBlock({ id: "topic", type: "text", body: "Duplicate identity" })
      .success,
  ).toBe(false);
  expect(
    parseBlock({ id: "table", type: "table", columns: ["one"], rows: [[1, 2]] })
      .success,
  ).toBe(false);
});
