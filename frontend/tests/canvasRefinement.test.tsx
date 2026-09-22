import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";

import {
  storageKey,
  type CanvasGraph,
} from "../src/features/infinite-canvas/model";
import { CanvasPage } from "../src/pages/CanvasPage";

const dataset = {
  dataset_id: "dataset_1",
  project_id: "project_1",
  name: "Tumour study",
  source_kind: "upload",
  source_id: "upload_1",
  revision_id: "revision_1",
  state: "ready",
  created_at: "2026-09-03T00:00:00Z",
  updated_at: "2026-09-03T00:00:00Z",
};
const opacity = {
  id: "point_alpha",
  label: "Point opacity",
  group: "appearance",
  update_strategy: "rerun",
  type: "number",
  // Planned before new plans had to start on their scale: 0.1 steps from 0.1 miss 0.75.
  value: 0.75,
  minimum: 0.1,
  maximum: 1,
  step: 0.1,
  input_mode: "number",
} as const;
const title = {
  id: "title",
  label: "Title",
  group: "appearance",
  update_strategy: "rerun",
  type: "text",
  value: "Tumour volume",
  min_length: 1,
  max_length: 80,
} as const;
const snapshot = {
  schema_version: "1.0",
  run_id: "run_1",
  project_id: "project_1",
  status: "completed",
  stage: "committing_version",
  created_at: "2026-09-03T00:00:00Z",
  updated_at: "2026-09-03T00:00:01Z",
  result: {
    plot_id: "plot_1",
    version_id: "version_1",
    title: "Tumour volume",
    execution_mode: "r",
    preview: {
      artifact_id: "artifact_1",
      role: "preview",
      media_type: "image/svg+xml",
      href: "/api/v1/artifacts/artifact_1",
      description: "Tumour volume by group.",
    },
    controls_mode: "hybrid",
    parameter_updates_available: true,
    controls: [title, opacity],
    validation: { status: "passed", warnings: [] },
  },
  progress: null,
  pending_question: null,
  pending_approval: null,
  failure: null,
};

function savedCanvas(): CanvasGraph {
  return {
    schemaVersion: 1,
    projectId: "project_1",
    viewport: { x: 72, y: 100, zoom: 1 },
    selectedId: "plot-node",
    drafts: {},
    nodes: [
      {
        id: "data-node",
        type: "data",
        label: "D1",
        title: "Tumour study",
        position: { x: 0, y: 0 },
        dataset: dataset as never,
        summary: "1 object",
      },
      {
        id: "plot-node",
        type: "plot",
        label: "P1",
        title: "Tumour volume",
        position: { x: 368, y: 0 },
        sourceDataNodeId: "data-node",
        sourceDatasetId: "dataset_1",
        sourceDatasetRevisionId: "revision_1",
        parentPlotId: null,
        prompt: "Plot tumour volume by group",
        createdAt: "2026-09-03T00:00:00Z",
        status: "completed",
        request: { id: "request_1", changes: {}, mode: "language" },
        parameters: { title: "Tumour volume", point_alpha: 0.75 },
        run: null,
        assistant: null,
        assistantSnapshot: null,
        snapshot: snapshot as never,
        source: null,
        error: null,
      },
    ],
  };
}

function json(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test("a saved plot whose parameter starts off its scale can still be refined", async () => {
  const user = userEvent.setup();
  const sent: { changes: object }[] = [];
  const canvasId = "canvas_1";
  window.localStorage.setItem("vis-platform.project-id", "project_1");
  window.localStorage.setItem(
    "vis-platform.canvases.v1.project_1",
    JSON.stringify([
      {
        id: canvasId,
        title: "Canvas 1",
        nodes: 2,
        updatedAt: "2026-09-03T00:00:00Z",
      },
    ]),
  );
  window.localStorage.setItem(
    storageKey("project_1", canvasId),
    JSON.stringify(savedCanvas()),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/plots/plot_1/parameters") {
        sent.push(JSON.parse(String(init!.body)));
        return json(
          { error: { code: "UNAVAILABLE", message: "Stopped by the test." } },
          503,
        );
      }
      if (path === "/api/v1/projects/project_1")
        return json({
          schema_version: "1.0",
          project_id: "project_1",
          name: "Untitled study",
          created_at: "2026-09-03T00:00:00Z",
        });
      if (path.startsWith("/api/v1/projects/project_1/datasets"))
        return json({ datasets: [dataset], total: 1, offset: 0 });
      return json({ error: { code: "NOT_FOUND", message: "Not found." } }, 404);
    }),
  );
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/canvas"]}>
        <CanvasPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const composer = await screen.findByRole("form", {
    name: "Canvas plot instructions",
  });
  const describe = within(composer).getByRole("textbox", {
    name: "Describe a refinement",
  });
  await user.type(describe, "Use a softer palette");
  expect(
    within(composer).getByRole("button", { name: /Create refinement/ }),
  ).toBeEnabled();
  await user.clear(describe);

  // Editing another parameter sends only that change, never the saved opacity.
  const parameters = screen.getByRole("form", { name: "Plot parameters" });
  fireEvent.change(within(parameters).getByRole("textbox", { name: "Title" }), {
    target: { value: "Tumour volume by group" },
  });
  const apply = within(parameters).getByRole("button", {
    name: "Create refinement",
  });
  expect(apply).toBeEnabled();
  await user.click(apply);
  await vi.waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0]!.changes).toEqual({ title: "Tumour volume by group" });
});
