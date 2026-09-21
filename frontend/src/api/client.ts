import type { z } from "zod";
import type { PlannerAnswer } from "./schemas/planner";

import {
  type AssistantTurnResponse,
  type AssistantTurnAccepted,
  type AssistantTurnSnapshot,
  assistantSubmissionSchema,
  assistantTurnAcceptedSchema,
  assistantTurnSnapshotSchema,
  type DeveloperTraceResponse,
  type PlotRunAccepted,
  type PlotRunSnapshot,
  type Project,
  type ParameterValues,
  type PlotVersionList,
  plotVersionListSchema,
  apiErrorEnvelopeSchema,
  assistantTurnResponseSchema,
  developerTraceResponseSchema,
  plotRunAcceptedSchema,
  plotRunSnapshotSchema,
  projectSchema,
} from "./schemas/plotRun";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiClientError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly recoverable: boolean,
    readonly details: Record<string, unknown> | null = null,
  ) {
    super(message);
    this.name = "ApiClientError";
  }
}

export type QuestionAnswer =
  | { choiceId: string; freeText?: never }
  | { choiceId?: never; freeText: string };

export function apiUrl(path: string): string {
  return API_BASE + path;
}

export async function request<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(apiUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  await checkResponse(response);
  return schema.parse(await response.json());
}

export async function checkResponse(response: Response): Promise<void> {
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // The stable fallback below handles non-JSON upstream failures.
    }
    const parsed = apiErrorEnvelopeSchema.safeParse(body);
    if (parsed.success) {
      throw new ApiClientError(
        parsed.data.error.code,
        parsed.data.error.message,
        parsed.data.error.recoverable,
        parsed.data.error.details ?? null,
      );
    }
    throw new ApiClientError(
      "UNEXPECTED_RESPONSE",
      "The backend returned an unexpected error response.",
      true,
    );
  }
}

export function createProject(name = "Untitled study"): Promise<Project> {
  return request("/api/v1/projects", projectSchema, {
    method: "POST",
    body: JSON.stringify({ schema_version: "1.0", name }),
  });
}

export function createAssistantTurn(
  projectId: string,
  text: string,
  baseVersionId?: string,
): Promise<AssistantTurnResponse> {
  return request("/api/v1/assistant-turns", assistantTurnResponseSchema, {
    method: "POST",
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
      base_version_id: baseVersionId,
    }),
  });
}

export function getDeveloperTrace(
  path: string,
  accessToken: string,
): Promise<DeveloperTraceResponse> {
  return request(path, developerTraceResponseSchema, {
    headers: {
      "X-Developer-Trace-Token": accessToken,
    },
  });
}

export function getPlotRun(path: string): Promise<PlotRunSnapshot> {
  return request(path, plotRunSnapshotSchema);
}

export function createRunEventSource(path: string): EventSource {
  return new EventSource(apiUrl(path));
}

