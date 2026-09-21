import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";

import { WorkspacePage } from "../src/pages/WorkspacePage";

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  onerror: ((event: Event) => void) | null = null;
  readonly listeners = new Map<
    string,
    Array<(event: MessageEvent<string>) => void>
  >();

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject | null,
  ) {
    if (listener === null) {
      return;
    }
    const callback = (event: MessageEvent<string>) => {
      if (typeof listener === "function") {
        listener(event);
      } else {
        listener.handleEvent(event);
      }
    };
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), callback]);
  }

  close() {}

  emit(type: string, payload: object) {
    const event = new MessageEvent(type, { data: JSON.stringify(payload) });
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event);
    }
  }
}

const preview = {
  artifact_id: "artifact_1",
  role: "preview",
  media_type: "image/svg+xml",
  href: "/api/v1/artifacts/artifact_1",
  description: "A demonstration comparison plot.",
};

const completedSnapshot = {
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
    execution_mode: "demo",
    preview,
    controls_mode: "hybrid",
    controls: [],
    validation: { status: "demo_only", warnings: [] },
  },
  progress: { progress: 90, message: "Saving the plot version" },
  pending_question: null,
  pending_approval: null,
  failure: null,
};

afterEach(() => {
  FakeEventSource.instances = [];
  vi.unstubAllGlobals();
});

