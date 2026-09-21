import type { ReportContent } from "../../api/schemas/reports";

export function reportItemNumbers(
  content: ReportContent,
  kind: "figure" | "table",
) {
  const numbers = new Map<string, number>();
  for (const topic of content.sections)
    for (const block of topic.blocks) {
      if (block.type === kind) numbers.set(block.id, numbers.size + 1);
    }
  return numbers;
}
