import { request } from "./client";
import {
  workspaceSessionDocumentSchema,
  workspaceSessionListSchema,
  workspaceSessionSchema,
} from "./schemas/workspaceSessions";

const base = (projectId: string) =>
  `/api/v1/projects/${encodeURIComponent(projectId)}/workspace-sessions`;

export const listWorkspaceSessions = (projectId: string, offset = 0) =>
  request(`${base(projectId)}?offset=${offset}`, workspaceSessionListSchema);
export const getWorkspaceSession = (projectId: string, sessionId: string) =>
  request(
    `${base(projectId)}/${encodeURIComponent(sessionId)}`,
    workspaceSessionDocumentSchema,
  );
export const createWorkspaceSession = (
  projectId: string,
  title: string,
  requestId: string,
) =>
  request(base(projectId), workspaceSessionSchema, {
    method: "POST",
    body: JSON.stringify({
      schema_version: "1.0",
      request_id: requestId,
      title,
    }),
  });
