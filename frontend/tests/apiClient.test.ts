import { afterEach, expect, test, vi } from "vitest";

import { answerQuestion } from "../src/api/client";

afterEach(() => vi.unstubAllGlobals());

test("sends a free-text question answer using the versioned API field", async () => {
  const fetchMock = vi.fn(async () =>
    jsonResponse({
      schema_version: "1.0",
      run_id: "run_1",
      status: "queued",
      stage: "received",
      links: {
        status: "/api/v1/plot-runs/run_1",
        events: "/api/v1/plot-runs/run_1/events",
        cancel: "/api/v1/plot-runs/run_1/cancel",
      },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await answerQuestion("run_1", "question_1", {
    freeText: "Disease-specific survival",
  });

  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/plot-runs/run_1/questions/question_1/answer",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        schema_version: "1.0",
        free_text: "Disease-specific survival",
      }),
    }),
  );
});

function jsonResponse(body: object): Response {
  return new Response(JSON.stringify(body), {
    status: 202,
    headers: { "Content-Type": "application/json" },
  });
}

test("figure downloads use the version-scoped API and preserve the response filename", async () => {
  const { getFigureExport } = await import("../src/api/client");
  const fetcher = vi.fn().mockResolvedValue(
    new Response("svg bytes", {
      headers: {
        "Content-Type": "image/svg+xml",
        "Content-Disposition": 'attachment; filename="study-version.svg"',
      },
    }),
  );
  vi.stubGlobal("fetch", fetcher);
  const exported = await getFigureExport(
    "project_1",
    "plot_1",
    "version_old",
    "svg",
  );
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/projects/project_1/plots/plot_1/versions/version_old/exports/svg",
  );
  expect(exported.filename).toBe("study-version.svg");
  expect(await exported.blob.text()).toBe("svg bytes");
});

test("figure download errors never become a downloaded JSON or HTML file", async () => {
  const { getFigureExport } = await import("../src/api/client");
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response("upstream login page", {
        headers: { "Content-Type": "text/html" },
      }),
    ),
  );
  await expect(getFigureExport("p", "plot", "version", "png")).rejects.toThrow(
    "valid figure",
  );
});
