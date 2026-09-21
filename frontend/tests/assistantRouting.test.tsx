import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { expect, test, vi } from "vitest";

import { WorkspacePage } from "../src/pages/WorkspacePage";

test.each(["social", "plot_create"])(
  "a %s reply does not start plotting",
  async (kind) => {
    const eventSource = vi.fn();
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
          return jsonResponse({
            schema_version: "1.0",
            turn_id: "turn_social",
            outcome: "message",
            intent: {
              kind,
              subtype: "greeting",
              normalized_request: "how are you?",
              confidence: 1,
              next_action: "reply",
              mode_requests: { data: "auto" },
              plot:
                kind === "plot_create" ? { goal: "Plan a comparison" } : null,
              refinement: null,
              missing_context: [],
              decision_summary: "No plotting request was made.",
              user_reply: "I am ready to help with your next plot.",
            },
            message: "I am ready to help with your next plot.",
            plot_run: null,
            links: {
              trace: "/api/v1/assistant-turns/turn_social/trace",
            },
            created_at: "2026-09-03T00:00:01Z",
          });
        }
        throw new Error("Unexpected request: " + path);
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", eventSource);
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
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
    await user.type(input, "how are you?");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await screen.findByText("I am ready to help with your next plot.");
    expect(
      screen.getByRole("heading", { name: /shape the figure/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("New figure")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    await waitFor(() => expect(eventSource).not.toHaveBeenCalled());
  },
);

function jsonResponse(body: object): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
