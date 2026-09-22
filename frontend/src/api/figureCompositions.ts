import type { PlannerAnswer } from "./schemas/planner";
import type { ParameterValues } from "./schemas/plotRun";
import {
  EXPORT_MEDIA_TYPES,
  downloadAttachment,
  request,
  type FigureExportFormat,
} from "./client";
import {
  figureContentSchema,
  figureDocumentSchema,
  figureHistorySchema,
  figureListSchema,
  type FigureArrangement,
  type FigureContent,
  type FigureOperation,
} from "./schemas/figureCompositions";

export type FigureRefinement = {
  panel_id: string;
  instructions: string;
  parameter_changes: ParameterValues;
};

const base = (projectId: string) =>
  `/api/v1/projects/${encodeURIComponent(projectId)}/figure-compositions`;
const figurePath = (projectId: string, compositionId: string) =>
  `${base(projectId)}/${encodeURIComponent(compositionId)}`;

export const listFigures = (projectId: string, offset = 0) =>
  request(`${base(projectId)}?offset=${offset}`, figureListSchema);
export const getFigure = (projectId: string, compositionId: string) =>
  request(figurePath(projectId, compositionId), figureDocumentSchema);
export const createFigure = (
  projectId: string,
  content: FigureContent,
  requestId: string,
) =>
  request(base(projectId), figureDocumentSchema, {
    method: "POST",
    body: JSON.stringify({ request_id: requestId, content }),
  });
export const saveFigure = (
  projectId: string,
  compositionId: string,
  baseRevision: number,
  content: FigureContent,
  summary: string,
) =>
  request(figurePath(projectId, compositionId), figureDocumentSchema, {
    method: "PUT",
    body: JSON.stringify({ base_revision: baseRevision, content, summary }),
  });
export const applyFigureOperations = (
  projectId: string,
  compositionId: string,
  baseRevision: number,
  operations: FigureOperation[],
  requestId: string,
  summary: string,
) =>
  request(
    `${figurePath(projectId, compositionId)}/operations`,
    figureDocumentSchema,
    {
      method: "POST",
      body: JSON.stringify({
        request_id: requestId,
        base_revision: baseRevision,
        operations,
        summary,
      }),
    },
  );
export const arrangeFigure = (
  projectId: string,
  compositionId: string,
  baseRevision: number,
  requestId: string,
  options: {
    arrangement?: FigureArrangement;
    render?: boolean;
    summary: string;
  },
) =>
  request(
    `${figurePath(projectId, compositionId)}/arrange`,
    figureDocumentSchema,
    {
      method: "POST",
      body: JSON.stringify({
        request_id: requestId,
        base_revision: baseRevision,
        arrangement: options.arrangement ?? null,
        render: options.render ?? false,
        summary: options.summary,
      }),
    },
  );
export const renderFigurePanels = (
  projectId: string,
  compositionId: string,
  requestId: string,
  panels: Record<string, { width_mm: number; height_mm: number }>,
) =>
  request(
    `${figurePath(projectId, compositionId)}/renders`,
    figureDocumentSchema,
    {
      method: "POST",
      body: JSON.stringify({ request_id: requestId, panels }),
    },
  );
export const sendFigureMessage = (
  projectId: string,
  compositionId: string,
  input: {
    request_id: string;
    message: string;
    selection?: { panel_ids: string[] };
    /** Slots to fill from their descriptions, without planning. */
    fill?: string[];
    /** A plot panel to refine directly, without planning. */
    refine?: FigureRefinement;
  },
) =>
  request(
    `${figurePath(projectId, compositionId)}/messages`,
    figureDocumentSchema,
    {
      method: "POST",
      body: JSON.stringify(input),
    },
  );
export const answerFigureMessage = (
  projectId: string,
  compositionId: string,
  messageId: string,
  interactionId: string,
  answers: PlannerAnswer[],
) =>
  request(
    `${figurePath(projectId, compositionId)}/messages/${encodeURIComponent(messageId)}/answer`,
    figureDocumentSchema,
    {
      method: "POST",
      body: JSON.stringify({ interaction_id: interactionId, answers }),
    },
  );
export const cancelFigureMessage = (
  projectId: string,
  compositionId: string,
  messageId: string,
) =>
  request(
    `${figurePath(projectId, compositionId)}/messages/${encodeURIComponent(messageId)}/cancel`,
    figureDocumentSchema,
    { method: "POST" },
  );
export const listFigureHistory = (
  projectId: string,
  compositionId: string,
  offset = 0,
) =>
  request(
    `${figurePath(projectId, compositionId)}/history?offset=${offset}`,
    figureHistorySchema,
  );
export const getFigureRevision = (
  projectId: string,
  compositionId: string,
  revision: number,
) =>
  request(
    `${figurePath(projectId, compositionId)}/revisions/${revision}`,
    figureContentSchema,
  );
export const exportFigureContent = (projectId: string, compositionId: string) =>
  request(
    `${figurePath(projectId, compositionId)}/content`,
    figureContentSchema,
  );
export const downloadFigure = (
  projectId: string,
  compositionId: string,
  format: FigureExportFormat,
) =>
  downloadAttachment(
    `${figurePath(projectId, compositionId)}/exports/${format}`,
    EXPORT_MEDIA_TYPES[format],
    `figure.${format}`,
  );
