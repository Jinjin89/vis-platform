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
  listFigures: vi.fn(),
  createFigure: vi.fn(),
  getFigure: vi.fn(),
  applyFigureOperations: vi.fn(),
  arrangeFigure: vi.fn(),
  renderFigurePanels: vi.fn(),
  sendFigureMessage: vi.fn(),
  answerFigureMessage: vi.fn(),
}));
vi.mock("../src/api/figureCompositions", async (original) => ({
  ...(await original<typeof import("../src/api/figureCompositions")>()),
  ...api,
}));

// jsdom has no modal dialogs.
HTMLDialogElement.prototype.showModal ??= function () {
  this.open = true;
};
HTMLDialogElement.prototype.close ??= function () {
  this.open = false;
};

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
  parameter_updates_available: true,
  controls: ["width", "height"].map((dimension) => ({
    id: `figure_${dimension}`,
    type: "number",
    label: `Figure ${dimension}`,
    group: "figure_size",
    value: 4,
    minimum: 1,
    maximum: 30,
    step: 0.01,
    unit: "in",
  })),
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
    checks: [
      {
        code: "small_text",
        severity: "warning",
        message: "The smallest text in Panel A prints at 3.1 pt, below 5 pt.",
        panel_ids: ["umap"],
      },
    ],
  });
}

/** The standard document with a third panel: a slot, optionally with a fill in progress. */
function slotDocument(
  fill?: "waiting" | "plotting" | "failed",
  prompt = "Tumour volume over time.",
): FigureDocument {
  const base = makeDocument();
  return figureDocumentSchema.parse({
    ...base,
    content: {
      ...base.content,
      panels: [
        ...base.content.panels,
        {
          id: "growth",
          content: { type: "slot", prompt, width_mm: 120, height_mm: 60 },
          x_mm: 5,
          y_mm: 90,
        },
      ],
    },
    panels: {
      ...base.panels,
      growth: {
        label: "C",
        frame: { x_mm: 5, y_mm: 90, width_mm: 120, height_mm: 60 },
        natural_width_mm: 120,
        natural_height_mm: 60,
      },
    },
    messages: fill
      ? [
          {
            message_id: "m1",
            prompt: "Build the figure",
            status: fill === "failed" ? "completed" : "running",
            panels: [
              {
                panel_id: "growth",
                status: fill,
                error:
                  fill === "failed" ? "No data matched the request." : null,
              },
            ],
            created_at: "2026-09-21T00:00:00Z",
          },
        ]
      : [],
  });
}

function renderEditor(entry = "/figure?id=figure-1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
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
  api.arrangeFigure.mockImplementation(async () => makeDocument(2));
  api.renderFigurePanels.mockImplementation(async () => makeDocument(1));
});
afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

