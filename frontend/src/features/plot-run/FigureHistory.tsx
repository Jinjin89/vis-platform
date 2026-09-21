import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState } from "react";
import {
  createMutationId,
  getPlotVersions,
  resolveArtifactUrl,
} from "../../api/client";
import type { PlotRunSnapshot } from "../../api/schemas/plotRun";
import "./figureHistory.css";

type FigureHistoryProps = {
  snapshot: PlotRunSnapshot;
  disabled: boolean;
  onSelect: (runId: string) => Promise<void>;
  onRestore: (versionId: string, requestId: string) => Promise<boolean>;
};

const HISTORY_OPEN_KEY = "vis-platform.history-open";

export function FigureHistory({
  snapshot,
  disabled,
  onSelect,
  onRestore,
}: FigureHistoryProps) {
  const [open, setOpen] = useState(() => {
    try {
      return window.sessionStorage.getItem(HISTORY_OPEN_KEY) === "true";
    } catch {
      return false;
    }
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const request = useRef({ version: "", id: "" });
  const id = useId();
  const result = snapshot.result!;
  const history = useQuery({
    queryKey: [
      "plot-versions",
      snapshot.project_id,
      result.plot_id,
      result.version_id,
    ],
    queryFn: () => getPlotVersions(snapshot.project_id, result.plot_id),
    enabled: open,
  });
  useEffect(() => {
    try {
      window.sessionStorage.setItem(HISTORY_OPEN_KEY, String(open));
    } catch {
      /* Keep the rail usable when storage is unavailable. */
    }
  }, [open]);

  async function select(runId: string) {
    if (busy || disabled) return;
    setBusy(true);
    setError(null);
    try {
      await onSelect(runId);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The version could not be loaded.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function restore() {
    if (busy || disabled) return;
    if (request.current.version !== result.version_id)
      request.current = { version: result.version_id, id: createMutationId() };
    setBusy(true);
    setError(null);
    try {
      if (await onRestore(result.version_id, request.current.id))
        request.current = { version: "", id: "" };
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The version could not be restored.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside
      className="figure-history"
      data-open={open}
      aria-label="Version history sidebar"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          setOpen(false);
          toggle.current?.focus();
        }
      }}
    >
      <button
        ref={toggle}
        className="history-toggle"
        type="button"
        aria-label={open ? "Collapse figure history" : "History"}
        aria-expanded={open}
        aria-controls={id}
        title={open ? "Collapse history" : "Browse saved versions"}
        onClick={() => setOpen((value) => !value)}
      >
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <path
            d="M3 8a7 7 0 1 1 0 4M3 3v5h5m2-2v4l3 2"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span>History</span>
        <svg
          className="history-chevron"
          viewBox="0 0 20 20"
          fill="none"
          aria-hidden="true"
        >
          <path
            d={open ? "m12 5-5 5 5 5" : "m8 5 5 5-5 5"}
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      {open ? (
        <section
          className="history-content"
          id={id}
          aria-label="Figure history"
          aria-busy={busy}
        >
          {history.isPending ? (
            <p className="history-notice">Loading saved versions…</p>
          ) : history.isError ? (
            <div className="history-notice" role="alert">
              <p>History could not be loaded.</p>
              <button type="button" onClick={() => void history.refetch()}>
                Retry
              </button>
            </div>
          ) : (
            <>
              <div className="history-versions">
                {history.data.versions.map((version, index) => (
                  <button
                    type="button"
                    className="history-version"
                    key={version.version_id}
                    aria-pressed={result.version_id === version.version_id}
                    disabled={busy || disabled}
                    onClick={() => void select(version.run_id)}
                  >
                    <img
                      src={resolveArtifactUrl(version.result.preview.href)}
                      alt=""
                    />
                    <span>
                      <strong>
                        Version {history.data.versions.length - index}
                        {history.data.current_version_id === version.version_id
                          ? " · Current"
                          : ""}
                      </strong>
                      <span>{version.change_summary}</span>
                      <small
                        title={new Date(version.created_at).toLocaleString()}
                      >
                        {new Date(version.created_at).toLocaleDateString(
                          undefined,
                          { month: "short", day: "numeric" },
                        )}
                      </small>
                    </span>
                  </button>
                ))}
              </div>
              <footer>
                <span aria-live="polite">
                  {history.data.current_version_id === result.version_id
                    ? "Viewing the current version"
                    : "Viewing an earlier version"}
                </span>
                {history.data.current_version_id !== result.version_id ? (
                  <button
                    className="history-restore"
                    type="button"
                    disabled={busy || disabled}
                    onClick={() => void restore()}
                  >
                    Restore as new
                  </button>
                ) : null}
              </footer>
            </>
          )}
          {error ? (
            <p className="history-notice inspector-error" role="alert">
              {error}
            </p>
          ) : null}
        </section>
      ) : null}
    </aside>
  );
}