export function answerQuestion(
  runId: string,
  questionId: string,
  answer: QuestionAnswer,
): Promise<PlotRunAccepted> {
  const payload =
    answer.choiceId == null
      ? { schema_version: "1.0", free_text: answer.freeText }
      : { schema_version: "1.0", choice_id: answer.choiceId };
  return request(
    "/api/v1/plot-runs/" + runId + "/questions/" + questionId + "/answer",
    plotRunAcceptedSchema,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function decideApproval(
  runId: string,
  approvalId: string,
  decision: "approve" | "reject",
): Promise<PlotRunAccepted> {
  return request(
    "/api/v1/plot-runs/" + runId + "/approvals/" + approvalId,
    plotRunAcceptedSchema,
    {
      method: "POST",
      body: JSON.stringify({ schema_version: "1.0", decision }),
    },
  );
}

export function cancelPlotRun(path: string): Promise<PlotRunSnapshot> {
  return request(path, plotRunSnapshotSchema, { method: "POST" });
}

export function resolveArtifactUrl(path: string): string {
  return apiUrl(path);
}

export function createMutationId(): string {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `request-${Date.now()}-${Math.random().toString(36).slice(2)}`
  );
}

export function updatePlotParameters(
  projectId: string,
  plotId: string,
  baseVersionId: string,
  changes: ParameterValues,
  requestId: string,
): Promise<PlotRunAccepted> {
  return request(
    `/api/v1/plots/${encodeURIComponent(plotId)}/parameters`,
    plotRunAcceptedSchema,
    {
      method: "POST",
      headers: { "Idempotency-Key": requestId },
      body: JSON.stringify({
        schema_version: "1.0",
        project_id: projectId,
        base_version_id: baseVersionId,
        changes,
      }),
    },
  );
}

export function getPlotVersions(
  projectId: string,
  plotId: string,
): Promise<PlotVersionList> {
  return request(
    `/api/v1/projects/${encodeURIComponent(projectId)}/plots/${encodeURIComponent(plotId)}/versions`,
    plotVersionListSchema,
  );
}

export function restorePlotVersion(
  projectId: string,
  plotId: string,
  sourceVersionId: string,
  requestId: string,
): Promise<PlotRunAccepted> {
  return request(
    `/api/v1/plots/${encodeURIComponent(plotId)}/restore`,
    plotRunAcceptedSchema,
    {
      method: "POST",
      headers: { "Idempotency-Key": requestId },
      body: JSON.stringify({
        schema_version: "1.0",
        project_id: projectId,
        source_version_id: sourceVersionId,
      }),
    },
  );
}

export function startAssistantTurn(
  projectId: string,
  text: string,
  baseVersionId?: string,
  datasetIds: string[] = [],
  resultIds: string[] = [],
  referenceImageIds?: string[],
  requestId?: string,
  parameterChanges?: ParameterValues,
): Promise<AssistantTurnResponse | AssistantTurnAccepted> {
  return request("/api/v1/assistant-turns", assistantSubmissionSchema, {
    method: "POST",
    headers: {
      Prefer: "respond-async",
      ...(requestId ? { "Idempotency-Key": requestId } : {}),
    },
    body: JSON.stringify({
      schema_version: "1.0",
      project_id: projectId,
      request: {
        text,
        ...(referenceImageIds
          ? { reference_image_ids: referenceImageIds }
          : {}),
        generation_mode: "auto",
        gallery_mode: "off",
        controls_mode: "hybrid",
      },
      data_scope: datasetIds.length
        ? { mode: "selected", bundle_ids: datasetIds }
        : { mode: "auto" },
      result_ids: resultIds,
      base_version_id: baseVersionId,
      ...(parameterChanges && Object.keys(parameterChanges).length
        ? { parameter_changes: parameterChanges }
        : {}),
    }),
  });
}
export function getAssistantState(
  path: string,
): Promise<AssistantTurnSnapshot> {
  return request(path, assistantTurnSnapshotSchema);
}
export function answerPlanner(
  turnId: string,
  projectId: string,
  interactionId: string,
  answers: PlannerAnswer[],
): Promise<AssistantTurnAccepted> {
  return request(
    `/api/v1/assistant-turns/${encodeURIComponent(turnId)}/answer`,
    assistantTurnAcceptedSchema,
    {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        interaction_id: interactionId,
        answers,
      }),
    },
  );
}
export function cancelAssistant(path: string): Promise<AssistantTurnSnapshot> {
  return request(path, assistantTurnSnapshotSchema, { method: "POST" });
}

export type FigureExportFormat =
  import("./generated/schema").components["schemas"]["FigureExportFormat"];

export async function getFigureExport(
  projectId: string,
  plotId: string,
  versionId: string,
  format: FigureExportFormat,
): Promise<{ blob: Blob; filename: string }> {
  const path = `/api/v1/projects/${encodeURIComponent(projectId)}/plots/${encodeURIComponent(plotId)}/versions/${encodeURIComponent(versionId)}/exports/${format}`;
  const response = await fetch(apiUrl(path));
  await checkResponse(response);
  const expected = {
    png: "image/png",
    pdf: "application/pdf",
    svg: "image/svg+xml",
  }[format];
  if (response.headers.get("Content-Type")?.split(";")[0] !== expected)
    throw new ApiClientError(
      "INVALID_EXPORT",
      "The export did not return a valid figure. Please retry.",
      true,
    );
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const encoded = /filename\*=utf-8''([^;]+)/i.exec(disposition)?.[1];
  const plain = /filename="([^"]+)"/i.exec(disposition)?.[1];
  let filename = plain ?? `vis-platform-figure.${format}`;
  if (encoded) {
    try {
      filename = decodeURIComponent(encoded);
    } catch {
      /* Use the fallback filename. */
    }
  }
  return { blob: await response.blob(), filename };
}
