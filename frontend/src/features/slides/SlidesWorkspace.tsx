import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { createMutationId } from "../../api/client";
import {
  createSlideDeck,
  exportSlideDeck,
  linkSharedFigure,
  listSlideDecks,
  slideDeckSchema,
  type SlideDeck,
} from "../../api/slides";
import {
  applyReportOperations,
  generateReportContent,
  getReport,
  saveReport,
  sendReportMessage,
} from "../../api/reports";
import {
  figureForBlock,
  reportEditActive,
  type ReportDocument,
  type ReportBlock,
  type ReportFigure,
  type ReportOperation,
  type SlideFrame,
  type SlideSettings,
} from "../../api/schemas/reports";
import { DatasetSelector } from "../datasets/DatasetSelector";
import {
  ReportAssistantPanel,
  type ReportComposeTarget,
} from "../reports/ReportAssistantPanel";
import {
  ReportEditorDialog,
  type ReportEditorTarget,
} from "../reports/ReportEditorDialog";
import { ReportDialog, downloadReportFile } from "../reports/ReportDialog";
import {
  ReportFigureDetails,
  ReportHistoryDialog,
  ReportImageDialog,
  SavedFigureDialog,
} from "../reports/ReportLibraryDialogs";
import { ReportFigureMenu } from "../reports/ReportFigureMenu";
import { SlideCanvas } from "./SlideCanvas";
import "./slides.css";

const layouts: { value: SlideSettings["layout"]; label: string }[] = [
  { value: "title", label: "Title" },
  { value: "figure-summary", label: "Figure + summary" },
  { value: "two-column", label: "Two columns" },
  { value: "statement", label: "Statement" },
  { value: "table", label: "Table" },
];
const settings = (
  layout: SlideSettings["layout"] = "figure-summary",
): SlideSettings => ({ layout, notes: "", frames: {} });

