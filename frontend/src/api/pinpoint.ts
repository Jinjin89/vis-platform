import { request } from "./client";
import type { components } from "./generated/schema";
import { assistantTurnAcceptedSchema } from "./schemas/plotRun";

export type PlotMark = components["schemas"]["PlotMark"];

/**
 * Ask about or change a plot. Marks tie the request's words ("this", "①") to places on the
 * image of the version they were placed on. Without a version, a new plot is made.
 */
export const sendPinpointRequest = (
  projectId: string,
  {
    text,
    baseVersionId,
    marks,
    requestId,
  }: {
    text: string;
    baseVersionId: string | null;
    marks: PlotMark[];
    requestId: string;
  },
) =>
  request("/api/v1/assistant-turns", assistantTurnAcceptedSchema, {
    method: "POST",
    headers: { Prefer: "respond-async", "Idempotency-Key": requestId },
    body: JSON.stringify({
      schema_version: "1.0",
      project_id: projectId,
      request: {
        text,
        generation_mode: "auto",
        gallery_mode: "off",
        controls_mode: "hybrid",
      },
      data_scope: { mode: "auto" },
      ...(baseVersionId ? { base_version_id: baseVersionId } : {}),
      ...(marks.length ? { plot_marks: marks } : {}),
    }),
  });
