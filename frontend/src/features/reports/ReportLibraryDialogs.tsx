import { linkSharedFigure } from "../../api/slides";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createMutationId, resolveArtifactUrl } from "../../api/client";
import { getPlotSource } from "../../api/plotSource";
import {
  getReportRevision,
  listReportFigures,
  listReportHistory,
} from "../../api/reports";
import { uploadReferenceImage } from "../../api/referenceImages";
import type {
  ReportContent,
  ReportDocument,
  ReportFigure,
} from "../../api/schemas/reports";
import { FigureExportMenu } from "../plot-run/FigureExportMenu";
import { ReportDialog, downloadReportFile } from "./ReportDialog";

export function SavedFigureDialog({
  document,
  onClose,
  onInsert,
}: {
  document: ReportDocument;
  onClose: () => void;
  onInsert: (block: ReportFigure) => Promise<boolean>;
}) {
  const [offset, setOffset] = useState(0),
    [busy, setBusy] = useState(false);
  const [linked, setLinked] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const figures = useQuery({
    queryKey: ["report-figure-library", document.project_id, offset, linked],
    queryFn: () => listReportFigures(document.project_id, offset, linked),
  });
  return (
    <ReportDialog title="Add a saved figure" onClose={onClose}>
      <div className="report-dialog-form">
        <p>
          Use a figure already created in Workspace, Canvas, Report, or Slides.
        </p>
        <label>
          <input
            type="checkbox"
            checked={linked}
            onChange={(e) => setLinked(e.target.checked)}
          />{" "}
          Link updates across documents
        </label>
        {figures.isPending ? (
          <p>Loading figures…</p>
        ) : figures.isError ? (
          <p role="alert">
            {figures.error.message}
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
                    const selected = linked
                      ? await linkSharedFigure(
                          document.project_id,
                          figure.plot_id,
                          figure.version_id,
                        )
                      : figure;
                    if (
                      await onInsert({
                        id: createMutationId(),
                        type: "figure",
                        version_id: selected.version_id,
                        follow_plot_id: linked ? selected.plot_id : null,
                        image_id: null,
                        caption: "",
                      })
                    )
                      onClose();
                  } catch (reason) {
                    setError(
                      reason instanceof Error
                        ? reason.message
                        : "The figure could not be added.",
                    );
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <img
                  src={resolveArtifactUrl(figure.preview.href)}
                  alt={figure.title ?? figure.preview.description}
                />
                <strong>{figure.title ?? "Saved figure"}</strong>
              </button>
            ))}
          </div>
        ) : (
          <p>
            No saved figures yet. Ask the assistant to create one from your
            data.
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
          <span>{figures.data?.total ?? 0} figures</span>
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
export function ReportImageDialog({
  projectId,
  onClose,
  onInsert,
}: {
  projectId: string;
  onClose: () => void;
  onInsert: (block: ReportFigure) => Promise<boolean>;
}) {
  const [file, setFile] = useState<File | null>(null),
    [caption, setCaption] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null);
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
              createMutationId(),
            );
            if (
              await onInsert({
                id: createMutationId(),
                type: "figure",
                version_id: null,
                image_id: image.image_id,
                caption,
              })
            )
              onClose();
          } catch (reason) {
            setError(
              reason instanceof Error ? reason.message : "Image upload failed.",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        <p>
          Include a prepared image in this topic. To create an editable R
          version later, use its figure menu with the report's data.
        </p>
        <label>
          Image file
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            required
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <label>
          Caption
          <textarea
            value={caption}
            onChange={(event) => setCaption(event.target.value)}
            maxLength={4000}
            rows={3}
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
export function ReportHistoryDialog({
  document,
  onClose,
  onRestore,
}: {
  document: ReportDocument;
  onClose: () => void;
  onRestore: (content: ReportContent, revision: number) => Promise<boolean>;
}) {
  const [offset, setOffset] = useState(0),
    [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const history = useQuery({
    queryKey: ["report-history", document.report_id, document.revision, offset],
    queryFn: () =>
      listReportHistory(document.project_id, document.report_id, offset),
  });
  return (
    <ReportDialog
      title={
        document.content.kind === "slides"
          ? "Presentation history"
          : "Report history"
      }
      onClose={onClose}
    >
      <div className="report-dialog-form">
        <p>Restore a saved revision. Your current report remains in history.</p>
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
                      const content = await getReportRevision(
                        document.project_id,
                        document.report_id,
                        revision.revision,
                      );
                      if (await onRestore(content, revision.revision))
                        onClose();
                    } catch (reason) {
                      setError(
                        reason instanceof Error
                          ? reason.message
                          : "Revision could not be restored.",
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
export function ReportFigureDetails({
  document,
  block,
  mode,
  onClose,
}: {
  document: ReportDocument;
  block: ReportFigure;
  mode: "code" | "export";
  onClose: () => void;
}) {
  const figure = block.version_id
    ? document.figures[
        document.figure_bindings?.[block.id] ?? block.version_id!
      ]
    : undefined;
  const image = block.image_id ? document.images[block.image_id] : undefined;
  const source = useQuery({
    queryKey: ["plot-source", document.project_id, figure?.version_id],
    queryFn: () =>
      getPlotSource(document.project_id, figure!.plot_id, figure!.version_id),
    enabled: !!figure && mode === "code",
  });
  return (
    <ReportDialog
      title={mode === "code" ? "Figure R code" : "Export figure"}
      onClose={onClose}
    >
      <div className="report-dialog-form">
        {mode === "code" ? (
          source.isPending ? (
            <p>Loading saved R code…</p>
          ) : source.isError ? (
            <p role="alert">
              {source.error.message}
              <button type="button" onClick={() => void source.refetch()}>
                Retry
              </button>
            </p>
          ) : (
            <>
              <p>{source.data.message}</p>
              {source.data.code ? (
                <>
                  <pre
                    className="report-code"
                    tabIndex={0}
                    aria-label="Complete figure R code"
                  >
                    {source.data.code}
                  </pre>
                  <button
                    type="button"
                    className="report-primary"
                    onClick={() =>
                      downloadReportFile(
                        source.data.code!,
                        "report-figure.R",
                        "text/plain",
                      )
                    }
                  >
                    Download R code
                  </button>
                </>
              ) : null}
            </>
          )
        ) : (
          <>
            <img
              className="report-export-preview"
              src={resolveArtifactUrl(
                figure?.preview.href ?? image!.links.content,
              )}
              alt={block.caption || "Selected figure"}
            />
            {figure ? (
              <FigureExportMenu
                projectId={document.project_id}
                result={figure}
                label="Choose export format"
              />
            ) : (
              <a
                href={resolveArtifactUrl(image!.links.content)}
                download="report-image.png"
              >
                Download image
              </a>
            )}
          </>
        )}
      </div>
    </ReportDialog>
  );
}
