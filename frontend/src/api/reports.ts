import { request } from "./client";
import {
  reportContentSchema,
  reportDocumentSchema,
  reportFiguresSchema,
  reportHistorySchema,
  reportListSchema,
} from "./schemas/reports";
import type {
  ReportContent,
  ReportImportContent,
  ReportGenerateRequest,
} from "./schemas/reports";

const base = (projectId: string) =>
  `/api/v1/projects/${encodeURIComponent(projectId)}/reports`;
const reportPath = (projectId: string, reportId: string) =>
  `${base(projectId)}/${encodeURIComponent(reportId)}`;
export const listReports = (projectId: string, offset = 0) =>
  request(`${base(projectId)}?offset=${offset}`, reportListSchema);
export const getReport = (projectId: string, reportId: string) =>
  request(reportPath(projectId, reportId), reportDocumentSchema);
export const createReport = (
  projectId: string,
  content: ReportImportContent,
  requestId: string,
) =>
  request(base(projectId), reportDocumentSchema, {
    method: "POST",
    body: JSON.stringify({ content, request_id: requestId }),
  });
export const saveReport = (
  projectId: string,
  reportId: string,
  baseRevision: number,
  content: ReportContent,
  summary: string,
) =>
  request(reportPath(projectId, reportId), reportDocumentSchema, {
    method: "PUT",
    body: JSON.stringify({ base_revision: baseRevision, content, summary }),
  });
export const generateReportContent = (
  projectId: string,
  reportId: string,
  input: ReportGenerateRequest,
) =>
  request(`${reportPath(projectId, reportId)}/edits`, reportDocumentSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });
export const cancelReportEdit = (
  projectId: string,
  reportId: string,
  editId: string,
) =>
  request(
    `${reportPath(projectId, reportId)}/edits/${encodeURIComponent(editId)}/cancel`,
    reportDocumentSchema,
    { method: "POST" },
  );
export const listReportHistory = (
  projectId: string,
  reportId: string,
  offset = 0,
) =>
  request(
    `${reportPath(projectId, reportId)}/revisions?offset=${offset}`,
    reportHistorySchema,
  );
export const getReportRevision = (
  projectId: string,
  reportId: string,
  revision: number,
) =>
  request(
    `${reportPath(projectId, reportId)}/revisions/${revision}`,
    reportContentSchema,
  );
export const listReportFigures = (
  projectId: string,
  offset = 0,
  linked = false,
) =>
  request(
    `${base(projectId)}/figures?offset=${offset}&linked=${linked}`,
    reportFiguresSchema,
  );

export const applyReportOperations = (
  projectId: string,
  reportId: string,
  baseRevision: number,
  operations: import("./schemas/reports").ReportOperation[],
  requestId: string,
  summary: string,
) =>
  request(
    reportPath(projectId, reportId) + "/operations",
    reportDocumentSchema,
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
export const sendReportMessage = (
  projectId: string,
  reportId: string,
  input: import("./schemas/reports").ReportMessageRequest,
) =>
  request(reportPath(projectId, reportId) + "/messages", reportDocumentSchema, {
    method: "POST",
    body: JSON.stringify(input),
  });
export const answerReportMessage = (
  projectId: string,
  reportId: string,
  messageId: string,
  interactionId: string,
  answers: import("./schemas/planner").PlannerAnswer[],
) =>
  request(
    reportPath(projectId, reportId) +
      "/messages/" +
      encodeURIComponent(messageId) +
      "/answer",
    reportDocumentSchema,
    {
      method: "POST",
      body: JSON.stringify({ interaction_id: interactionId, answers }),
    },
  );
export const cancelReportMessage = (
  projectId: string,
  reportId: string,
  messageId: string,
) =>
  request(
    reportPath(projectId, reportId) +
      "/messages/" +
      encodeURIComponent(messageId) +
      "/cancel",
    reportDocumentSchema,
    { method: "POST" },
  );
