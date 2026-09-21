import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, test, vi } from "vitest";

import type { PlotRunSnapshot } from "../src/api/schemas/plotRun";
import { FigureHistory } from "../src/features/plot-run/FigureHistory";

const result = {
  plot_id: "plot_1",
  version_id: "version_2",
  execution_mode: "demo" as const,
  controls_mode: "hybrid" as const,
  parameter_schema_version: "1.0" as const,
  parameter_updates_available: false,
  data_summary: "Illustrative data.",
  controls: [],
  preview: {
    artifact_id: "artifact_2",
    role: "preview" as const,
    media_type: "image/svg+xml",
    href: "/api/v1/artifacts/artifact_2",
    description: "A saved figure.",
  },
  validation: { status: "demo_only" as const, warnings: [] },
};
const snapshot: PlotRunSnapshot = {
  schema_version: "1.0",
  run_id: "run_2",
  project_id: "project_1",
  status: "completed",
  stage: "committing_version",
  created_at: "2026-09-10T00:00:00Z",
  updated_at: "2026-09-10T00:00:01Z",
  result,
};

test("browses old versions without restoring until explicitly requested", async () => {
  const user = userEvent.setup();
  const restore = vi.fn(async () => true);
  const selection = vi.fn();
  const fetchMock = vi.fn(
    async () =>
      new Response(
        JSON.stringify({
          schema_version: "1.0",
          project_id: "project_1",
          plot_id: "plot_1",
          current_version_id: "version_2",
          versions: [2, 1].map((n) => ({
            version_id: `version_${n}`,
            run_id: `run_${n}`,
            parent_version_id: n === 2 ? "version_1" : null,
            created_at: `2026-09-10T00:00:0${n}Z`,
            change_summary: n === 2 ? "Larger labels" : "Initial figure",
            result: { ...result, version_id: `version_${n}` },
          })),
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
  );
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Workspace() {
    const [selected, setSelected] = useState(snapshot);
    return (
      <FigureHistory
        snapshot={selected}
        disabled={false}
        onSelect={async (runId) => {
          selection(runId);
          setSelected({
            ...snapshot,
            run_id: runId,
            result: {
              ...result,
              version_id: runId.replace("run_", "version_"),
            },
          });
        }}
        onRestore={restore}
      />
    );
  }
  const view = render(
    <QueryClientProvider client={client}>
      <Workspace />
    </QueryClientProvider>,
  );
  expect(fetchMock).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "History" }));
  await screen.findByRole("button", { name: /Version 2 · Current/ });
  await user.click(screen.getByRole("button", { name: /Version 1/ }));
  await screen.findByText("Viewing an earlier version");
  expect(selection).toHaveBeenCalledWith("run_1");
  expect(restore).not.toHaveBeenCalled();
  await user.click(document.body);
  expect(screen.getByRole("region", { name: "Figure history" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: /Version 2 · Current/ }));
  await screen.findByText("Viewing the current version");
  expect(selection).toHaveBeenLastCalledWith("run_2");
  await user.click(screen.getByRole("button", { name: /Version 1/ }));
  await screen.findByText("Viewing an earlier version");
  await user.click(screen.getByRole("button", { name: "Restore as new" }));
  expect(restore).toHaveBeenCalledWith("version_1", expect.any(String));
  expect(screen.getByRole("region", { name: "Figure history" })).toBeVisible();
  view.unmount();
  render(
    <QueryClientProvider client={client}>
      <Workspace />
    </QueryClientProvider>,
  );
  expect(
    screen.getByRole("button", { name: "Collapse figure history" }),
  ).toHaveAttribute("aria-expanded", "true");
  await user.click(
    screen.getByRole("button", { name: "Collapse figure history" }),
  );
  expect(
    screen.queryByRole("region", { name: "Figure history" }),
  ).not.toBeInTheDocument();
  expect(window.sessionStorage.getItem("vis-platform.history-open")).toBe(
    "false",
  );
  await user.click(screen.getByRole("button", { name: "History" }));
  await user.keyboard("{Escape}");
  expect(screen.getByRole("button", { name: "History" })).toHaveFocus();
});
