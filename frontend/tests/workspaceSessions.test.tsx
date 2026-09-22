import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, test, vi } from "vitest";

import { workspaceSessionDocumentSchema } from "../src/api/schemas/workspaceSessions";
import { restoreConversation } from "../src/features/plot-run/conversationHistory";
import { WorkspacePage } from "../src/pages/WorkspacePage";

const links = (turnId: string) => ({
  trace: `/api/v1/assistant-turns/${turnId}/trace`,
  status: `/api/v1/assistant-turns/${turnId}?project_id=project_1`,
  events: `/api/v1/assistant-turns/${turnId}/events?project_id=project_1`,
  cancel: `/api/v1/assistant-turns/${turnId}/cancel?project_id=project_1`,
});
const intent = {
  kind: "plot_create",
  subtype: "plot_request",
  normalized_request: "Compare treatment and control",
  confidence: 0.98,
  next_action: "build_context",
  mode_requests: {},
  plot: { goal: "Compare treatment and control" },
  refinement: null,
  missing_context: [],
  decision_summary: "Plot requested.",
  user_reply: null,
};
const figure = {
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
    title: "Treatment comparison",
    execution_mode: "demo",
    preview: {
      artifact_id: "artifact_1",
      role: "preview",
      media_type: "image/svg+xml",
      href: "/api/v1/artifacts/artifact_1",
      description: "A demonstration comparison plot.",
    },
    controls_mode: "hybrid",
    controls: [],
    validation: { status: "demo_only", warnings: [] },
  },
  progress: null,
  pending_question: null,
  pending_approval: null,
  failure: null,
};
const question = {
  interaction_id: "interaction_1",
  questions: [
    {
      question_id: "emphasis",
      header: "Emphasis",
      prompt: "What should the comparison emphasize?",
      choices: [
        { choice_id: "spread", label: "The full distribution" },
        { choice_id: "mean", label: "Group averages" },
      ],
    },
  ],
};
function snapshot(turnId: string, text: string, fields: object) {
  return {
    schema_version: "1.0",
    turn_id: turnId,
    project_id: "project_1",
    request_text: text,
    revision: 3,
    status: "completed",
    activity: [],
    ...fields,
  };
}
function response(turnId: string, fields: object) {
  return {
    schema_version: "1.0",
    turn_id: turnId,
    intent,
    links: { trace: links(turnId).trace },
    created_at: "2026-09-03T00:00:00Z",
    ...fields,
  };
}
const session = {
  schema_version: "1.0",
  session_id: "session_1",
  project_id: "project_1",
  title: "Treatment comparison",
  created_at: "2026-09-03T00:00:00Z",
  updated_at: "2026-09-03T00:00:05Z",
  figure,
  turns: [
    {
      turn: snapshot("turn_1", "Hello", {
        response: response("turn_1", {
          outcome: "message",
          message: "Hello! What would you like to show?",
        }),
      }),
      links: links("turn_1"),
      answers: [],
      run: null,
    },
    {
      turn: snapshot("turn_2", "Compare treatment and control", {
        run_status: "completed",
        response: response("turn_2", {
          outcome: "plot_run",
          plot_run: {
            schema_version: "1.0",
            run_id: "run_1",
            status: "queued",
            stage: "received",
            links: {
              status: "/api/v1/plot-runs/run_1",
              events: "/api/v1/plot-runs/run_1/events",
              cancel: "/api/v1/plot-runs/run_1/cancel",
            },
          },
        }),
      }),
      links: links("turn_2"),
      answers: [
        {
          question,
          answer: {
            project_id: "project_1",
            interaction_id: "interaction_1",
            answers: [{ question_id: "emphasis", choice_ids: ["spread"] }],
          },
        },
      ],
      run: figure,
    },
    {
      turn: snapshot("turn_3", "Use my uploaded data", {
        status: "failed",
        error: { code: "ASSISTANT_FAILED", message: "Please retry." },
      }),
      links: links("turn_3"),
      answers: [],
      run: null,
    },
  ],
};

const { turns: _turns, figure: _figure, ...summary } = session;

afterEach(() => vi.unstubAllGlobals());

test("a saved conversation reads as it did, and an unfinished request is resumed", () => {
  const restored = restoreConversation(
    workspaceSessionDocumentSchema.parse(session),
  );

  expect(
    restored.messages.map((message) => [message.role, message.content]),
  ).toEqual([
    ["user", "Hello"],
    ["assistant", "Hello! What would you like to show?"],
    ["user", "Compare treatment and control"],
    ["assistant", "What should the comparison emphasize?"],
    ["user", "The full distribution"],
    [
      "assistant",
      "The demonstration figure is ready. Fine-tune it below or export the figure.",
    ],
    ["user", "Use my uploaded data"],
    ["assistant", "Please retry."],
  ]);
  expect(restored.messages[5]?.turnId).toBe("turn_2");
  expect(restored.messages[7]?.tone).toBe("error");
  expect(restored.interactions).toEqual(["interaction_1"]);
  expect(restored.figure?.run_id).toBe("run_1");
  expect(restored.activities.map((turn) => turn.turnId)).toEqual([
    "turn_1",
    "turn_2",
    "turn_3",
  ]);
  expect(restored.pendingTurn).toBeNull();

  const waiting = restoreConversation(
    workspaceSessionDocumentSchema.parse({
      ...session,
      turns: [
        ...session.turns,
        {
          turn: snapshot("turn_4", "Ask me first", {
            status: "awaiting_input",
            question,
          }),
          links: links("turn_4"),
          answers: [],
          run: null,
        },
      ],
    }),
  );
  expect(waiting.pendingTurn).toEqual({
    accepted: {
      schema_version: "1.0",
      turn_id: "turn_4",
      status: "running",
      links: links("turn_4"),
    },
    text: "Ask me first",
  });
});