test("shows panels with their labels and page settings", async () => {
  const user = userEvent.setup();
  renderEditor();
  const page = await screen.findByRole("region", { name: "Figure page" });
  await user.click(screen.getByRole("tab", { name: "Page" }));
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
  await user.click(screen.getByRole("tab", { name: "Panel" }));
  await user.click(screen.getByRole("button", { name: "Apply update" }));
  expect(sentOperations()).toEqual([
    {
      op: "replace_panel",
      panel: expect.objectContaining({
        id: "violin",
        content: {
          type: "plot",
          version_id: "version-c",
          source_version_id: null,
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
  await user.click(screen.getByRole("tab", { name: "Panel" }));
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

test("checks select their panels and plots render at their panel size", async () => {
  const user = userEvent.setup();
  renderEditor();
  await user.click(await screen.findByRole("tab", { name: "Page" }));
  const check = await screen.findByRole("button", {
    name: /smallest text in Panel A/,
  });
  await user.click(check);
  expect(
    screen.getByRole("button", { name: "Panel A: Cell clusters" }),
  ).toHaveAttribute("aria-pressed", "true");
  await user.click(
    screen.getByRole("button", { name: "Render at panel size" }),
  );
  expect(api.renderFigurePanels).toHaveBeenCalledWith(
    "project-1",
    "figure-1",
    expect.any(String),
    { umap: { width_mm: 101.6, height_mm: 76.2 } },
  );
});

test("tidying rows can also render plots", async () => {
  const user = userEvent.setup();
  renderEditor();
  await user.click(await screen.findByText("Arrange"));
  await user.click(
    screen.getByRole("menuitem", {
      name: "Tidy rows and render plots at size",
    }),
  );
  expect(api.arrangeFigure).toHaveBeenCalledWith(
    "project-1",
    "figure-1",
    1,
    expect.any(String),
    expect.objectContaining({ render: true }),
  );
});

test("the assistant sends the selection as a hint and answers questions", async () => {
  const user = userEvent.setup();
  api.sendFigureMessage.mockImplementation(async () => makeDocument());
  renderEditor();
  await user.click(
    await screen.findByRole("button", { name: "Panel A: Cell clusters" }),
  );
  expect(screen.getByText(/About panel A/)).toBeInTheDocument();
  await user.type(
    screen.getByRole("textbox", { name: "Message the figure assistant" }),
    "Make this panel lead the figure{Enter}",
  );
  expect(api.sendFigureMessage).toHaveBeenCalledWith("project-1", "figure-1", {
    request_id: expect.any(String),
    message: "Make this panel lead the figure",
    selection: { panel_ids: ["umap"] },
  });
});

test("assistant questions and progress are shown in the conversation", async () => {
  const user = userEvent.setup();
  const waiting = {
    ...makeDocument(),
    messages: [
      {
        message_id: "m1",
        prompt: "Arrange the figure",
        selection: null,
        status: "awaiting_input",
        phase: "planning",
        response_text: "One choice first.",
        error: null,
        question: {
          interaction_id: "i1",
          questions: [
            {
              question_id: "lead",
              header: "Lead",
              prompt: "Which panel should lead?",
              reason: "It gets a full row.",
              selection: "single",
              allow_free_text: false,
              choices: [
                { choice_id: "umap", label: "Cell clusters" },
                { choice_id: "violin", label: "Expression by group" },
              ],
            },
          ],
        },
        active_step: null,
        panels: [],
        completed_actions: [],
        created_at: "2026-09-21T00:00:00Z",
      },
    ],
  };
  api.getFigure.mockResolvedValue(waiting);
  api.answerFigureMessage.mockImplementation(async () => makeDocument());
  renderEditor();
  expect(
    await screen.findByText("Which panel should lead?"),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("radio", { name: /Cell clusters/ }));
  await user.click(
    screen.getByRole("button", { name: /Continue|Submit|Answer/ }),
  );
  expect(api.answerFigureMessage).toHaveBeenCalledWith(
    "project-1",
    "figure-1",
    "m1",
    "i1",
    [{ question_id: "lead", choice_ids: ["umap"], free_text: null }],
  );
});

test("a failed slot is described again, resized, and retried", async () => {
  const user = userEvent.setup();
  api.getFigure.mockResolvedValue(slotDocument("failed"));
  api.applyFigureOperations.mockImplementation(async () =>
    slotDocument("failed"),
  );
  api.sendFigureMessage.mockImplementation(async () => slotDocument("waiting"));
  renderEditor();
  const slot = await screen.findByRole("button", {
    name: "Panel C: Slot: Tumour volume over time.",
  });
  expect(within(slot).getByText("Could not be created")).toBeInTheDocument();
  await user.dblClick(slot);
  expect(screen.getByText("No data matched the request.")).toBeInTheDocument();

  const height = screen.getByRole("spinbutton", { name: /^Height/ });
  await user.clear(height);
  await user.type(height, "80");
  await user.tab();
  expect(sentOperations()).toEqual([
    {
      op: "replace_panel",
      panel: expect.objectContaining({
        id: "growth",
        scale: 1,
        content: expect.objectContaining({ width_mm: 120, height_mm: 80 }),
      }),
    },
  ]);

  const prompt = screen.getByRole("textbox", {
    name: "What should this plot show?",
  });
  await user.clear(prompt);
  await user.type(prompt, "Tumour volume by group, mean ± SEM.");
  await user.click(screen.getByRole("button", { name: "Retry" }));
  expect(sentOperations()).toEqual([
    {
      op: "replace_panel",
      panel: expect.objectContaining({
        content: expect.objectContaining({
          type: "slot",
          prompt: "Tumour volume by group, mean ± SEM.",
        }),
      }),
    },
  ]);
  expect(api.sendFigureMessage).toHaveBeenCalledWith("project-1", "figure-1", {
    request_id: expect.any(String),
    message: "Create the plot for panel C.",
    fill: ["growth"],
  });
  expect(await within(slot).findByText("Waiting")).toBeInTheDocument();
});

test("slots are added from the toolbar at a free spot", async () => {
  const user = userEvent.setup();
  renderEditor();
  await user.click(await screen.findByRole("button", { name: "+ Slot" }));
  expect(sentOperations()).toEqual([
    {
      op: "add_panel",
      panel: {
        id: "panel-1",
        content: { type: "slot", prompt: "", width_mm: 90, height_mm: 67 },
        x_mm: 5,
        y_mm: 85.2,
        scale: 1,
        label: null,
        show_label: true,
        locked: false,
      },
    },
  ]);
});

test("a new figure with a description starts the assistant", async () => {
  const user = userEvent.setup();
  api.listFigures.mockResolvedValue({
    schema_version: "1.0",
    compositions: [],
    total: 0,
    offset: 0,
  });
  api.createFigure.mockImplementation(async () => makeDocument());
  api.sendFigureMessage.mockImplementation(async () => makeDocument());
  renderEditor("/figure");
  await user.click(await screen.findByRole("button", { name: "+ New figure" }));
  await user.type(
    screen.getByRole("textbox", { name: /What should this figure show/ }),
    "Treatment response in four panels.",
  );
  await user.click(screen.getByRole("button", { name: "Create and build" }));
  expect(api.createFigure).toHaveBeenCalledWith(
    "project-1",
    expect.objectContaining({ datasets: [] }),
    expect.any(String),
  );
  expect(api.sendFigureMessage).toHaveBeenCalledWith("project-1", "figure-1", {
    request_id: expect.any(String),
    message: "Treatment response in four panels.",
  });
  expect(
    await screen.findByRole("region", { name: "Figure page" }),
  ).toBeInTheDocument();
});