export function SlidesWorkspace({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [params, setParams] = useSearchParams();
  const deckId = params.get("id");
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("Untitled presentation");
  const [selectedSlide, setSelectedSlide] = useState<string | null>(null),
    [selectedBlock, setSelectedBlock] = useState<string | null>(null);
  const [scoped, setScoped] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(
    () => window.innerWidth >= 960,
  );
  const [target, setTarget] = useState<ReportComposeTarget | null>(null);
  const [editor, setEditor] = useState<ReportEditorTarget | null>(null);
  const [library, setLibrary] = useState(false),
    [image, setImage] = useState(false),
    [history, setHistory] = useState(false),
    [table, setTable] = useState(false);
  const [details, setDetails] = useState<{
    block: ReportFigure;
    mode: "code" | "export";
  } | null>(null);
  const [menu, setMenu] = useState<{
    x: number;
    y: number;
    block: ReportFigure;
    trigger: HTMLElement;
  } | null>(null);
  const [error, setError] = useState<string | null>(null),
    [busy, setBusy] = useState(false);
  const [presenting, setPresenting] = useState(false);
  const imported = useRef<HTMLInputElement>(null);
  const mutationLock = useRef(false),
    createKey = useRef(createMutationId());
  const list = useQuery({
    queryKey: ["slides", projectId, offset],
    queryFn: () => listSlideDecks(projectId, offset),
  });
  const query = useQuery({
    queryKey: ["report", projectId, deckId],
    queryFn: () => getReport(projectId, deckId!),
    enabled: !!deckId,
    refetchInterval: (q) =>
      q.state.error
        ? false
        : q.state.data?.edits.some(reportEditActive) ||
            q.state.data?.messages.some((m) =>
              ["running", "awaiting_input", "awaiting_approval"].includes(
                m.status,
              ),
            )
          ? 1000
          : 2500,
  });
  const doc = query.data;
  const slides = doc?.content.sections ?? [];
  const slide = slides.find((s) => s.id === selectedSlide) ?? slides[0];
  const index = slide ? slides.indexOf(slide) : 0;
  const block = slide?.blocks.find((b) => b.id === selectedBlock);
  const refresh = () => query.refetch();
  function show(next: ReportDocument) {
    queryClient.setQueryData(["report", projectId, next.report_id], next);
    void queryClient.invalidateQueries({ queryKey: ["slides", projectId] });
  }
  async function execute(task: () => Promise<ReportDocument>) {
    if (mutationLock.current) return false;
    mutationLock.current = true;
    setBusy(true);
    setError(null);
    try {
      show(await task());
      return true;
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "The change could not be saved.",
      );
      return false;
    } finally {
      mutationLock.current = false;
      setBusy(false);
    }
  }
  const apply = (operations: ReportOperation[], summary: string) =>
    doc
      ? execute(() =>
          applyReportOperations(
            projectId,
            doc.report_id,
            doc.revision,
            operations,
            createMutationId(),
            summary,
          ),
        )
      : Promise.resolve(false);
  function choose(id: string) {
    setSelectedSlide(id);
    setSelectedBlock(null);
    setScoped(true);
  }
  function compose(prompt: string) {
    setTarget({ prompt, key: Date.now() });
    setAssistantOpen(true);
  }
  async function create(content?: SlideDeck) {
    if (mutationLock.current) return;
    mutationLock.current = true;
    setBusy(true);
    setError(null);
    try {
      const deck =
        content ??
        slideDeckSchema.parse({
          title: title.trim() || "Untitled presentation",
          slides: [
            {
              id: createMutationId(),
              title: title.trim() || "Untitled presentation",
              settings: settings("title"),
              elements: [],
            },
            {
              id: createMutationId(),
              title: "Key findings",
              settings: settings(),
              elements: [],
            },
            {
              id: createMutationId(),
              title: "Takeaways",
              settings: settings("statement"),
              elements: [],
            },
          ],
        });
      const next = await createSlideDeck(projectId, deck, createKey.current);
      show(next);
      setParams({ id: next.report_id });
      setCreating(false);
      setSelectedSlide(null);
      setScoped(false);
      createKey.current = createMutationId();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "The presentation could not be created.",
      );
    } finally {
      mutationLock.current = false;
      setBusy(false);
    }
  }
  async function addSlide() {
    const id = createMutationId();
    if (
      await apply(
        [
          {
            op: "insert_section",
            section: {
              id,
              title: "New slide",
              level: 1,
              blocks: [],
              slide: settings(),
            },
            ...(slide ? { after_id: slide.id } : {}),
          },
        ],
        "Added slide",
      )
    )
      choose(id);
  }
  async function insert(newBlock: ReportBlock) {
    return slide
      ? apply(
          [{ op: "insert_block", section_id: slide.id, block: newBlock }],
          "Added slide content",
        )
      : false;
  }
  async function updateSettings(next: SlideSettings) {
    return slide
      ? apply(
          [{ op: "set_slide_settings", section_id: slide.id, settings: next }],
          "Updated slide layout",
        )
      : false;
  }
  function frame(blockId: string, value: SlideFrame) {
    if (slide)
      void updateSettings({
        ...(slide.slide ?? settings()),
        frames: { ...slide.slide?.frames, [blockId]: value },
      });
  }
  useEffect(() => {
    if (!presenting) return;
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPresenting(false);
      if (["ArrowRight", "PageDown", " "].includes(e.key)) {
        e.preventDefault();
        if (slides[index + 1]) choose(slides[index + 1]!.id);
      }
      if (["ArrowLeft", "PageUp"].includes(e.key)) {
        e.preventDefault();
        if (slides[index - 1]) choose(slides[index - 1]!.id);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [presenting, index, slides]);
  async function toggleLink() {
    if (!doc || block?.type !== "figure" || !block.version_id) return;
    const current = figureForBlock(doc, block)!;
    if (block.follow_plot_id) {
      await apply(
        [
          {
            op: "replace_block",
            section_id: slide!.id,
            block: {
              ...block,
              version_id: current.version_id,
              follow_plot_id: null,
            },
          },
        ],
        "Pinned figure version",
      );
      return;
    }
    try {
      const linked = await linkSharedFigure(
        projectId,
        current.plot_id,
        current.version_id,
      );
      await apply(
        [
          {
            op: "replace_block",
            section_id: slide!.id,
            block: {
              ...block,
              version_id: linked.version_id,
              follow_plot_id: linked.plot_id,
            },
          },
        ],
        "Linked shared figure",
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not link the figure.");
    }
  }
  const importControl = (
    <input
      ref={imported}
      type="file"
      accept="application/json,.json"
      hidden
      aria-label="Import slide deck"
      onChange={async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        try {
          if (file.size > 5_000_000)
            throw new Error("Choose a slide deck smaller than 5 MB.");
          const content = slideDeckSchema.parse(JSON.parse(await file.text()));
          createKey.current = createMutationId();
          await create(content);
        } catch (reason) {
          setError(
            reason instanceof Error ? reason.message : "Invalid slide deck.",
          );
        }
        e.target.value = "";
      }}
    />
  );
  if (!deckId)
    return (
      <section className="slides-library">
        {importControl}
        <div className="slides-library-heading">
          <div>
            <span className="slides-kicker">YOUR RESEARCH, PRESENTED</span>
            <h1>A story worth sharing.</h1>
            <p>
              Bring your figures and findings together in a clear, considered
              presentation.
            </p>
          </div>
          <div>
            <button onClick={() => imported.current?.click()}>
              Import deck
            </button>
            <button
              className="slides-primary"
              onClick={() => {
                setCreating(true);
                createKey.current = createMutationId();
              }}
            >
              + New presentation
            </button>
          </div>
        </div>
        {error ? (
          <p role="alert" className="report-error">
            {error}
          </p>
        ) : null}
        <div className="slides-deck-grid">
          {list.data?.reports.map((item) => (
            <button
              key={item.report_id}
              className="slides-deck-card"
              onClick={() => setParams({ id: item.report_id })}
            >
              <div className="slides-deck-cover">
                <span>RESEARCH PRESENTATION</span>
                <strong>{item.title}</strong>
                <i />
              </div>
              <b>{item.title}</b>
              <small>
                Edited {new Date(item.updated_at).toLocaleDateString()}
              </small>
            </button>
          ))}
          {!list.isPending && !list.data?.reports.length ? (
            <button
              className="slides-deck-card slides-start-card"
              onClick={() => setCreating(true)}
            >
              <span>+</span>
              <strong>Your next presentation starts here</strong>
              <small>Use saved figures or begin with your data.</small>
            </button>
          ) : null}
        </div>
        {list.isPending ? (
          <p>Opening presentations…</p>
        ) : list.isError ? (
          <p role="alert">
            {list.error.message}
            <button onClick={() => void list.refetch()}>Retry</button>
          </p>
        ) : null}
        {list.data && list.data.total > 30 ? (
          <footer>
            <button disabled={!offset} onClick={() => setOffset(offset - 30)}>
              Previous
            </button>
            <button
              disabled={offset + 30 >= list.data.total}
              onClick={() => setOffset(offset + 30)}
            >
              Next
            </button>
          </footer>
        ) : null}
        {creating ? (
          <ReportDialog
            title="New presentation"
            onClose={() => setCreating(false)}
          >
            <form
              className="report-dialog-form"
              onSubmit={(e) => {
                e.preventDefault();
                void create();
              }}
            >
              <label>
                Presentation title
                <input
                  autoFocus
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  maxLength={200}
                  required
                />
              </label>
              <p>
                Start with a title, key findings, and takeaways. Add data and
                figures as you go.
              </p>
              {error ? <p role="alert">{error}</p> : null}
              <footer>
                <button type="button" onClick={() => setCreating(false)}>
                  Cancel
                </button>
                <button
                  className="slides-primary"
                  disabled={busy || !title.trim()}
                >
                  Create presentation
                </button>
              </footer>
            </form>
          </ReportDialog>
        ) : null}
      </section>
    );
  if (!doc)
    return (
      <section className="report-loading">
        {query.isError ? (
          <>
            <p role="alert">{query.error.message}</p>
            <button onClick={() => void refresh()}>Retry</button>
          </>
        ) : (
          <p>Opening presentation…</p>
        )}
        <button onClick={() => setParams({})}>All presentations</button>
      </section>
    );
  if (doc.content.kind !== "slides")
    return (
      <p>
        This document is a report.{" "}
        <a href={`/report?id=${doc.report_id}`}>Open report</a>
      </p>
    );
  return (
    <section className="slides-workspace" data-assistant={assistantOpen}>
      {importControl}
      <header className="slides-toolbar">
        <button className="slides-back" onClick={() => setParams({})}>
          Presentations <span>/</span>
        </button>
        <input
          className="slides-deck-title"
          key={doc.title}
          defaultValue={doc.title}
          aria-label="Presentation title"
          maxLength={200}
          onBlur={(e) => {
            if (e.target.value.trim() && e.target.value.trim() !== doc.title)
              void apply(
                [{ op: "rename_report", title: e.target.value.trim() }],
                "Renamed presentation",
              );
          }}
        />
        <div className="slides-toolbar-actions">
          <span className="slides-save-state">
            {busy ? "Saving…" : "Saved"}
          </span>
          <DatasetSelector
            projectId={projectId}
            selectedIds={doc.content.datasets.map((d) => d.dataset_id)}
            ensureProject={async () => projectId}
            resultIds={[]}
            onUseResult={() => undefined}
            disabled={busy}
            datasetsOnly
            onSelect={(ids) => {
              void apply(
                [
                  {
                    op: "set_datasets",
                    datasets: ids.map((dataset_id) => ({ dataset_id })),
                  },
                ],
                "Updated presentation data",
              );
            }}
          />
          <button
            aria-label="Toggle slides assistant"
            onClick={() => setAssistantOpen(!assistantOpen)}
          >
            Assistant
          </button>
          <button onClick={() => setHistory(true)}>History</button>
          <details className="slides-export">
            <summary>Export</summary>
            <div>
              <button
                onClick={() => {
                  void exportSlideDeck(projectId, doc.report_id)
                    .then((deck) =>
                      downloadReportFile(
                        JSON.stringify(deck, null, 2),
                        `${doc.title}.json`,
                        "application/json",
                      ),
                    )
                    .catch((e) => setError(e.message));
                }}
              >
                Slide deck JSON
              </button>
              <button onClick={() => window.print()}>Print / Save PDF</button>
            </div>
          </details>
          <button
            className="slides-primary"
            disabled={!slide}
            onClick={() => setPresenting(true)}
          >
            ▷ Present
          </button>
        </div>
      </header>
      {error ? (
        <div className="slides-error" role="alert">
          {error}
          <button
            onClick={() => {
              setError(null);
              void refresh();
            }}
          >
            Refresh
          </button>
        </div>
      ) : null}
      <div className="slides-editor">
        <nav className="slides-filmstrip" aria-label="Slides">
          <header>
            <span>SLIDES</span>
            <button
              aria-label="Add slide"
              disabled={busy}
              onClick={() => void addSlide()}
            >
              +
            </button>
          </header>
          {slides.map((s, i) => (
            <div
              className={`slides-thumbnail-row ${s.id === slide?.id ? "active" : ""}`}
              key={s.id}
            >
              <span>{String(i + 1).padStart(2, "0")}</span>
              <button
                aria-label={`Slide ${i + 1}: ${s.title}`}
                aria-current={s.id === slide?.id ? "true" : undefined}
                onClick={() => choose(s.id)}
              >
                <SlideCanvas document={doc} section={s} index={i} thumbnail />
              </button>
            </div>
          ))}
          <button
            className="slides-add-button"
            disabled={busy}
            onClick={() => void addSlide()}
          >
            + Add slide
          </button>
        </nav>
        <div className="slides-main">
          {slide ? (
            <>
              <div className="slides-formatbar">
                <label>
                  Layout
                  <select
                    aria-label="Slide layout"
                    value={slide.slide?.layout ?? "figure-summary"}
                    disabled={busy}
                    onChange={(e) =>
                      void updateSettings({
                        ...(slide.slide ?? settings()),
                        layout: e.target.value as SlideSettings["layout"],
                        frames: {},
                      })
                    }
                  >
                    {layouts.map((l) => (
                      <option key={l.value} value={l.value}>
                        {l.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Theme
                  <select
                    aria-label="Presentation theme"
                    value={doc.content.presentation?.theme ?? "paper"}
                    disabled={busy}
                    onChange={(e) =>
                      void apply(
                        [
                          {
                            op: "set_presentation_settings",
                            settings: {
                              theme: e.target.value as "paper" | "midnight",
                              aspect_ratio: "16:9",
                            },
                          },
                        ],
                        "Changed presentation theme",
                      )
                    }
                  >
                    <option value="paper">Paper</option>
                    <option value="midnight">Midnight</option>
                  </select>
                </label>
                <div className="slides-format-spacer" />
                <button
                  disabled={busy || index === 0}
                  aria-label="Move slide earlier"
                  onClick={() =>
                    void apply(
                      [
                        {
                          op: "move_section",
                          section_id: slide.id,
                          before_id: slides[index - 1]!.id,
                        },
                      ],
                      "Moved slide",
                    )
                  }
                >
                  ↑
                </button>
                <button
                  disabled={busy || index === slides.length - 1}
                  aria-label="Move slide later"
                  onClick={() =>
                    void apply(
                      [
                        {
                          op: "move_section",
                          section_id: slide.id,
                          after_id: slides[index + 1]!.id,
                        },
                      ],
                      "Moved slide",
                    )
                  }
                >
                  ↓
                </button>
                <button
                  disabled={busy}
                  onClick={() =>
                    void apply(
                      [{ op: "remove_section", section_id: slide.id }],
                      "Removed slide",
                    )
                  }
                >
                  Delete slide
                </button>
              </div>
              <div className="slides-stage-scroll">
                <div className="slides-stage-meta">
                  <input
                    key={`${slide.id}-${slide.title}`}
                    aria-label="Slide title"
                    defaultValue={slide.title}
                    maxLength={200}
                    onBlur={(e) => {
                      if (
                        e.target.value.trim() &&
                        e.target.value.trim() !== slide.title
                      )
                        void apply(
                          [
                            {
                              op: "rename_section",
                              section_id: slide.id,
                              title: e.target.value.trim(),
                            },
                          ],
                          "Renamed slide",
                        );
                    }}
                  />
                  <span>
                    {index + 1} / {slides.length}
                  </span>
                </div>
                <div
                  className="slides-stage"
                  role="region"
                  aria-label="Slide editor"
                >
                  <SlideCanvas
                    key={slide.id}
                    document={doc}
                    section={slide}
                    index={index}
                    selectedId={selectedBlock}
                    onSelect={(b) => {
                      setSelectedBlock(b.id);
                      setScoped(true);
                    }}
                    onEdit={(b) =>
                      b.type !== "table" &&
                      setEditor({
                        kind: b.type,
                        topicId: slide.id,
                        blockId: b.id,
                      })
                    }
                    onMenu={(e, b) =>
                      b.type === "figure" &&
                      setMenu({
                        x: e.clientX,
                        y: e.clientY,
                        block: b,
                        trigger: e.currentTarget,
                      })
                    }
                    onFrame={frame}
                  />
                </div>
                <div className="slides-insertbar">
                  <button
                    disabled={busy}
                    onClick={() =>
                      setEditor({ kind: "text", topicId: slide.id })
                    }
                  >
                    T <span>Text</span>
                  </button>
                  <button
                    disabled={busy}
                    onClick={() =>
                      compose(
                        "Create a figure for this slide using the available data.",
                      )
                    }
                  >
                    ◩ <span>New figure</span>
                  </button>
                  <button disabled={busy} onClick={() => setLibrary(true)}>
                    ▧ <span>Saved figure</span>
                  </button>
                  <button disabled={busy} onClick={() => setImage(true)}>
                    ▣ <span>Image</span>
                  </button>
                  <button disabled={busy} onClick={() => setTable(true)}>
                    ▦ <span>Table</span>
                  </button>
                </div>
                {block ? (
                  <div className="slides-selection-tools">
                    <span>
                      {block.type === "figure"
                        ? block.follow_plot_id
                          ? "Linked figure · updates across documents"
                          : "Pinned figure version"
                        : "Selected content"}
                    </span>
                    {block.type !== "table" ? (
                      <button
                        onClick={() =>
                          setEditor({
                            kind: block.type,
                            topicId: slide.id,
                            blockId: block.id,
                          })
                        }
                      >
                        {block.type === "figure"
                          ? "Refine / parameters"
                          : "Edit text"}
                      </button>
                    ) : null}
                    {block.type === "figure" && block.version_id ? (
                      <>
                        <button
                          disabled={busy}
                          onClick={() => void toggleLink()}
                        >
                          {block.follow_plot_id
                            ? "Pin this version"
                            : "Link updates"}
                        </button>
                        <button
                          onClick={() => setDetails({ block, mode: "code" })}
                        >
                          Code / export
                        </button>
                      </>
                    ) : null}
                    <button
                      disabled={busy}
                      onClick={() =>
                        void apply(
                          [{ op: "remove_block", block_id: block.id }],
                          "Removed content",
                        )
                      }
                    >
                      Remove
                    </button>
                  </div>
                ) : (
                  <p className="slides-edit-hint">
                    Double-click to edit · Right-click a figure to refine · Alt
                    + arrows to move selected content
                  </p>
                )}
                {doc.stale_text_ids.some((id) =>
                  slide.blocks.some((b) => b.id === id),
                ) ? (
                  <p className="slides-evidence-notice">
                    The evidence has changed. Review this slide’s summary.
                  </p>
                ) : null}
                {doc.edits
                  .filter(
                    (e) => e.section_id === slide.id && reportEditActive(e),
                  )
                  .map((e) => (
                    <p
                      className="slides-evidence-notice"
                      role="status"
                      key={e.edit_id}
                    >
                      <span className="report-spinner" />{" "}
                      {e.kind === "figure"
                        ? "Creating your figure…"
                        : "Writing slide content…"}
                    </p>
                  ))}
                <label className="slides-notes">
                  SPEAKER NOTES
                  <textarea
                    key={`${slide.id}-${slide.slide?.notes ?? ""}`}
                    aria-label="Speaker notes"
                    placeholder="Add the context you want to share when presenting…"
                    defaultValue={slide.slide?.notes ?? ""}
                    maxLength={12000}
                    onBlur={(e) => {
                      if (e.target.value !== (slide.slide?.notes ?? ""))
                        void updateSettings({
                          ...(slide.slide ?? settings()),
                          notes: e.target.value,
                        });
                    }}
                  />
                </label>
              </div>
            </>
          ) : (
            <div className="slides-stage-empty">
              <h2>Your presentation is ready to begin.</h2>
              <button
                className="slides-primary"
                onClick={() => void addSlide()}
              >
                Add the first slide
              </button>
            </div>
          )}
        </div>
        <ReportAssistantPanel
          document={doc}
          section={scoped ? slide : undefined}
          block={scoped ? block : undefined}
          open={assistantOpen}
          composeTarget={target}
          onClose={() => setAssistantOpen(false)}
          onClearSelection={() => {
            setScoped(false);
            setSelectedBlock(null);
          }}
          onSend={(input) =>
            execute(() => sendReportMessage(projectId, doc.report_id, input))
          }
          onShowReport={show}
          onEditDirectly={setEditor}
          refresh={refresh}
        />
      </div>
      {editor ? (
        <ReportEditorDialog
          key={`${editor.topicId}-${editor.blockId ?? "new"}-${editor.kind}`}
          document={doc}
          target={editor}
          onClose={() => setEditor(null)}
          onGenerate={(input) =>
            execute(() =>
              generateReportContent(projectId, doc.report_id, input),
            )
          }
          onSaveText={(s, b) =>
            apply(
              [
                {
                  op: s.blocks.some((item) => item.id === b.id)
                    ? "replace_block"
                    : "insert_block",
                  section_id: s.id,
                  block: b,
                },
              ],
              "Edited slide text",
            )
          }
        />
      ) : null}
      {library ? (
        <SavedFigureDialog
          document={doc}
          onClose={() => setLibrary(false)}
          onInsert={insert}
        />
      ) : null}
      {image ? (
        <ReportImageDialog
          projectId={projectId}
          onClose={() => setImage(false)}
          onInsert={insert}
        />
      ) : null}
      {details ? (
        <ReportFigureDetails
          document={doc}
          block={details.block}
          mode={details.mode}
          onClose={() => setDetails(null)}
        />
      ) : null}
      {history ? (
        <ReportHistoryDialog
          document={doc}
          onClose={() => setHistory(false)}
          onRestore={(content) =>
            execute(() =>
              saveReport(
                projectId,
                doc.report_id,
                doc.revision,
                content,
                "Restored presentation revision",
              ),
            )
          }
        />
      ) : null}
      {table ? (
        <TableDialog
          onClose={() => setTable(false)}
          onSave={async (b) => {
            if (await insert(b)) setTable(false);
          }}
        />
      ) : null}
      {menu && slide ? (
        <ReportFigureMenu
          x={menu.x}
          y={menu.y}
          editable={!!menu.block.version_id}
          formatName="slide"
          linked={!!menu.block.follow_plot_id}
          busy={busy}
          trigger={menu.trigger}
          onClose={() => setMenu(null)}
          onAction={(action) => {
            if (action === "link") void toggleLink();
            if (action === "refine")
              setEditor({
                kind: "figure",
                topicId: slide.id,
                blockId: menu.block.id,
              });
            if (action === "new")
              setEditor({ kind: "figure", topicId: slide.id });
            if (action === "code" || action === "export")
              setDetails({ block: menu.block, mode: action });
            if (action === "remove")
              void apply(
                [{ op: "remove_block", block_id: menu.block.id }],
                "Removed figure",
              );
          }}
        />
      ) : null}
      {presenting && slide ? (
        <div
          className="slides-present"
          role="dialog"
          aria-modal="true"
          aria-label="Presentation"
        >
          <SlideCanvas
            document={doc}
            section={slide}
            index={index}
            presenting
          />
          <div className="slides-present-controls">
            <button
              disabled={index === 0}
              onClick={() => choose(slides[index - 1]!.id)}
            >
              ← Previous
            </button>
            <span>
              {index + 1} / {slides.length}
            </span>
            <button
              disabled={index === slides.length - 1}
              onClick={() => choose(slides[index + 1]!.id)}
            >
              Next →
            </button>
            <button autoFocus onClick={() => setPresenting(false)}>
              Exit presentation
            </button>
          </div>
        </div>
      ) : null}
      <div className="slides-print">
        {slides.map((s, i) => (
          <SlideCanvas
            key={s.id}
            document={doc}
            section={s}
            index={i}
            presenting
          />
        ))}
      </div>
    </section>
  );
}
function TableDialog({
  onClose,
  onSave,
}: {
  onClose: () => void;
  onSave: (block: ReportBlock) => Promise<void>;
}) {
  const [title, setTitle] = useState(""),
    [value, setValue] = useState("Group\tValue\n"),
    [error, setError] = useState<string | null>(null),
    [busy, setBusy] = useState(false);
  return (
    <ReportDialog title="Add a table" onClose={onClose}>
      <form
        className="report-dialog-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setError(null);
          const [columns, ...rows] = value
            .trim()
            .split(/\r?\n/)
            .map((row) => row.split("\t"));
          if (
            !columns?.length ||
            columns.length > 30 ||
            rows.length > 200 ||
            rows.some((row) => row.length !== columns.length)
          ) {
            setError(
              "Use a header row and matching tab-separated columns, up to 30 columns and 200 rows.",
            );
            return;
          }
          setBusy(true);
          try {
            await onSave({
              id: createMutationId(),
              type: "table",
              title,
              columns,
              rows,
              source_description: "",
            });
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          Table title
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
          />
        </label>
        <label>
          Paste cells from a spreadsheet
          <textarea
            rows={8}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            required
          />
        </label>
        {error ? <p role="alert">{error}</p> : null}
        <footer>
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button disabled={busy}>Insert table</button>
        </footer>
      </form>
    </ReportDialog>
  );
}
