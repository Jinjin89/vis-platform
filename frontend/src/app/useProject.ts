import { useCallback, useEffect, useRef, useState } from "react";
import { ApiClientError, createProject, getProject } from "../api/client";

const STORAGE_KEY = "vis-platform.project-id";

type ProjectState = {
  projectId: string | null;
  opening: boolean;
  error: string | null;
};

/**
 * The study every interface works in. It is remembered in this browser, so a later visit
 * reopens the same conversations, canvases, reports, slides, and figures.
 * With `create`, a new study is started when none is remembered; otherwise `ensure` starts
 * one when it is first needed.
 */
export function useProject(create: boolean) {
  const [state, setState] = useState<ProjectState>(() => ({
    projectId: null,
    opening: create || storedProject() !== null,
    error: null,
  }));
  const current = useRef<string | null>(null);
  const pending = useRef<Promise<string | null> | null>(null);
  // Opening shows its progress and failure; a study started on demand reports to its caller.
  const open = useCallback((createNew: boolean, shown: boolean) => {
    pending.current ??= resolveProject(createNew).finally(() => {
      pending.current = null;
    });
    return pending.current.then(
      (projectId) => {
        current.current = projectId;
        setState({ projectId, opening: false, error: null });
        return projectId;
      },
      (reason: unknown) => {
        if (shown)
          setState((previous) => ({
            ...previous,
            opening: false,
            error:
              reason instanceof Error
                ? reason.message
                : "The study could not be opened.",
          }));
        throw reason;
      },
    );
  }, []);
  // The study opens once; later attempts go through ensure or retry.
  useEffect(() => {
    if (state.opening) void open(create, true).catch(() => undefined);
  }, []);
  const ensure = useCallback(async () => {
    const opened =
      current.current ??
      (await (pending.current ?? Promise.resolve(null)).catch(() => null));
    return opened ?? (await open(true, false))!;
  }, [open]);
  const retry = useCallback(() => {
    setState((previous) => ({ ...previous, opening: true, error: null }));
    void open(create, true).catch(() => undefined);
  }, [create, open]);
  return { ...state, ensure, retry };
}

async function resolveProject(create: boolean): Promise<string | null> {
  const stored = storedProject();
  if (stored) {
    try {
      const project = await getProject(stored);
      remember(project.project_id);
      return project.project_id;
    } catch (reason) {
      // A reset backend no longer has the study; anything else may be temporary.
      if (!(reason instanceof ApiClientError && reason.code === "NOT_FOUND"))
        throw reason;
      forget();
    }
  }
  if (!create) return null;
  const project = await createProject();
  remember(project.project_id);
  return project.project_id;
}

function storedProject(): string | null {
  try {
    // Earlier versions kept the study only for the browser tab.
    return (
      window.localStorage.getItem(STORAGE_KEY) ??
      window.sessionStorage.getItem(STORAGE_KEY)
    );
  } catch {
    return null;
  }
}

function remember(projectId: string) {
  try {
    window.localStorage.setItem(STORAGE_KEY, projectId);
  } catch {
    /* Without storage the study lasts for this page only. */
  }
}

function forget() {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    /* Nothing is stored. */
  }
}
