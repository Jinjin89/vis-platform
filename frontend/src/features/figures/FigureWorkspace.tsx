import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { createMutationId, type FigureExportFormat } from "../../api/client";
import {
  applyFigureOperations,
  arrangeFigure,
  createFigure,
  downloadFigure,
  exportFigureContent,
  getFigure,
  listFigures,
  renderFigurePanels,
  saveFigure,
} from "../../api/figureCompositions";
import {
  figureContentSchema,
  type FigureContent,
  type FigureDocument,
  type FigureOperation,
  type FigurePanel,
} from "../../api/schemas/figureCompositions";
import type { PlotResult } from "../../api/schemas/plotRun";
import type { ReferenceImage } from "../../api/schemas/referenceImages";
import { downloadReportFile } from "../reports/ReportDialog";
import {
  AddImageDialog,
  AddPlotDialog,
  FigureHistoryDialog,
  FigurePreviewDialog,
  NewFigureDialog,
  figureExportUrl,
} from "./FigureDialogs";
import { FigureInspector, type RenderSizes } from "./FigureInspector";
import { FigureLegendEditor } from "./FigureLegendEditor";
import { FigurePageCanvas, panelTitle } from "./FigurePageCanvas";
import {
  PAGE_PRESETS,
  imageNaturalSize,
  placeNewPanel,
  plotNaturalSize,
  type Size,
} from "./figureGeometry";
import "./figures.css";

// Used only when a legacy plot version recorded no size; the page shows its real SVG size later.
const FALLBACK_PLOT_SIZE: Size = { width: 152.4, height: 101.6 };
const EXPORTS: { format: FigureExportFormat; label: string }[] = [
  { format: "pdf", label: "PDF · vector" },
  { format: "svg", label: "SVG · vector" },
  { format: "png", label: "PNG · 300 dpi" },
  { format: "tiff", label: "TIFF · 300 dpi" },
];

const reasonText = (reason: unknown, fallback: string) =>
  reason instanceof Error ? reason.message : fallback;

export function FigureWorkspace({ projectId }: { projectId: string }) {
  const [params] = useSearchParams();
  const figureId = params.get("id");
  return figureId ? (
    <FigureEditor key={figureId} projectId={projectId} figureId={figureId} />
  ) : (
    <FigureLibrary projectId={projectId} />
  );
}

