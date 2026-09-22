import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createMutationId, resolveArtifactUrl } from "../../api/client";
import {
  getFigureRevision,
  listFigureHistory,
  type FigureRefinement,
} from "../../api/figureCompositions";
import { uploadReferenceImage } from "../../api/referenceImages";
import { listReportFigures } from "../../api/reports";
import type {
  FigureContent,
  FigureDocument,
} from "../../api/schemas/figureCompositions";
import type { ParameterValues, PlotResult } from "../../api/schemas/plotRun";
import type { ReferenceImage } from "../../api/schemas/referenceImages";
import { DatasetSelector } from "../datasets/DatasetSelector";
import { FigureInspector as PlotInspector } from "../plot-run/FigureInspector";
import { validValue } from "../plot-run/ParameterForm";
import { ReportDialog } from "../reports/ReportDialog";
import { PAGE_PRESETS } from "./figureGeometry";

const message = (reason: unknown, fallback: string) =>
  reason instanceof Error ? reason.message : fallback;

export type NewFigure = {
  title: string;
  preset: string;
  datasetIds: string[];
  /** What the figure should show; the assistant starts building from it. */
  description: string;
};

export function NewFigureDialog({
  projectId,
  busy,
  error,
  onCreate,
  onClose,
}: {
  projectId: string;
  busy: boolean;
  error: string | null;
  onCreate: (figure: NewFigure) => void;
  onClose: () => void;
}) {
  const [title, setTitle] = useState("Figure 1");
  const [preset, setPreset] = useState("a4-width");
  const [datasetIds, setDatasetIds] = useState<string[]>([]);
  const [description, setDescription] = useState("");
  return (
    <ReportDialog title="New figure" onClose={onClose}>
      <form
        className="report-dialog-form"
        onSubmit={(event) => {
          event.preventDefault();
          onCreate({
            title: title.trim(),
            preset,
            datasetIds,
            description: description.trim(),
          });
        }}
      >
        <label>
          Figure title
          <input
            autoFocus
            value={title}
            maxLength={200}
            required
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label>
          Page
          <select
            value={preset}
            onChange={(event) => setPreset(event.target.value)}
          >
            {PAGE_PRESETS.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <p>
          Auto height ends the page below the last panel, which suits figures
          shorter than a full page. You can change the page at any time.
        </p>
        <div className="report-data-choice">
          <strong>Data for this figure</strong>
          <DatasetSelector
            projectId={projectId}
            ensureProject={async () => projectId}
            selectedIds={datasetIds}
            onSelect={setDatasetIds}
            resultIds={[]}
            onUseResult={() => undefined}
            datasetsOnly
            disabled={busy}
          />
        </div>
        <label>
          What should this figure show? (optional)
          <textarea
            value={description}
            rows={4}
            maxLength={8000}
            placeholder="For example: Figure 2 — treatment response: tumour growth over time, final volumes by group, and marker expression."
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <small>
          With a description, the assistant plans the panels and creates each
          plot from the data. Leave it empty to start with a blank page.
        </small>
        {error ? (
          <p role="alert" className="report-error">
            {error}
          </p>
        ) : null}
        <footer>
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            className="report-primary"
            disabled={busy || !title.trim()}
          >
            {description.trim() ? "Create and build" : "Create figure"}
          </button>
        </footer>
      </form>
    </ReportDialog>
  );
}

export function AddPlotDialog({
  projectId,
  onAdd,
  onClose,
}: {
  projectId: string;
  onAdd: (figure: PlotResult) => Promise<boolean>;
  onClose: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const figures = useQuery({
    queryKey: ["composition-plot-library", projectId, offset],
    queryFn: () => listReportFigures(projectId, offset),
  });
  return (
    <ReportDialog title="Add a saved plot" onClose={onClose} wide>
      <div className="report-dialog-form">
        <p>
          Plots created in Workspace, Canvas, Report, or Slides. The panel keeps
          this exact version until you apply an update.
        </p>
        {figures.isPending ? (
          <p>Loading plots…</p>
        ) : figures.isError ? (
          <p role="alert">
            {figures.error.message}{" "}
            <button type="button" onClick={() => void figures.refetch()}>
              Retry
            </button>
          </p>
        ) : figures.data.figures.length ? (
          <div className="report-saved-figures">
            {figures.data.figures.map((figure) => (
              <button
                type="button"
                key={figure.version_id}
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setError(null);
                  try {
                    if (await onAdd(figure)) onClose();
                  } catch (reason) {
                    setError(message(reason, "The plot could not be added."));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <img
                  src={resolveArtifactUrl(figure.preview.href)}
                  alt={figure.title ?? figure.preview.description}
                />
                <strong>{figure.title ?? "Saved plot"}</strong>
              </button>
            ))}
          </div>
        ) : (
          <p>
            No saved plots yet. Create one in Workspace, or ask the figure
            assistant.
          </p>
        )}
        {error ? (
          <p className="report-error" role="alert">
            {error}
          </p>
        ) : null}
        <footer>
          <button
            type="button"
            disabled={!offset}
            onClick={() => setOffset(offset - 30)}
          >
            Previous
          </button>
          <span>{figures.data?.total ?? 0} plots</span>
          <button
            type="button"
            disabled={offset + 30 >= (figures.data?.total ?? 0)}
            onClick={() => setOffset(offset + 30)}
          >
            Next
          </button>
        </footer>
      </div>
    </ReportDialog>
  );
}

/** Refine a plot panel with the plot agent, as a figure is refined in a report. */
export function RefinePanelDialog({
  document,
  panelId,
  versionId,
  onRefine,
  onClose,
}: {
  document: FigureDocument;
  panelId: string;
  versionId: string;
  onRefine: (requestId: string, refine: FigureRefinement) => Promise<boolean>;
  onClose: () => void;
}) {
  const figure = document.figures[versionId];
  const label = document.panels[panelId]?.label;
  const [instructions, setInstructions] = useState("");
  const [parameters, setParameters] = useState<ParameterValues>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef({ key: "", id: "" });
  const valid = (figure?.controls ?? []).every((control) =>
    validValue(control, parameters[control.id] ?? control.value),
  );
  async function refine(changes = parameters) {
    if (
      busy ||
      !valid ||
      (!instructions.trim() && !Object.keys(changes).length)
    )
      return false;
    const input: FigureRefinement = {
      panel_id: panelId,
      instructions: instructions.trim(),
      parameter_changes: changes,
    };
    // A retried refinement keeps its request ID, so it cannot run twice.
    const key = JSON.stringify(input);
    if (request.current.key !== key)
      request.current = { key, id: createMutationId() };
    setBusy(true);
    setError(null);
    try {
      const ok = await onRefine(request.current.id, input);
      if (ok) onClose();
      return ok;
    } catch (reason) {
      setError(message(reason, "The refinement could not be started."));
      return false;
    } finally {
      setBusy(false);
    }
  }
  return (
    <ReportDialog
      title="Refine plot"
      wide
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <div className="report-editor-context">
        <span>PANEL {label ?? ""}</span>
        <strong>
          {figure?.title ?? figure?.preview.description ?? "Plot"}
        </strong>
        <small>Uses this plot's saved data</small>
      </div>
      <div className="report-figure-editor">
        <div className="report-editor-preview">
          {figure ? (
            <img
              src={resolveArtifactUrl(figure.preview.href)}
              alt={figure.title ?? "Current plot"}
            />
          ) : null}
        </div>
        {figure ? (
          <PlotInspector
            projectId={document.project_id}
            result={figure}
            disabled={busy}
            parameterDraft={parameters}
            onParameterDraftChange={setParameters}
            parameterApplyLabel="Update plot"
            onApply={(changes) => refine(changes)}
          />
        ) : null}
      </div>
      <div className="report-editor-instructions">
        <label htmlFor="composition-refine-prompt">
          What would you like to change?
        </label>
        <textarea
          id="composition-refine-prompt"
          autoFocus
          value={instructions}
          onChange={(event) => setInstructions(event.target.value)}
          maxLength={7000}
          rows={3}
          placeholder="e.g. Show individual points and use a softer palette…"
          disabled={busy}
        />
        <small>
          {Object.keys(parameters).length
            ? `${Object.keys(parameters).length} parameter drafts. `
            : ""}
          The panel keeps its place and width; follow the progress in the
          Assistant tab.
        </small>
        {error ? (
          <p className="report-error" role="alert">
            {error}
          </p>
        ) : null}
        <footer>
          <button type="button" disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="report-primary"
            disabled={
              busy ||
              !valid ||
              (!instructions.trim() && !Object.keys(parameters).length)
            }
            onClick={() => void refine()}
          >
            {busy ? "Starting…" : "Update plot"}
          </button>
        </footer>
      </div>
    </ReportDialog>
  );
}

export function AddImageDialog({
  projectId,
  onAdd,
  onClose,
}: {
  projectId: string;
  onAdd: (image: ReferenceImage) => Promise<boolean>;
  onClose: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState(createMutationId);
  return (
    <ReportDialog
      title="Add an image"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form
        className="report-dialog-form"
        onSubmit={async (event) => {
          event.preventDefault();
          if (!file || busy) return;
          setBusy(true);
          setError(null);
          try {
            const image = await uploadReferenceImage(
              projectId,
              file,
              new AbortController().signal,
              key,
            );
            if (await onAdd(image)) onClose();
          } catch (reason) {
            setError(message(reason, "Image upload failed."));
          } finally {
            setBusy(false);
          }
        }}
      >
        <p>
          Add a micrograph, diagram, or other prepared image. It is placed at
          300 dpi and can be scaled on the page.
        </p>
        <label>
          Image file
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            required
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setKey(createMutationId());
            }}
          />
        </label>
        {error ? (
          <p className="report-error" role="alert">
            {error}
          </p>
        ) : null}
        <footer>
          <button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="submit"
            className="report-primary"
            disabled={busy || !file}
          >
            {busy ? "Adding…" : "Add image"}
          </button>
        </footer>
      </form>
    </ReportDialog>
  );
}

export function FigureHistoryDialog({
  document,
  onRestore,
  onClose,
}: {
  document: FigureDocument;
  onRestore: (content: FigureContent, revision: number) => Promise<boolean>;
  onClose: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const history = useQuery({
    queryKey: [
      "composition-history",
      document.composition_id,
      document.revision,
      offset,
    ],
    queryFn: () =>
      listFigureHistory(document.project_id, document.composition_id, offset),
  });
  return (
    <ReportDialog title="Figure history" onClose={onClose}>
      <div className="report-dialog-form">
        <p>Restore a saved revision. The current figure stays in history.</p>
        {history.isPending ? (
          <p>Loading revisions…</p>
        ) : history.isError ? (
          <p role="alert">{history.error.message}</p>
        ) : (
          <ol className="report-history">
            {history.data.revisions.map((revision) => (
              <li key={revision.revision}>
                <div>
                  <strong>
                    Revision {revision.revision}
                    {revision.revision === document.revision
                      ? " · Current"
                      : ""}
                  </strong>
                  <p>{revision.summary}</p>
                  <small>
                    {new Date(revision.created_at).toLocaleString()}
                  </small>
                </div>
                <button
                  type="button"
                  disabled={busy || revision.revision === document.revision}
                  aria-label={`Restore revision ${revision.revision}`}
                  onClick={async () => {
                    setBusy(true);
                    setError(null);
                    try {
                      const content = await getFigureRevision(
                        document.project_id,
                        document.composition_id,
                        revision.revision,
                      );
                      if (await onRestore(content, revision.revision))
                        onClose();
                    } catch (reason) {
                      setError(
                        message(reason, "The revision could not be restored."),
                      );
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Restore
                </button>
              </li>
            ))}
          </ol>
        )}
        {error ? (
          <p role="alert" className="report-error">
            {error}
          </p>
        ) : null}
        <footer>
          <button
            type="button"
            disabled={!offset}
            onClick={() => setOffset(offset - 30)}
          >
            Previous
          </button>
          <button
            type="button"
            disabled={offset + 30 >= (history.data?.total ?? 0)}
            onClick={() => setOffset(offset + 30)}
          >
            Next
          </button>
        </footer>
      </div>
    </ReportDialog>
  );
}

/** The revision query parameter only distinguishes cached images of different revisions. */
export function figureExportUrl(
  figure: { project_id: string; composition_id: string; revision: number },
  format: string,
) {
  return resolveArtifactUrl(
    `/api/v1/projects/${encodeURIComponent(figure.project_id)}/figure-compositions/${encodeURIComponent(figure.composition_id)}/exports/${format}?revision=${figure.revision}`,
  );
}

export function FigurePreviewDialog({
  document,
  onClose,
}: {
  document: FigureDocument;
  onClose: () => void;
}) {
  return (
    <ReportDialog title="Export preview" onClose={onClose} wide>
      <div className="report-dialog-form composition-preview">
        <p>
          The exported page, rendered by the server exactly as SVG, PDF, PNG,
          and TIFF files will be.
        </p>
        <img
          src={figureExportUrl(document, "svg")}
          alt={`Export preview of ${document.title}`}
        />
      </div>
    </ReportDialog>
  );
}
