import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { expect, test, vi } from "vitest";
import { reportDocumentSchema } from "../src/api/schemas/reports";
import { ReportEditorDialog } from "../src/features/reports/ReportEditorDialog";

vi.mock("../src/features/reports/ReportDialog", () => ({
  ReportDialog: ({ children }: { children: ReactNode }) => (
    <section>{children}</section>
  ),
}));

test("a removed topic preserves the open text draft without attempting a save", async () => {
  const user = userEvent.setup();
  const document = reportDocumentSchema.parse({
    schema_version: "1.0",
    report_id: "r",
    project_id: "p",
    title: "Report",
    revision: 1,
    created_at: "2026-09-15T00:00:00Z",
    updated_at: "2026-09-15T00:00:00Z",
    content: {
      title: "Report",
      sections: [
        {
          id: "topic",
          title: "Results",
          blocks: [{ id: "text", type: "text", body: "Original" }],
        },
      ],
    },
    datasets: [],
    figures: {},
    images: {},
    edits: [],
  });
  const save = vi.fn(async () => true);
  const props = {
    document,
    target: { kind: "text" as const, topicId: "topic", blockId: "text" },
    onClose: vi.fn(),
    onGenerate: vi.fn(async () => true),
    onSaveText: save,
  };
  const view = render(<ReportEditorDialog {...props} />);
  await user.type(
    screen.getByLabelText("Report text"),
    " and my unsaved draft",
  );
  view.rerender(
    <ReportEditorDialog
      {...props}
      document={{ ...document, content: { ...document.content, sections: [] } }}
    />,
  );
  expect(screen.getByLabelText("Preserved report draft")).toHaveValue(
    "Original and my unsaved draft",
  );
  expect(save).not.toHaveBeenCalled();
});