function FigureLibrary({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [, setParams] = useSearchParams();
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const createKey = useRef(createMutationId());
  const imported = useRef<HTMLInputElement>(null);
  const list = useQuery({
    queryKey: ["figures", projectId, offset],
    queryFn: () => listFigures(projectId, offset),
  });
  async function create(content: FigureContent) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createFigure(projectId, content, createKey.current);
      createKey.current = createMutationId();
      queryClient.setQueryData(
        ["figure", projectId, created.composition_id],
        created,
      );
      void queryClient.invalidateQueries({ queryKey: ["figures", projectId] });
      setCreating(false);
      setParams({ id: created.composition_id });
    } catch (reason) {
      setError(reasonText(reason, "The figure could not be created."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="figure-library">
      <input
        ref={imported}
        type="file"
        accept="application/json,.json"
        hidden
        aria-label="Import figure"
        onChange={async (event) => {
          const file = event.target.files?.[0];
          event.target.value = "";
          if (!file) return;
          try {
            if (file.size > 5_000_000)
              throw new Error("Choose a figure file smaller than 5 MB.");
            createKey.current = createMutationId();
            await create(
              figureContentSchema.parse(JSON.parse(await file.text())),
            );
          } catch (reason) {
            setError(reasonText(reason, "This is not a valid figure file."));
          }
        }}
      />
      <div className="figure-library-heading">
        <div>
          <span className="figure-kicker">Publication figures</span>
          <h1>Compose your figures.</h1>
          <p>
            Arrange saved plots and images into multi-panel figures on an A4 or
            journal-width page, then export them for your manuscript.
          </p>
        </div>
        <div>
          <button type="button" onClick={() => imported.current?.click()}>
            Import figure
          </button>
          <button
            type="button"
            className="figure-primary"
            onClick={() => {
              setError(null);
              setCreating(true);
            }}
          >
            + New figure
          </button>
        </div>
      </div>
      {error && !creating ? (
        <p role="alert" className="report-error">
          {error}
        </p>
      ) : null}
      <div className="figure-grid">
        {list.data?.compositions.map((item) => (
          <button
            type="button"
            key={item.composition_id}
            className="figure-card"
            onClick={() => setParams({ id: item.composition_id })}
          >
            <span className="figure-card-cover">
              <img src={figureExportUrl(item, "svg")} alt="" loading="lazy" />
            </span>
            <strong>{item.title}</strong>
            <small>
              Edited {new Date(item.updated_at).toLocaleDateString()}
            </small>
          </button>
        ))}
        {list.data && !list.data.compositions.length ? (
          <button
            type="button"
            className="figure-card figure-start-card"
            onClick={() => setCreating(true)}
          >
            <span>+</span>
            <strong>Start your first figure</strong>
            <small>Combine saved plots and images on one page.</small>
          </button>
        ) : null}
      </div>
      {list.isPending ? <p>Opening figures…</p> : null}
      {list.isError ? (
        <p role="alert">
          {list.error.message}{" "}
          <button type="button" onClick={() => void list.refetch()}>
            Retry
          </button>
        </p>
      ) : null}
      {list.data && list.data.total > 30 ? (
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
            disabled={offset + 30 >= list.data.total}
            onClick={() => setOffset(offset + 30)}
          >
            Next
          </button>
        </footer>
      ) : null}
      {creating ? (
        <NewFigureDialog
          busy={busy}
          error={error}
          onClose={() => setCreating(false)}
          onCreate={(title, preset) =>
            void create(
              figureContentSchema.parse({
                title,
                page: PAGE_PRESETS.find((item) => item.id === preset)!.page,
              }),
            )
          }
        />
      ) : null}
    </section>
  );
}

function newPanelId(document: FigureDocument) {
  let id: string;
  do id = `panel-${createMutationId().replace(/-/g, "").slice(0, 8)}`;
  while (document.content.panels.some((panel) => panel.id === id));
  return id;
}

function FigureEditor({
  projectId,
  figureId,
}: {
  projectId: string;
  figureId: string;
}) {
  const queryClient = useQueryClient();
  const [, setParams] = useSearchParams();
  const [selected, setSelected] = useState<string[]>([]);
  const [tab, setTab] = useState<"inspect" | "legend">("inspect");
  const [dialog, setDialog] = useState<
    "plot" | "image" | "history" | "preview" | null
  >(null);
  const [menu, setMenu] = useState<{
    x: number;
    y: number;
    panelId: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lock = useRef(false);
  const query = useQuery({
    queryKey: ["figure", projectId, figureId],
    queryFn: () => getFigure(projectId, figureId),
    refetchInterval: (current) =>
      current.state.data?.jobs.some((job) => job.status === "running")
        ? 1000
        : false,
  });
  const document = query.data;
  const [openedAt] = useState(() => Date.now());
  const [dismissed, setDismissed] = useState<string[]>([]);
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", close);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", close);
    };
  }, [menu]);
  useEffect(() => {
    if (document)
      setSelected((current) => current.filter((id) => id in document.panels));
  }, [document]);

  function show(next: FigureDocument) {
    queryClient.setQueryData(["figure", projectId, next.composition_id], next);
    void queryClient.invalidateQueries({ queryKey: ["figures", projectId] });
  }
  async function execute(task: () => Promise<FigureDocument>) {
    if (lock.current) return false;
    lock.current = true;
    setBusy(true);
    setError(null);
    try {
      show(await task());
      return true;
    } catch (reason) {
      setError(reasonText(reason, "The change could not be saved."));
      void query.refetch();
      return false;
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  const apply = (operations: FigureOperation[], summary: string) =>
    document
      ? execute(() =>
          applyFigureOperations(
            projectId,
            figureId,
            document.revision,
            operations,
            createMutationId(),
            summary,
          ),
        )
      : Promise.resolve(false);
  async function addPanel(
    content: FigurePanel["content"],
    natural: Size,
    summary: string,
  ) {
    if (!document) return false;
    const panel: FigurePanel = {
      id: newPanelId(document),
      content,
      ...placeNewPanel(document, natural),
      label: null,
      show_label: true,
      locked: false,
    };
    const added = await apply([{ op: "add_panel", panel }], summary);
    if (added) setSelected([panel.id]);
    return added;
  }
  const addPlot = (figure: PlotResult) =>
    addPanel(
      {
        type: "plot",
        version_id: figure.version_id,
        source_version_id: null,
        ignored_version_id: null,
      },
      plotNaturalSize(figure) ?? FALLBACK_PLOT_SIZE,
      "Added plot panel",
    );
  const addImage = (image: ReferenceImage) =>
    addPanel(
      { type: "image", image_id: image.image_id },
      imageNaturalSize(image),
      "Added image panel",
    );
  const render = (panels: RenderSizes) =>
    execute(() =>
      renderFigurePanels(projectId, figureId, createMutationId(), panels),
    );
  const tidy = (renderPlots: boolean) =>
    document
      ? execute(() =>
          arrangeFigure(
            projectId,
            figureId,
            document.revision,
            createMutationId(),
            {
              render: renderPlots,
              summary: renderPlots
                ? "Tidied rows and rendered plots at their sizes"
                : "Tidied rows",
            },
          ),
        )
      : Promise.resolve(false);
  const remove = (ids: string[]) =>
    void apply(
      ids.map((id) => ({ op: "remove_panel" as const, panel_id: id })),
      ids.length > 1 ? "Removed panels" : "Removed panel",
    ).then((removed) => removed && setSelected([]));
  async function download(format: FigureExportFormat | "json") {
    if (!document || exporting) return;
    setExporting(format);
    setError(null);
    try {
      if (format === "json") {
        const content = await exportFigureContent(projectId, figureId);
        downloadReportFile(
          JSON.stringify(content, null, 2),
          `${document.title}.json`,
        );
      } else {
        const file = await downloadFigure(projectId, figureId, format);
        downloadReportFile(file.blob, file.filename, file.blob.type);
      }
    } catch (reason) {
      setError(reasonText(reason, "The figure could not be exported."));
    } finally {
      setExporting(null);
    }
  }

  if (!document)
    return (
      <section className="report-loading">
        {query.isError ? (
          <>
            <p role="alert">{query.error.message}</p>
            <button type="button" onClick={() => void query.refetch()}>
              Retry
            </button>
          </>
        ) : (
          <p>Opening figure…</p>
        )}
        <button type="button" onClick={() => setParams({})}>
          All figures
        </button>
      </section>
    );
  const menuPanel = document.content.panels.find(
    (panel) => panel.id === menu?.panelId,
  );
  const updates = Object.keys(document.updates).length;
  // Render problems from this session stay visible until dismissed.
  const failures = document.jobs.filter(
    (job) =>
      (job.status === "failed" || job.status === "discarded") &&
      Date.parse(job.created_at) >= openedAt - 1000 &&
      !dismissed.includes(job.job_id),
  );
  return (
    <section className="figure-workspace">
      <header className="figure-toolbar">
        <button
          type="button"
          className="figure-back"
          onClick={() => setParams({})}
        >
          Figures <span>/</span>
        </button>
        <input
          className="figure-title"
          key={document.title}
          defaultValue={document.title}
          aria-label="Figure title"
          maxLength={200}
          onBlur={(event) => {
            const title = event.target.value.trim();
            if (title && title !== document.title)
              void apply([{ op: "set_title", title }], "Renamed figure");
          }}
        />
        <span className="figure-save-state" role="status">
          {busy ? "Saving…" : `Saved · revision ${document.revision}`}
        </span>
        <div className="figure-toolbar-actions">
          <button
            type="button"
            disabled={busy}
            onClick={() => setDialog("plot")}
          >
            + Plot
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => setDialog("image")}
          >
            + Image
          </button>
          <details className="figure-export">
            <summary>Arrange</summary>
            <div role="menu" aria-label="Arrange panels">
              <button
                type="button"
                role="menuitem"
                disabled={busy || !document.content.panels.length}
                onClick={() => void tidy(false)}
              >
                Tidy rows
              </button>
              <button
                type="button"
                role="menuitem"
                disabled={busy || !document.content.panels.length}
                onClick={() => void tidy(true)}
              >
                Tidy rows and render plots at size
              </button>
            </div>
          </details>
          <button type="button" onClick={() => setDialog("history")}>
            History
          </button>
          <button type="button" onClick={() => setDialog("preview")}>
            Preview
          </button>
          <details className="figure-export">
            <summary>{exporting ? "Exporting…" : "Export"}</summary>
            <div role="menu" aria-label="Export figure">
              {EXPORTS.map((item) => (
                <button
                  type="button"
                  role="menuitem"
                  key={item.format}
                  disabled={!!exporting}
                  onClick={() => void download(item.format)}
                >
                  {item.label}
                </button>
              ))}
              <button
                type="button"
                role="menuitem"
                disabled={!!exporting}
                onClick={() => void download("json")}
              >
                Figure JSON
              </button>
            </div>
          </details>
        </div>
      </header>
      {error ? (
        <div className="figure-error" role="alert">
          {error}
          <button type="button" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      ) : null}
      {failures.map((job) => (
        <div className="figure-error" role="alert" key={job.job_id}>
          {job.error ?? "A plot could not be rendered at its panel size."}
          <button
            type="button"
            onClick={() => setDismissed([...dismissed, job.job_id])}
          >
            Dismiss
          </button>
        </div>
      ))}
      {updates ? (
        <p className="figure-notice" role="status">
          {updates === 1
            ? "A newer version of one plot is available."
            : `Newer versions of ${updates} plots are available.`}{" "}
          Select a panel marked “Update available” to review it.
        </p>
      ) : null}
      <div className="figure-editor">
        <div className="figure-canvas-area">
          {document.content.panels.length ? null : (
            <div className="figure-empty">
              <strong>Your page is empty.</strong>
              <p>Add saved plots or images to start composing.</p>
              <div>
                <button
                  type="button"
                  className="figure-primary"
                  onClick={() => setDialog("plot")}
                >
                  Add a saved plot
                </button>
                <button type="button" onClick={() => setDialog("image")}>
                  Add an image
                </button>
              </div>
            </div>
          )}
          <FigurePageCanvas
            document={document}
            selected={selected}
            busy={busy}
            onSelect={(ids) => {
              setSelected(ids);
              if (ids.length) setTab("inspect");
            }}
            onCommit={(changes, summary) =>
              apply([{ op: "set_panel_geometry", panels: changes }], summary)
            }
            onRemove={remove}
            onMenu={(event, panelId) =>
              setMenu({ x: event.clientX, y: event.clientY, panelId })
            }
          />
          <p className="figure-hint">
            Drag to move · drag the corner to scale · Shift-click to select
            several · arrow keys nudge 0.5 mm (Shift: 5 mm) · hold Alt to skip
            snapping
          </p>
        </div>
        <aside className="figure-sidebar" aria-label="Figure details">
          <div className="figure-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "inspect"}
              onClick={() => setTab("inspect")}
            >
              {selected.length ? "Panel" : "Page"}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "legend"}
              onClick={() => setTab("legend")}
            >
              Legend
            </button>
          </div>
          {tab === "inspect" ? (
            <FigureInspector
              document={document}
              selected={selected}
              busy={busy}
              onApply={apply}
              onRender={render}
              onSelect={setSelected}
            />
          ) : (
            <FigureLegendEditor
              document={document}
              busy={busy}
              onApply={apply}
            />
          )}
        </aside>
      </div>
      {menu && menuPanel ? (
        <div
          className="figure-menu"
          role="menu"
          aria-label={`Actions for ${panelTitle(document, menuPanel)}`}
          style={{ left: menu.x, top: menu.y }}
          onPointerDown={(event) => event.stopPropagation()}
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenu(null);
              void apply(
                [{ op: "move_panel", panel_id: menuPanel.id, before_id: null }],
                "Brought panel to front",
              );
            }}
          >
            Bring to front
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenu(null);
              void apply(
                [
                  {
                    op: "replace_panel",
                    panel: { ...menuPanel, locked: !menuPanel.locked },
                  },
                ],
                menuPanel.locked ? "Unlocked panel" : "Locked panel",
              );
            }}
          >
            {menuPanel.locked ? "Unlock position" : "Lock position"}
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenu(null);
              remove(selected.length ? selected : [menuPanel.id]);
            }}
          >
            Remove
          </button>
        </div>
      ) : null}
      {dialog === "plot" ? (
        <AddPlotDialog
          projectId={projectId}
          onAdd={addPlot}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog === "image" ? (
        <AddImageDialog
          projectId={projectId}
          onAdd={addImage}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog === "history" ? (
        <FigureHistoryDialog
          document={document}
          onClose={() => setDialog(null)}
          onRestore={(content, revision) =>
            execute(() =>
              saveFigure(
                projectId,
                figureId,
                document.revision,
                content,
                `Restored revision ${revision}`,
              ),
            )
          }
        />
      ) : null}
      {dialog === "preview" ? (
        <FigurePreviewDialog
          document={document}
          onClose={() => setDialog(null)}
        />
      ) : null}
    </section>
  );
}
