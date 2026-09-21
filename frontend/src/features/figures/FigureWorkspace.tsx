import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useSearchParams } from "react-router";
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
  sendFigureMessage,
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
import { reportEditActive } from "../../api/schemas/reports";
import { DatasetSelector } from "../datasets/DatasetSelector";
import { downloadReportFile } from "../reports/ReportDialog";
import {
  AddImageDialog,
  AddPlotDialog,
  FigureHistoryDialog,
  FigurePreviewDialog,
  NewFigureDialog,
  figureExportUrl,
} from "./FigureDialogs";
import { FigureAssistantPanel } from "./FigureAssistantPanel";
import { FigureInspector, type RenderSizes } from "./FigureInspector";
import { FigureLegendEditor } from "./FigureLegendEditor";
import { FigurePageCanvas, panelTitle } from "./FigurePageCanvas";
import {
  PAGE_PRESETS,
  imageNaturalSize,
  newPanelId,
  placeNewPanel,
  placeNewSlot,
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
  async function create(content: FigureContent, description = "") {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createFigure(projectId, content, createKey.current);
      createKey.current = createMutationId();
      let opened = created;
      let unsent: string | null = null;
      // With a description, the assistant starts building as soon as the figure opens.
      if (description)
        try {
          opened = await sendFigureMessage(projectId, created.composition_id, {
            request_id: createMutationId(),
            message: description,
          });
        } catch {
          unsent = description;
        }
      queryClient.setQueryData(
        ["figure", projectId, created.composition_id],
        opened,
      );
      void queryClient.invalidateQueries({ queryKey: ["figures", projectId] });
      setCreating(false);
      setParams(
        { id: created.composition_id },
        unsent ? { state: { unsent } } : undefined,
      );
    } catch (reason) {
      setError(reasonText(reason, "The figure could not be created."));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="composition-library">
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
      <div className="composition-library-heading">
        <div>
          <span className="composition-kicker">Publication figures</span>
          <h1>Build your figures.</h1>
          <p>
            Describe a figure and let the assistant build it from your data
            panel by panel, or arrange saved plots and images yourself, on an A4
            or journal-width page. Export it for your manuscript.
          </p>
        </div>
        <div>
          <button type="button" onClick={() => imported.current?.click()}>
            Import figure
          </button>
          <button
            type="button"
            className="composition-primary"
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
      <div className="composition-grid">
        {list.data?.compositions.map((item) => (
          <button
            type="button"
            key={item.composition_id}
            className="composition-card"
            onClick={() => setParams({ id: item.composition_id })}
          >
            <span className="composition-card-cover">
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
            className="composition-card composition-start-card"
            onClick={() => setCreating(true)}
          >
            <span>+</span>
            <strong>Start your first figure</strong>
            <small>Build it from your data, or combine saved plots.</small>
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
          projectId={projectId}
          onCreate={({ title, preset, datasetIds, description }) =>
            void create(
              figureContentSchema.parse({
                title,
                page: PAGE_PRESETS.find((item) => item.id === preset)!.page,
                datasets: datasetIds.map((dataset_id) => ({ dataset_id })),
              }),
              description,
            )
          }
        />
      ) : null}
    </section>
  );
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
  const location = useLocation();
  // A description that could not be sent when the figure was created.
  const [unsent] = useState(
    () => (location.state as { unsent?: string } | null)?.unsent ?? "",
  );
  const composer = useRef<HTMLTextAreaElement>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [tab, setTab] = useState<"assistant" | "inspect" | "legend">(
    "assistant",
  );
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
  const [error, setError] = useState<string | null>(() =>
    unsent
      ? "The assistant could not start. Your description is in the message box; send it again."
      : null,
  );
  const lock = useRef(false);
  const query = useQuery({
    queryKey: ["figure", projectId, figureId],
    queryFn: () => getFigure(projectId, figureId),
    refetchInterval: (current) =>
      current.state.data?.jobs.some((job) => job.status === "running") ||
      current.state.data?.messages.some((message) =>
        ["running", "awaiting_input", "awaiting_approval"].includes(
          message.status,
        ),
      )
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
  function addSlot() {
    if (!document) return;
    const place = placeNewSlot(document);
    const panel: FigurePanel = {
      id: newPanelId(document),
      content: {
        type: "slot",
        prompt: "",
        width_mm: place.width,
        height_mm: place.height,
      },
      x_mm: place.x_mm,
      y_mm: place.y_mm,
      scale: 1,
      label: null,
      show_label: true,
      locked: false,
    };
    void apply([{ op: "add_panel", panel }], "Added a slot").then((added) => {
      if (!added) return;
      setSelected([panel.id]);
      setTab("inspect");
    });
  }
  function reshape(panelId: string, size: Size) {
    const panel = document?.content.panels.find((item) => item.id === panelId);
    if (!panel || panel.content.type !== "slot") return Promise.resolve(false);
    return apply(
      [
        {
          op: "replace_panel",
          panel: {
            ...panel,
            content: {
              ...panel.content,
              width_mm: size.width,
              height_mm: size.height,
            },
            scale: 1,
          },
        },
      ],
      "Resized slot",
    );
  }
  const fill = (panelIds: string[]) =>
    document
      ? execute(() =>
          sendFigureMessage(projectId, figureId, {
            request_id: createMutationId(),
            message: `Create the plot for ${panelIds
              .map((id) => `panel ${document.panels[id]?.label ?? id}`)
              .join(", ")}.`,
            fill: panelIds,
          }),
        )
      : Promise.resolve(false);
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
    <section className="composition-workspace">
      <header className="composition-toolbar">
        <button
          type="button"
          className="composition-back"
          onClick={() => setParams({})}
        >
          Figures <span>/</span>
        </button>
        <input
          className="composition-title"
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
        <span className="composition-save-state" role="status">
          {busy ? "Saving…" : `Saved · revision ${document.revision}`}
        </span>
        <div className="composition-toolbar-actions">
          <DatasetSelector
            projectId={projectId}
            ensureProject={async () => projectId}
            selectedIds={document.content.datasets.map(
              (dataset) => dataset.dataset_id,
            )}
            onSelect={(ids) =>
              void apply(
                [
                  {
                    op: "set_datasets",
                    datasets: ids.map((dataset_id) => ({ dataset_id })),
                  },
                ],
                "Updated figure data",
              )
            }
            resultIds={[]}
            onUseResult={() => undefined}
            datasetsOnly
            disabled={busy}
          />
          <button type="button" disabled={busy} onClick={addSlot}>
            + Slot
          </button>
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
          <details className="composition-export">
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
          <details className="composition-export">
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
        <div className="composition-error" role="alert">
          {error}
          <button type="button" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      ) : null}
      {failures.map((job) => (
        <div className="composition-error" role="alert" key={job.job_id}>
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
        <p className="composition-notice" role="status">
          {updates === 1
            ? "A newer version of one plot is available."
            : `Newer versions of ${updates} plots are available.`}{" "}
          Select a panel marked “Update available” to review it.
        </p>
      ) : null}
      <div className="composition-editor">
        <div className="composition-canvas-area">
          {document.content.panels.length ? null : (
            <div className="composition-empty">
              <strong>Your page is empty.</strong>
              <p>
                Describe the figure to the assistant: it plans the panels, lays
                out the page, and creates each plot from your data. Or build it
                yourself from slots, saved plots, and images.
              </p>
              <div>
                <button
                  type="button"
                  className="composition-primary"
                  onClick={() => {
                    setTab("assistant");
                    window.setTimeout(() => composer.current?.focus());
                  }}
                >
                  Describe the figure
                </button>
                <button type="button" disabled={busy} onClick={addSlot}>
                  Add a slot
                </button>
                <button type="button" onClick={() => setDialog("plot")}>
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
              // The assistant keeps its conversation open and uses the selection as a hint.
              if (ids.length && tab === "legend") setTab("inspect");
            }}
            onCommit={(changes, summary) =>
              apply([{ op: "set_panel_geometry", panels: changes }], summary)
            }
            onReshape={reshape}
            onRemove={remove}
            onMenu={(event, panelId) =>
              setMenu({ x: event.clientX, y: event.clientY, panelId })
            }
            onOpen={(panelId) => {
              setSelected([panelId]);
              setTab("inspect");
            }}
          />
          <p className="composition-hint">
            Double-click a panel for its properties · drag to move · drag the
            corner to scale (slots: to reshape) · Shift-click to select several
            · arrow keys nudge 0.5 mm (Shift: 5 mm) · hold Alt to skip snapping
          </p>
        </div>
        <aside className="composition-sidebar" aria-label="Figure details">
          <div className="composition-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "assistant"}
              onClick={() => setTab("assistant")}
            >
              Assistant
            </button>
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
          {tab === "assistant" ? (
            <FigureAssistantPanel
              document={document}
              selected={selected}
              composer={composer}
              initialDraft={unsent}
              onSend={(input) =>
                execute(() => sendFigureMessage(projectId, figureId, input))
              }
              onShow={show}
              onClearSelection={() => setSelected([])}
              refresh={() => query.refetch()}
            />
          ) : tab === "inspect" ? (
            <FigureInspector
              document={document}
              selected={selected}
              busy={busy}
              working={document.messages.some(reportEditActive)}
              onApply={apply}
              onRender={render}
              onFill={fill}
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
          className="composition-menu"
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
