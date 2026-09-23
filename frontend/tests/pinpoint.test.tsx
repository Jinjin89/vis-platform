import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";

import type { PlotMark } from "../src/api/pinpoint";
import { PinpointPage } from "../src/pages/PinpointPage";

// jsdom has no WebGL; the stand-in marks points and areas as the real view would.
vi.mock("../src/features/pinpoint/PointMapStage", () => ({
  PointMapStage: ({
    onMark,
    onUnavailable,
  }: {
    onMark: (mark: PlotMark) => void;
    onUnavailable: (reason: string) => void;
  }) => (
    <div role="img" aria-label="Interactive point view">
      <button
        type="button"
        onClick={() => onMark({ number: 1, kind: "element", index: 42 })}
      >
        Click point 42
      </button>
      <button
        type="button"
        onClick={() =>
          onMark({
            number: 2,
            kind: "selection",
            x_from: 10,
            x_to: 20,
            y_from: 30,
            y_to: 40,
          })
        }
      >
        Drag an area
      </button>
      <button type="button" onClick={() => onUnavailable("no WebGL")}>
        Lose WebGL
      </button>
    </div>
  ),
}));

function plot(version: number) {
  return {
    plot_id: "plot_1",
    version_id: `version_${version}`,
    execution_mode: "r",
    preview: {
      artifact_id: `artifact_${version}`,
      role: "preview",
      media_type: "image/svg+xml",
      href: `/api/v1/artifacts/artifact_${version}`,
      description: `Dose response, version ${version}.`,
    },
    controls_mode: "hybrid",
    title: "Dose response",
    validation: { status: "passed", warnings: [] },
  };
}

const links = {
  trace: "/api/v1/assistant-turns/turn_1/trace",
  status: "/api/v1/assistant-turns/turn_1?project_id=project_1",
  events: "/api/v1/assistant-turns/turn_1/events?project_id=project_1",
  cancel: "/api/v1/assistant-turns/turn_1/cancel?project_id=project_1",
};
const run = {
  schema_version: "1.0",
  run_id: "run_2",
  status: "queued",
  stage: "received",
  links: {
    status: "/api/v1/plot-runs/run_2",
    events: "/api/v1/plot-runs/run_2/events",
    cancel: "/api/v1/plot-runs/run_2/cancel",
  },
};
const intent = {
  kind: "plot_refine",
  subtype: "visual",
  normalized_request: "Label the marked point and shade the marked area.",
  confidence: 1,
  next_action: "refine_context",
  decision_summary: "Refine the marked places.",
  user_reply: "Labelled point 1 and shaded area 2.",
};

function json(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function serve(sent: object[], extra: object = {}) {
  let version = 1;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/projects/project_1")
        return json({
          schema_version: "1.0",
          project_id: "project_1",
          name: "Untitled study",
          created_at: "2026-09-22T00:00:00Z",
        });
      if (path.startsWith("/api/v1/projects/project_1/reports/figures"))
        return json({
          schema_version: "1.0",
          figures: [{ ...plot(version), ...extra }],
          total: 1,
          offset: 0,
        });
      if (path === "/api/v1/assistant-turns" && init?.method === "POST") {
        sent.push(JSON.parse(String(init.body)));
        return json(
          {
            schema_version: "1.0",
            turn_id: "turn_1",
            status: "running",
            links,
          },
          202,
        );
      }
      if (path === links.status)
        return json({
          schema_version: "1.0",
          turn_id: "turn_1",
          project_id: "project_1",
          request_text: "Label 1 and shade 2",
          revision: 3,
          status: "completed",
          response: {
            schema_version: "1.0",
            turn_id: "turn_1",
            outcome: "plot_run",
            intent,
            plot_run: run,
            links,
            created_at: "2026-09-22T00:00:00Z",
          },
        });
      if (path === run.links.status) {
        version = 2;
        return json({
          schema_version: "1.0",
          run_id: "run_2",
          project_id: "project_1",
          status: "completed",
          stage: "committing_version",
          created_at: "2026-09-22T00:00:00Z",
          updated_at: "2026-09-22T00:00:01Z",
          result: { ...plot(2), ...extra },
        });
      }
      return json({ error: { code: "NOT_FOUND", message: "Not found." } }, 404);
    }),
  );
}

