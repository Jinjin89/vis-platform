import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  figureDocumentSchema,
  type FigureDocument,
  type FigureOperation,
} from "../src/api/schemas/figureCompositions";
import { FigureWorkspace } from "../src/features/figures/FigureWorkspace";

const api = vi.hoisted(() => ({
  getFigure: vi.fn(),
  applyFigureOperations: vi.fn(),
}));
vi.mock("../src/api/figureCompositions", async (original) => ({
  ...(await original<typeof import("../src/api/figureCompositions")>()),
  getFigure: api.getFigure,
  applyFigureOperations: api.applyFigureOperations,
}));

const preview = (id: string) => ({
  artifact_id: `artifact-${id}`,
  role: "preview",
  media_type: "image/svg+xml",
  href: `/api/v1/artifacts/artifact-${id}`,
  description: `Plot ${id}`,
});
const figure = (id: string, title: string) => ({
  plot_id: `plot-${id}`,
  version_id: `version-${id}`,
  execution_mode: "demo",
  preview: preview(id),
  controls_mode: "hybrid",
  figure_size: { width: 4, height: 3, unit: "in" },
  title,
  validation: { status: "demo_only", warnings: [] },
});

function makeDocument(revision = 1): FigureDocument {
  return figureDocumentSchema.parse({
    schema_version: "1.0",
    composition_id: "figure-1",
    project_id: "project-1",
    title: "Figure 2",
    revision,
    created_at: "2026-09-21T00:00:00Z",
    updated_at: "2026-09-21T00:00:00Z",
    page_height_mm: 86.2,
    content: {
      title: "Figure 2",
      page: { width_mm: 210, height_mm: 297, height_mode: "auto" },
      panels: [
        {
          id: "umap",
          content: { type: "plot", version_id: "version-a" },
          x_mm: 5,
          y_mm: 5,
        },
        {
          id: "violin",
          content: { type: "plot", version_id: "version-b" },
          x_mm: 105,
          y_mm: 5,
        },
      ],
    },
    panels: {
      umap: {
        label: "A",
        frame: { x_mm: 5, y_mm: 5, width_mm: 101.6, height_mm: 76.2 },
        natural_width_mm: 101.6,
        natural_height_mm: 76.2,
      },
      violin: {
        label: "B",
        frame: { x_mm: 105, y_mm: 5, width_mm: 101.6, height_mm: 76.2 },
        natural_width_mm: 101.6,
        natural_height_mm: 76.2,
      },
    },
    figures: {
      "version-a": figure("a", "Cell clusters"),
      "version-b": figure("b", "Expression by group"),
      "version-c": figure("c", "Expression by group"),
    },
    images: {},
    updates: { violin: "version-c" },
  });
}

function renderEditor() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/figure?id=figure-1"]}>
        <FigureWorkspace projectId="project-1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function sentOperations(): FigureOperation[] {
  return api.applyFigureOperations.mock.calls.at(-1)![3];
}

beforeEach(() => {
  api.getFigure.mockResolvedValue(makeDocument());
  api.applyFigureOperations.mockImplementation(async () => makeDocument(2));
});
afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

test("shows panels with their labels and page settings", async () => {
  renderEditor();
  const page = await screen.findByRole("region", { name: "Figure page" });
  expect(
    within(page).getByRole("button", { name: "Panel A: Cell clusters" }),
  ).toBeInTheDocument();
  expect(within(page).getByText("Update available")).toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "Page preset" })).toHaveValue(
    "a4-width",
  );
  expect(screen.getByText("Saved · revision 1")).toBeInTheDocument();
});

test("keyboard nudges become one geometry operation", async () => {
  renderEditor();
  const panel = await screen.findByRole("button", {
    name: "Panel A: Cell clusters",
  });
  vi.useFakeTimers();
  fireEvent.pointerDown(panel, { button: 0, pointerId: 1 });
  fireEvent.keyDown(panel, { key: "ArrowRight" });
  fireEvent.keyDown(panel, { key: "ArrowRight", shiftKey: true });
  fireEvent.keyDown(panel, { key: "ArrowDown" });
  expect(api.applyFigureOperations).not.toHaveBeenCalled();
  await act(async () => {
    vi.advanceTimersByTime(600);
  });
  expect(api.applyFigureOperations).toHaveBeenCalledTimes(1);
  expect(sentOperations()).toEqual([
    {
      op: "set_panel_geometry",
      panels: { umap: { x_mm: 10.5, y_mm: 5.5, scale: 1 } },
    },
  ]);
});

test("the inspector applies a newer version while keeping the panel width", async () => {
  const user = userEvent.setup();
  api.getFigure.mockResolvedValue({
    ...makeDocument(),
    figures: {
      ...makeDocument().figures,
      "version-c": {
        ...makeDocument().figures["version-c"]!,
        figure_size: { width: 8, height: 4, unit: "in" },
      },
    },
  });
  renderEditor();
  await user.click(
    await screen.findByRole("button", { name: "Panel B: Expression by group" }),
  );
  await user.click(screen.getByRole("button", { name: "Apply update" }));
  expect(sentOperations()).toEqual([
    {
      op: "replace_panel",
      panel: expect.objectContaining({
        id: "violin",
        content: {
          type: "plot",
          version_id: "version-c",
          ignored_version_id: null,
        },
        scale: 0.5,
      }),
    },
  ]);
});

test("custom labels and removal use panel operations", async () => {
  const user = userEvent.setup();
  renderEditor();
  await user.click(
    await screen.findByRole("button", { name: "Panel A: Cell clusters" }),
  );
  const label = screen.getByRole("textbox", { name: "Custom label" });
  await user.type(label, "i");
  await user.tab();
  expect(sentOperations()).toEqual([
    {
      op: "replace_panel",
      panel: expect.objectContaining({ id: "umap", label: "i" }),
    },
  ]);
  await user.click(screen.getByRole("button", { name: "Remove panel" }));
  expect(sentOperations()).toEqual([{ op: "remove_panel", panel_id: "umap" }]);
});
