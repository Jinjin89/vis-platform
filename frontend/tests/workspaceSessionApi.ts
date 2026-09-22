/** Answers the Workspace conversation requests the way a backend with no saved ones would. */
export function workspaceSessionResponse(
  path: string,
  init?: RequestInit,
): Response | null {
  const match = /^\/api\/v1\/projects\/([^/]+)\/workspace-sessions(\?|$)/.exec(
    path,
  );
  if (!match) return null;
  const body =
    init?.method === "POST"
      ? {
          schema_version: "1.0",
          session_id: "session_1",
          project_id: match[1],
          title: JSON.parse(String(init.body)).title,
          created_at: "2026-09-03T00:00:00Z",
          updated_at: "2026-09-03T00:00:00Z",
        }
      : { sessions: [], total: 0, offset: 0 };
  return new Response(JSON.stringify(body), {
    status: init?.method === "POST" ? 201 : 200,
    headers: { "Content-Type": "application/json" },
  });
}