function renderPage() {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/pinpoint"]}>
        <PinpointPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The image is 200 × 100 pixels on screen. */
async function surface() {
  const image = await screen.findByRole("img", {
    name: "Dose response, version 1.",
  });
  const element = image.parentElement!;
  vi.spyOn(element, "getBoundingClientRect").mockReturnValue({
    left: 0,
    top: 0,
    width: 200,
    height: 100,
  } as DOMRect);
  return element;
}

function click(element: HTMLElement, x: number, y: number) {
  fireEvent.pointerDown(element, { clientX: x, clientY: y, button: 0 });
  fireEvent.pointerUp(element, { clientX: x, clientY: y });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

test("marks placed on a plot are sent with the request and cleared by its new version", async () => {
  const user = userEvent.setup();
  const sent: object[] = [];
  window.localStorage.setItem("vis-platform.project-id", "project_1");
  serve(sent);
  renderPage();
  const plotSurface = await surface();

  click(plotSurface, 50, 25);
  fireEvent.pointerDown(plotSurface, { clientX: 100, clientY: 40, button: 0 });
  fireEvent.pointerMove(plotSurface, { clientX: 180, clientY: 90 });
  fireEvent.pointerUp(plotSurface, { clientX: 180, clientY: 90 });
  const toSend = screen.getByRole("list", { name: "Marks to send" });
  expect(within(toSend).getByText("Point 1")).toBeInTheDocument();
  expect(within(toSend).getByText("Area 2")).toBeInTheDocument();

  // A removed number is used again first.
  await user.click(screen.getByRole("button", { name: "Remove mark 1" }));
  expect(within(toSend).queryByText("Point 1")).not.toBeInTheDocument();
  click(plotSurface, 50, 25);
  expect(within(toSend).getByText("Point 1")).toBeInTheDocument();

  await user.type(
    screen.getByRole("textbox", { name: "Your request" }),
    "Label 1 and shade 2",
  );
  await user.click(screen.getByRole("button", { name: "Send" }));

  expect(
    await screen.findByText("Labelled point 1 and shaded area 2."),
  ).toBeInTheDocument();
  expect(sent).toEqual([
    expect.objectContaining({
      request: expect.objectContaining({ text: "Label 1 and shade 2" }),
      base_version_id: "version_1",
      plot_marks: [
        { number: 2, kind: "area", x: 0.5, y: 0.4, width: 0.4, height: 0.5 },
        { number: 1, kind: "point", x: 0.25, y: 0.25, width: 0, height: 0 },
      ],
    }),
  ]);
  // The new version replaces the image, and marks on the old one are gone.
  expect(
    await screen.findByRole("img", { name: "Dose response, version 2." }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("list", { name: "Marks to send" }),
  ).not.toBeInTheDocument();
  const sentMarks = screen.getByRole("list", { name: "Marks sent" });
  expect(within(sentMarks).getByText("Area 2")).toBeInTheDocument();

  // The conversation stays with the plot in this browser.
  const saved = JSON.parse(
    window.localStorage.getItem("vis-platform.pinpoint.project_1.plot_1")!,
  );
  expect(saved.pending).toBeNull();
  expect(
    saved.messages.map((message: { text: string }) => message.text),
  ).toEqual(["Label 1 and shade 2", "Labelled point 1 and shaded area 2."]);
});

test("a request without marks sends no marks", async () => {
  const user = userEvent.setup();
  const sent: object[] = [];
  window.localStorage.setItem("vis-platform.project-id", "project_1");
  serve(sent);
  renderPage();
  await surface();
  await user.type(
    screen.getByRole("textbox", { name: "Your request" }),
    "Use a larger font",
  );
  await user.click(screen.getByRole("button", { name: "Send" }));
  await screen.findByText("Labelled point 1 and shaded area 2.");
  expect(sent[0]).not.toHaveProperty("plot_marks");
  expect(sent[0]).toHaveProperty("base_version_id", "version_1");
});

test("a point map's clicked points and dragged areas are sent as data marks", async () => {
  const user = userEvent.setup();
  const sent: object[] = [];
  window.localStorage.setItem("vis-platform.project-id", "project_1");
  serve(sent, { interactive_view: "points" });
  renderPage();
  await user.click(
    await screen.findByRole("button", { name: "Click point 42" }),
  );
  await user.click(screen.getByRole("button", { name: "Drag an area" }));
  const toSend = screen.getByRole("list", { name: "Marks to send" });
  expect(within(toSend).getByText("Point 1")).toBeInTheDocument();
  expect(within(toSend).getByText("Area 2")).toBeInTheDocument();
  await user.type(
    screen.getByRole("textbox", { name: "Your request" }),
    "Compare 1 with 2",
  );
  await user.click(screen.getByRole("button", { name: "Send" }));
  await screen.findByText("Labelled point 1 and shaded area 2.");
  expect(sent[0]).toMatchObject({
    request: { text: "Compare 1 with 2", interactive: true },
    base_version_id: "version_1",
    plot_marks: [
      { number: 1, kind: "element", index: 42 },
      {
        number: 2,
        kind: "selection",
        x_from: 10,
        x_to: 20,
        y_from: 30,
        y_to: 40,
      },
    ],
  });
});

test("without WebGL, a point map falls back to its saved figure", async () => {
  const user = userEvent.setup();
  window.localStorage.setItem("vis-platform.project-id", "project_1");
  serve([], { interactive_view: "points" });
  renderPage();
  await user.click(
    await screen.findByRole("button", { name: "Click point 42" }),
  );
  await user.click(screen.getByRole("button", { name: "Lose WebGL" }));
  expect(
    await screen.findByRole("img", { name: "Dose response, version 1." }),
  ).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("no WebGL");
  // A clicked point means nothing on the image, so it is dropped.
  expect(
    screen.queryByRole("list", { name: "Marks to send" }),
  ).not.toBeInTheDocument();
});
