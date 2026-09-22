import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { useAssistantPlanner } from "../src/features/plot-run/useAssistantPlanner";

class Events {
  static instance: Events;
  onerror: (() => void) | null = null;
  handler: ((event: MessageEvent<string>) => void) | null = null;
  closed = false;
  constructor() {
    Events.instance = this;
  }
  addEventListener(
    _name: string,
    handler: (event: MessageEvent<string>) => void,
  ) {
    this.handler = handler;
  }
  close() {
    this.closed = true;
  }
  emit(snapshot: object) {
    this.handler?.(
      new MessageEvent("assistant.updated", { data: JSON.stringify(snapshot) }),
    );
  }
}
afterEach(() => vi.unstubAllGlobals());
const links = {
  trace: "/api/v1/assistant-turns/turn_1/trace",
  status: "/api/v1/assistant-turns/turn_1?project_id=project_1",
  events: "/api/v1/assistant-turns/turn_1/events?project_id=project_1",
  cancel: "/api/v1/assistant-turns/turn_1/cancel?project_id=project_1",
};
const response = {
  schema_version: "1.0",
  turn_id: "turn_1",
  outcome: "plot_run",
  intent: {
    kind: "plot_create",
    subtype: "figure",
    normalized_request: "Create a figure",
    confidence: 1,
    next_action: "build_context",
    plot: { goal: "Create a figure" },
    decision_summary: "Ready to render.",
  },
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
  links,
  created_at: "2026-09-10T00:00:00Z",
};

test("stale polling cannot overwrite newer streamed activity or deliver a response twice", async () => {
  let finishRead!: (response: Response) => void;
  vi.stubGlobal("EventSource", Events);
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finishRead = resolve;
        }),
    ),
  );
  const onResponse = vi.fn();
  const { result } = renderHook(() =>
    useAssistantPlanner({ onResponse, onError: vi.fn() }),
  );
  act(() =>
    result.current.track(
      { schema_version: "1.0", turn_id: "turn_1", status: "running", links },
      "project_1",
      "Create a figure",
    ),
  );
  const current = {
    schema_version: "1.0",
    turn_id: "turn_1",
    project_id: "project_1",
    request_text: "Create a figure",
    revision: 5,
    status: "completed",
    activity: [],
    response,
    run_status: "running",
  };
  act(() => Events.instance.emit(current));
  expect(onResponse).toHaveBeenCalledTimes(1);
  expect(result.current.working).toBe(false);
  await act(async () => {
    finishRead(
      new Response(
        JSON.stringify({
          ...current,
          revision: 2,
          status: "running",
          response: null,
        }),
        { headers: { "Content-Type": "application/json" } },
      ),
    );
  });
  expect(result.current.working).toBe(false);
  expect(result.current.turns[0]?.status).toBe("completed");
  act(() =>
    Events.instance.emit({ ...current, revision: 6, run_status: "completed" }),
  );
  await waitFor(() => expect(Events.instance.closed).toBe(true));
  expect(onResponse).toHaveBeenCalledTimes(1);
});