test("opening the Workspace continues the latest conversation and adds to it", async () => {
  window.localStorage.setItem("vis-platform.project-id", "project_1");
  const turns: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/projects/project_1")
        return json({
          schema_version: "1.0",
          project_id: "project_1",
          name: "Untitled study",
          created_at: "2026-09-03T00:00:00Z",
        });
      if (path === "/api/v1/projects/project_1/workspace-sessions?offset=0")
        return json({
          sessions: [
            summary,
            { ...summary, session_id: "session_0", title: "An earlier idea" },
          ],
          total: 2,
          offset: 0,
        });
      if (path === "/api/v1/projects/project_1/workspace-sessions/session_1")
        return json(session);
      if (path === "/api/v1/assistant-turns" && init?.method === "POST") {
        turns.push(JSON.parse(String(init.body)));
        return json(
          response("turn_5", {
            outcome: "message",
            message: "The legend can go below the plot.",
          }),
        );
      }
      throw new Error("Unexpected request: " + path);
    }),
  );
  const user = userEvent.setup();
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/workspace"]}>
        <WorkspacePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  expect(
    await screen.findByText("Hello! What would you like to show?"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("img", { name: "A demonstration comparison plot." }),
  ).toBeInTheDocument();
  const list = screen.getByRole("navigation", { name: "Conversations" });
  expect(
    within(list).getByRole("button", { name: /Treatment comparison/ }),
  ).toHaveAttribute("aria-current", "page");
  expect(
    within(list).getByRole("button", { name: /An earlier idea/ }),
  ).toBeInTheDocument();

  await user.type(
    screen.getByRole("textbox", { name: "Describe the plot you want" }),
    "Where should the legend go?",
  );
  await user.click(screen.getByRole("button", { name: "Send" }));

  await screen.findByText("The legend can go below the plot.");
  await waitFor(() => expect(turns).toHaveLength(1));
  expect(turns[0]).toMatchObject({
    session_id: "session_1",
    base_version_id: "version_1",
  });
});

test("a first message stays on screen while its study and conversation are created", async () => {
  let createProject!: () => void;
  let opened = false;
  const sessions: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/projects" && init?.method === "POST") {
        await new Promise<void>((resolve) => (createProject = resolve));
        return json({
          schema_version: "1.0",
          project_id: "project_1",
          name: "Untitled study",
          created_at: "2026-09-03T00:00:00Z",
        });
      }
      if (path === "/api/v1/projects/project_1/workspace-sessions?offset=0")
        return json(
          sessions.length
            ? { sessions: [summary], total: 1, offset: 0 }
            : { sessions: [], total: 0, offset: 0 },
        );
      if (
        opened &&
        path === "/api/v1/projects/project_1/workspace-sessions/session_1"
      )
        return json(session);
      if (
        path === "/api/v1/projects/project_1/workspace-sessions" &&
        init?.method === "POST"
      ) {
        sessions.push(JSON.parse(String(init.body)));
        return json(summary);
      }
      if (path === "/api/v1/assistant-turns" && init?.method === "POST")
        return json(
          response("turn_1", {
            outcome: "message",
            message: "Hello! What would you like to show?",
          }),
        );
      throw new Error("Unexpected request: " + path);
    }),
  );
  const user = userEvent.setup();
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter initialEntries={["/workspace"]}>
        <WorkspacePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  await user.type(
    screen.getByRole("textbox", { name: "Describe the plot you want" }),
    "Hello",
  );
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(createProject).toBeDefined());
  expect(screen.queryByText("Opening your conversation…")).toBeNull();
  createProject();

  expect(
    await screen.findByText("Hello! What would you like to show?"),
  ).toBeInTheDocument();
  expect(sessions).toEqual([expect.objectContaining({ title: "Hello" })]);
  // Coming back to the conversation later reopens it from the backend.
  opened = true;
  await user.click(screen.getByRole("button", { name: "New conversation" }));
  await waitFor(() =>
    expect(
      screen.queryByText("Hello! What would you like to show?"),
    ).toBeNull(),
  );
  await user.click(
    await screen.findByRole("button", { name: /Treatment comparison/ }),
  );
  expect(
    await screen.findByRole("img", {
      name: "A demonstration comparison plot.",
    }),
  ).toBeInTheDocument();
  expect(window.localStorage.getItem("vis-platform.project-id")).toBe(
    "project_1",
  );
  expect(
    within(screen.getByRole("navigation", { name: "Conversations" })).getByRole(
      "button",
      { name: "New conversation" },
    ),
  ).toBeInTheDocument();
});

function json(body: object): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
