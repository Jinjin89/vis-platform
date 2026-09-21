import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { getFigureExport } from "../src/api/client";
import type { PlotResult } from "../src/api/schemas/plotRun";
import { FigureExportMenu } from "../src/features/plot-run/FigureExportMenu";

vi.mock("../src/api/client", () => ({ getFigureExport: vi.fn() }));
afterEach(() => vi.clearAllMocks());

const figure: PlotResult = {
  plot_id: "plot_1",
  version_id: "version_2",
  execution_mode: "r",
  controls_mode: "hybrid",
  parameter_schema_version: "1.0",
  parameter_updates_available: true,
  data_summary: "Selected observations",
  figure_size: { width: 8, height: 5.5, unit: "in" },
  preview: {
    artifact_id: "artifact_1",
    role: "preview",
    media_type: "image/svg+xml",
    href: "/api/v1/artifacts/artifact_1",
    description: "Measured observations.",
  },
  validation: { status: "passed", warnings: [] },
};

test("export chooser exposes all formats and supports keyboard navigation and dismissal", async () => {
  const user = userEvent.setup();
  render(
    <>
      <FigureExportMenu projectId="project_1" result={figure} />
      <button type="button">Next action</button>
    </>,
  );
  const button = screen.getByRole("button", { name: "Export" });
  await user.click(button);
  expect(screen.getByText("8 × 5.5 in")).toBeVisible();
  expect(screen.getByRole("menuitem", { name: "Download PNG" })).toHaveFocus();
  await user.keyboard("{ArrowDown}");
  expect(screen.getByRole("menuitem", { name: "Download PDF" })).toHaveFocus();
  await user.keyboard("{End}");
  expect(screen.getByRole("menuitem", { name: "Download SVG" })).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(button).toHaveFocus();
  await user.click(button);
  await user.keyboard("{Tab}");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Next action" })).toHaveFocus();
  await user.click(button);
  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

test("failed exports remain retryable and request the selected project and version", async () => {
  const user = userEvent.setup();
  vi.mocked(getFigureExport).mockRejectedValue(
    new Error("The export could not be prepared."),
  );
  const { rerender } = render(
    <FigureExportMenu projectId="project_1" result={figure} />,
  );
  await user.click(screen.getByRole("button", { name: "Export" }));
  await user.click(screen.getByRole("menuitem", { name: "Download PDF" }));
  expect(screen.getByRole("alert")).toHaveTextContent(
    "The export could not be prepared.",
  );
  expect(getFigureExport).toHaveBeenLastCalledWith(
    "project_1",
    "plot_1",
    "version_2",
    "pdf",
  );
  rerender(
    <FigureExportMenu
      projectId="project_1"
      result={{ ...figure, version_id: "version_1" }}
    />,
  );
  await user.click(screen.getByRole("menuitem", { name: "Download SVG" }));
  expect(getFigureExport).toHaveBeenLastCalledWith(
    "project_1",
    "plot_1",
    "version_1",
    "svg",
  );
});