test("shows an event preview and preserves it after a failed refinement", async () => {
  let runCount = 0;
  const fetchMock = vi.fn(
    async (input: string | URL | Request, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/projects") {
        return jsonResponse({
          schema_version: "1.0",
          project_id: "project_1",
          name: "Untitled project",
          created_at: "2026-09-03T00:00:00Z",
        });
      }
      if (path === "/api/v1/assistant-turns" && init?.method === "POST") {
        runCount += 1;
        const runId = "run_" + runCount;
        const turnId = "turn_" + runCount;
        return jsonResponse({
          schema_version: "1.0",
          turn_id: turnId,
          outcome: "plot_run",
          intent: {
            kind: runCount === 1 ? "plot_create" : "plot_refine",
            subtype: "plot_request",
            normalized_request: "Plot request",
            confidence: 0.98,
            next_action: runCount === 1 ? "build_context" : "refine_context",
            mode_requests: {},
            plot:
              runCount === 1
                ? {
                    goal: "Compare treatment and control",
                    variable_mentions: {},
                    data_hints: [],
                    filters: [],
                    statistics: [],
                    appearance: [],
                  }
                : null,
            refinement:
              runCount === 1
                ? null
                : {
                    changes: [
                      {
                        target: "legend_position",
                        value: "bottom",
                        change_class: "visual",
                      },
                    ],
                    reuse_data: true,
                  },
            missing_context: [],
            decision_summary: "This request asks to create or refine a plot.",
            user_reply: null,
          },
          message: null,
          plot_run: {
            schema_version: "1.0",
            run_id: runId,
            status: "queued",
            stage: "received",
            links: {
              status: "/api/v1/plot-runs/" + runId,
              events: "/api/v1/plot-runs/" + runId + "/events",
              cancel: "/api/v1/plot-runs/" + runId + "/cancel",
            },
          },
          links: { trace: "/api/v1/assistant-turns/" + turnId + "/trace" },
          created_at: "2026-09-03T00:00:00Z",
        });
      }
      if (path === "/api/v1/plot-runs/run_1") {
        return jsonResponse(completedSnapshot);
      }
      if (path === "/api/v1/plot-runs/run_2") {
        return jsonResponse({
          ...completedSnapshot,
          run_id: "run_2",
          status: "failed",
          result: null,
          failure: {
            code: "R_EXECUTION_FAILED",
            message: "The refinement could not be rendered.",
            recoverable: true,
          },
        });
      }
      throw new Error("Unexpected request: " + path);
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("EventSource", FakeEventSource);

  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const user = userEvent.setup();
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <WorkspacePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  const input = screen.getByRole("textbox", {
    name: "Describe the plot you want",
  });
  await user.type(input, "Compare treatment and control");
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

  await act(async () => {
    FakeEventSource.instances[0]?.emit("preview.ready", {
      schema_version: "1.0",
      event_id: "event_1",
      run_id: "run_1",
      sequence: 1,
      type: "preview.ready",
      occurred_at: "2026-09-03T00:00:00Z",
      payload: { artifact: preview, provisional: false },
    });
  });
  expect(
    screen.getByRole("img", { name: preview.description }),
  ).toBeInTheDocument();

  await act(async () => {
    FakeEventSource.instances[0]?.emit("run.completed", {
      schema_version: "1.0",
      event_id: "event_2",
      run_id: "run_1",
      sequence: 2,
      type: "run.completed",
      occurred_at: "2026-09-03T00:00:01Z",
      payload: {
        status: "completed",
        plot_id: "plot_1",
        version_id: "version_1",
      },
    });
  });
  await screen.findByText(/The demonstration figure is ready/);

  await user.type(input, "Move the legend below the plot");
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
  await act(async () => {
    FakeEventSource.instances[1]?.emit("run.failed", {
      schema_version: "1.0",
      event_id: "event_3",
      run_id: "run_2",
      sequence: 1,
      type: "run.failed",
      occurred_at: "2026-09-03T00:00:02Z",
      payload: {
        status: "failed",
        code: "R_EXECUTION_FAILED",
        message: "The refinement could not be rendered.",
        recoverable: true,
      },
    });
  });

  await screen.findByText("The refinement could not be rendered.");
  expect(
    screen.getByRole("img", { name: preview.description }),
  ).toBeInTheDocument();
});

test("recovers by polling when the cancel response is lost", async () => {
  let statusRequests = 0;
  const fetchMock = vi.fn(
    async (input: string | URL | Request, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/projects") {
        return jsonResponse(projectResponse());
      }
      if (path === "/api/v1/assistant-turns" && init?.method === "POST") {
        return jsonResponse(plotTurnResponse("run_cancel"));
      }
      if (path === "/api/v1/plot-runs/run_cancel/cancel") {
        expect(init?.method).toBe("POST");
        throw new TypeError("The cancellation response was lost.");
      }
      if (path === "/api/v1/plot-runs/run_cancel") {
        statusRequests += 1;
        return jsonResponse(cancelledSnapshot("run_cancel"));
      }
      throw new Error("Unexpected request: " + path);
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("EventSource", FakeEventSource);
  const user = userEvent.setup();
  renderWorkspace();

  const input = screen.getByRole("textbox", {
    name: "Describe the plot you want",
  });
  await user.type(input, "Create a comparison plot");
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

  await user.click(screen.getByRole("button", { name: "Stop" }));

  await screen.findByText(
    "I stopped this run. Your last saved figure is unchanged.",
    undefined,
    { timeout: 2_000 },
  );
  expect(statusRequests).toBe(1);
  expect(input).toBeEnabled();
  expect(
    screen.queryByRole("button", { name: "Stop" }),
  ).not.toBeInTheDocument();
});

test("polls for the final snapshot after a transient completion fetch failure", async () => {
  let statusRequests = 0;
  const fetchMock = vi.fn(
    async (input: string | URL | Request, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/projects") {
        return jsonResponse(projectResponse());
      }
      if (path === "/api/v1/assistant-turns" && init?.method === "POST") {
        return jsonResponse(plotTurnResponse("run_recovery"));
      }
      if (path === "/api/v1/plot-runs/run_recovery") {
        statusRequests += 1;
        if (statusRequests === 1) {
          throw new TypeError("Temporary network interruption");
        }
        return jsonResponse({ ...completedSnapshot, run_id: "run_recovery" });
      }
      throw new Error("Unexpected request: " + path);
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("EventSource", FakeEventSource);
  const user = userEvent.setup();
  renderWorkspace();

  await user.type(
    screen.getByRole("textbox", { name: "Describe the plot you want" }),
    "Create a comparison plot",
  );
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

  await act(async () => {
    FakeEventSource.instances[0]?.emit("run.completed", {
      schema_version: "1.0",
      event_id: "event_complete",
      run_id: "run_recovery",
      sequence: 1,
      type: "run.completed",
      occurred_at: "2026-09-03T00:00:01Z",
      payload: {
        status: "completed",
        plot_id: "plot_1",
        version_id: "version_1",
      },
    });
  });

  await screen.findByText(/The demonstration figure is ready/, undefined, {
    timeout: 2_000,
  });
  expect(statusRequests).toBe(2);
  expect(
    screen.getByRole("textbox", { name: "Describe the plot you want" }),
  ).toBeEnabled();
});

test("recovers a required question after its first snapshot request fails", async () => {
  let statusRequests = 0;
  const question = {
    question_id: "question_endpoint",
    prompt: "Which endpoint should be shown?",
    reason: "The available data contains more than one valid endpoint.",
    choices: [
      { choice_id: "os", label: "Overall survival" },
      { choice_id: "pfs", label: "Progression-free survival" },
    ],
    allow_free_text: true,
  };
  const fetchMock = vi.fn(
    async (input: string | URL | Request, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/projects") {
        return jsonResponse(projectResponse());
      }
      if (path === "/api/v1/assistant-turns" && init?.method === "POST") {
        return jsonResponse(plotTurnResponse("run_question"));
      }
      if (
        path ===
        "/api/v1/plot-runs/run_question/questions/question_endpoint/answer"
      ) {
        expect(init?.method).toBe("POST");
        expect(init?.body).toBe(
          JSON.stringify({ schema_version: "1.0", choice_id: "os" }),
        );
        return jsonResponse(
          runningRunResponse("run_question", "selecting_data"),
        );
      }
      if (path === "/api/v1/plot-runs/run_question") {
        statusRequests += 1;
        if (statusRequests === 1) {
          throw new TypeError("Temporary network interruption");
        }
        return jsonResponse({
          schema_version: "1.0",
          run_id: "run_question",
          project_id: "project_1",
          status: "awaiting_input",
          stage: "selecting_data",
          created_at: "2026-09-03T00:00:00Z",
          updated_at: "2026-09-03T00:00:01Z",
          result: null,
          progress: { progress: 22, message: "Waiting for an endpoint" },
          pending_question: question,
          pending_approval: null,
          failure: null,
        });
      }
      throw new Error("Unexpected request: " + path);
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("EventSource", FakeEventSource);
  const user = userEvent.setup();
  renderWorkspace();

  await user.type(
    screen.getByRole("textbox", { name: "Describe the plot you want" }),
    "Create a survival plot",
  );
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

  await act(async () => {
    FakeEventSource.instances[0]?.emit("question.required", {
      schema_version: "1.0",
      event_id: "event_question",
      run_id: "run_question",
      sequence: 1,
      type: "question.required",
      occurred_at: "2026-09-03T00:00:01Z",
      payload: {
        status: "awaiting_input",
        stage: "selecting_data",
        question,
      },
    });
  });

  expect(
    await screen.findByRole(
      "heading",
      { name: "Which endpoint should be shown?" },
      { timeout: 2_000 },
    ),
  ).toBeInTheDocument();
  expect(statusRequests).toBe(2);
  expect(
    screen.getByRole("textbox", { name: "Or answer in your own words" }),
  ).toBeEnabled();

  await user.click(screen.getByRole("radio", { name: "Overall survival" }));
  await user.click(screen.getByRole("button", { name: "Continue" }));

  expect(
    await screen.findByText(question.prompt, {
      selector: ".message-assistant p",
    }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Overall survival", { selector: ".message-user p" }),
  ).toBeInTheDocument();
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
});

test("keeps a successful scientific approval decision in the conversation", async () => {
  const approval = {
    approval_id: "approval_outliers",
    operation: "remove_outliers",
    summary: "Remove observations classified as outliers before plotting.",
    scientific_effect: "The displayed distributions may change.",
  };
  const fetchMock = vi.fn(
    async (input: string | URL | Request, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/projects") {
        return jsonResponse(projectResponse());
      }
      if (path === "/api/v1/assistant-turns" && init?.method === "POST") {
        return jsonResponse(plotTurnResponse("run_approval"));
      }
      if (path === "/api/v1/plot-runs/run_approval") {
        return jsonResponse({
          schema_version: "1.0",
          run_id: "run_approval",
          project_id: "project_1",
          status: "awaiting_approval",
          stage: "planning_transformations",
          created_at: "2026-09-03T00:00:00Z",
          updated_at: "2026-09-03T00:00:01Z",
          result: null,
          progress: { progress: 36, message: "Waiting for approval" },
          pending_question: null,
          pending_approval: approval,
          failure: null,
        });
      }
      if (
        path === "/api/v1/plot-runs/run_approval/approvals/approval_outliers"
      ) {
        expect(init?.method).toBe("POST");
        expect(init?.body).toBe(
          JSON.stringify({ schema_version: "1.0", decision: "reject" }),
        );
        return jsonResponse(
          runningRunResponse("run_approval", "planning_transformations"),
        );
      }
      throw new Error("Unexpected request: " + path);
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("EventSource", FakeEventSource);
  const user = userEvent.setup();
  renderWorkspace();

  await user.type(
    screen.getByRole("textbox", { name: "Describe the plot you want" }),
    "Remove outliers and compare groups",
  );
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

  await act(async () => {
    FakeEventSource.instances[0]?.emit("approval.required", {
      schema_version: "1.0",
      event_id: "event_approval",
      run_id: "run_approval",
      sequence: 1,
      type: "approval.required",
      occurred_at: "2026-09-03T00:00:01Z",
      payload: {
        status: "awaiting_approval",
        stage: "planning_transformations",
        approval,
      },
    });
  });

  expect(
    await screen.findByRole("heading", { name: approval.summary }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Keep data unchanged" }));

  expect(
    await screen.findByText(approval.summary, {
      selector: ".message-assistant p",
    }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Keep data unchanged", { selector: ".message-user p" }),
  ).toBeInTheDocument();
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
});

function renderWorkspace() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <WorkspacePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function projectResponse() {
  return {
    schema_version: "1.0",
    project_id: "project_1",
    name: "Untitled study",
    created_at: "2026-09-03T00:00:00Z",
  };
}

function plotTurnResponse(runId: string) {
  return {
    schema_version: "1.0",
    turn_id: `turn_${runId}`,
    outcome: "plot_run",
    intent: {
      kind: "plot_create",
      subtype: "plot_request",
      normalized_request: "Create a comparison plot",
      confidence: 0.98,
      next_action: "build_context",
      mode_requests: {},
      plot: {
        goal: "Create a comparison plot",
        variable_mentions: {},
        data_hints: [],
        filters: [],
        statistics: [],
        appearance: [],
      },
      refinement: null,
      missing_context: [],
      decision_summary: "This request asks to create a plot.",
      user_reply: null,
    },
    message: null,
    plot_run: {
      schema_version: "1.0",
      run_id: runId,
      status: "queued",
      stage: "received",
      links: {
        status: `/api/v1/plot-runs/${runId}`,
        events: `/api/v1/plot-runs/${runId}/events`,
        cancel: `/api/v1/plot-runs/${runId}/cancel`,
      },
    },
    links: { trace: `/api/v1/assistant-turns/turn_${runId}/trace` },
    created_at: "2026-09-03T00:00:00Z",
  };
}

function runningRunResponse(runId: string, stage: string) {
  return {
    schema_version: "1.0",
    run_id: runId,
    status: "running",
    stage,
    links: {
      status: `/api/v1/plot-runs/${runId}`,
      events: `/api/v1/plot-runs/${runId}/events`,
      cancel: `/api/v1/plot-runs/${runId}/cancel`,
    },
  };
}

function cancelledSnapshot(runId: string) {
  return {
    schema_version: "1.0",
    run_id: runId,
    project_id: "project_1",
    status: "cancelled",
    stage: "received",
    created_at: "2026-09-03T00:00:00Z",
    updated_at: "2026-09-03T00:00:01Z",
    result: null,
    progress: { progress: 0, message: "Run cancelled" },
    pending_question: null,
    pending_approval: null,
    failure: null,
  };
}

function jsonResponse(body: object): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
