import { linkSharedFigure } from "../api/slides";
import { figureForBlock } from "../api/schemas/reports";
import { SlidesWorkspace } from "../features/slides/SlidesWorkspace";
import { FigureWorkspace } from "../features/figures/FigureWorkspace";
import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { createMutationId, createProject } from "../api/client";
import {
  createReport,
  generateReportContent,
  getReport,
  listReports,
  saveReport,
  applyReportOperations,
  sendReportMessage,
} from "../api/reports";
import {
  reportEditActive,
  type ReportBlock,
  type ReportContent,
  type ReportDocument,
  type ReportFigure,
  type ReportGenerateRequest,
  type ReportMessageRequest,
  type ReportOperation,
} from "../api/schemas/reports";
import { WorkspaceSwitcher } from "../components/WorkspaceSwitcher";
import { ResizablePanels } from "../components/ResizablePanels";
import { DatasetSelector } from "../features/datasets/DatasetSelector";
import {
  ReportAssistantPanel,
  type ReportComposeTarget,
} from "../features/reports/ReportAssistantPanel";
import { ReportCreateDialog } from "../features/reports/ReportCreateDialog";
import {
  ReportEditorDialog,
  type ReportEditorTarget,
} from "../features/reports/ReportEditorDialog";
import { ReportDocumentView } from "../features/reports/ReportDocumentView";
import {
  ReportFigureMenu,
  type FigureAction,
} from "../features/reports/ReportFigureMenu";
import {
  ReportFigureDetails,
  ReportHistoryDialog,
  ReportImageDialog,
  SavedFigureDialog,
} from "../features/reports/ReportLibraryDialogs";
import { downloadReportFile } from "../features/reports/ReportDialog";
import "../features/reports/reports.css";

export function ReportPage({
  format = "report",
}: {
  format?: "report" | "slides" | "figure";
}) {
  const [projectId, setProjectId] = useState<string | null>(() => {
    try {
      return window.sessionStorage.getItem("vis-platform.project-id");
    } catch {
      return null;
    }
  });
  const [error, setError] = useState<string | null>(null);
  const creation = useRef<Promise<string> | null>(null);
  const ensure = useCallback(async () => {
    if (projectId) return projectId;
    if (!creation.current)
      creation.current = createProject()
        .then((project) => {
          try {
            window.sessionStorage.setItem(
              "vis-platform.project-id",
              project.project_id,
            );
          } catch {
            /* Storage is optional. */
          }
          setProjectId(project.project_id);
          setError(null);
          return project.project_id;
        })
        .catch((reason) => {
          creation.current = null;
          throw reason;
        });
    return creation.current;
  }, [projectId]);
  useEffect(() => {
    void ensure().catch((reason) => setError(reason.message));
  }, [ensure]);
  return (
    <main className="app-shell report-shell">
      <header className="top-bar">
        <div className="brand" aria-label="Vis Platform">
          <span className="brand-name">vis.</span>
        </div>
        <div className="project-title">
          <span className="project-kicker">Research studio</span>
          <strong>Untitled study</strong>
        </div>
        <WorkspaceSwitcher />
      </header>
      {projectId ? (
        format === "slides" ? (
          <SlidesWorkspace key={projectId} projectId={projectId} />
        ) : format === "figure" ? (
          <FigureWorkspace key={projectId} projectId={projectId} />
        ) : (
          <ReportWorkspace key={projectId} projectId={projectId} />
        )
      ) : (
        <div className="report-loading">
          {error ? (
            <>
              <p role="alert">{error}</p>
              <button
                type="button"
                onClick={() =>
                  void ensure().catch((reason) => setError(reason.message))
                }
              >
                Retry
              </button>
            </>
          ) : (
            <p>Opening reports…</p>
          )}
        </div>
      )}
    </main>
  );
}

function ReportWorkspace({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const reportId = params.get("id");
  const [offset, setOffset] = useState(0);
  const [createMode, setCreateMode] = useState<"new" | "import" | null>(null);
  const [selection, setSelection] = useState<{
    topicId: string | null;
    blockId?: string;
  }>({ topicId: null });
  const [assistantOpen, setAssistantOpen] = useState(
    () => window.matchMedia?.("(min-width: 960px)").matches ?? true,
  );
  const [composeTarget, setComposeTarget] =
    useState<ReportComposeTarget | null>(null);
  const composeSequence = useRef(0);
  const selectedTopic = selection.topicId;
  function setSelectedTopic(id: string | null) {
    setSelection((current) => ({
      topicId: id,
      blockId: current.topicId === id ? current.blockId : undefined,
    }));
  }
  const [editor, setEditor] = useState<ReportEditorTarget | null>(null);
  const [libraryTopic, setLibraryTopic] = useState<string | null>(null);
  const [imageTopic, setImageTopic] = useState<string | null>(null);
  const [history, setHistory] = useState(false);
  const [figureDetails, setFigureDetails] = useState<{
    block: ReportFigure;
    mode: "code" | "export";
  } | null>(null);
  const [menu, setMenu] = useState<{
    x: number;
    y: number;
    topicId: string;
    blockId: string;
    trigger: HTMLElement | null;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const list = useQuery({
    queryKey: ["reports", projectId, offset],
    queryFn: () => listReports(projectId, offset),
  });
  const report = useQuery({
    queryKey: ["report", projectId, reportId],
    queryFn: () => getReport(projectId, reportId!),
    enabled: !!reportId,
    refetchInterval: (query) =>
      query.state.error
        ? false
        : query.state.data?.messages.some((message) =>
              ["running", "awaiting_input", "awaiting_approval"].includes(
                message.status,
              ),
            ) ||
            query.state.data?.edits.some(reportEditActive) ||
            query.state.data?.datasets.some((d) =>
              ["processing", "uploading"].includes(d.state ?? ""),
            )
          ? 1000
          : query.state.data?.content.sections.some((s) =>
                s.blocks.some((b) => b.type === "figure" && b.follow_plot_id),
              )
            ? 2500
            : false,
  });
  const document = report.data;
  const currentTopic = document?.content.sections.find(
    (topic) => topic.id === selectedTopic,
  );
  const currentBlock = currentTopic?.blocks.find(
    (block) => block.id === selection.blockId,
  );
  const menuBlock = document?.content.sections
    .find((topic) => topic.id === menu?.topicId)
    ?.blocks.find((block) => block.id === menu?.blockId);
  const closeMenu = useCallback(() => setMenu(null), []);
  function showReport(next: ReportDocument) {
    client.setQueryData(["report", projectId, next.report_id], next);
    void client.invalidateQueries({ queryKey: ["reports", projectId] });
    if (next.report_id !== reportId) {
      setParams({ id: next.report_id });
      setSelectedTopic(null);
    }
  }
  async function save(content: ReportContent, summary: string) {
    if (!document) return false;
    setSaving(true);
    try {
      showReport(
        await saveReport(
          projectId,
          document.report_id,
          document.revision,
          content,
          summary,
        ),
      );
      setError(null);
      return true;
    } catch (reason) {
      void report.refetch();
      throw reason;
    } finally {
      setSaving(false);
    }
  }
  async function apply(operations: ReportOperation[], summary: string) {
    if (!document) return false;
    setSaving(true);
    try {
      showReport(
        await applyReportOperations(
          projectId,
          document.report_id,
          document.revision,
          operations,
          createMutationId(),
          summary,
        ),
      );
      setError(null);
      return true;
    } catch (reason) {
      void report.refetch();
      throw reason;
    } finally {
      setSaving(false);
    }
  }
  async function sendMessage(input: ReportMessageRequest) {
    if (!document) return false;
    setAssistantOpen(true);
    showReport(await sendReportMessage(projectId, document.report_id, input));
    return true;
  }
  async function perform(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The report could not be updated.",
      );
    }
  }
  async function insertBlock(topicId: string, block: ReportBlock) {
    return apply(
      [
        {
          op: "insert_block",
          section_id: topicId,
          block,
          before_id: null,
          after_id: null,
        },
      ],
      "Added " + block.type,
    );
  }
  async function generate(input: ReportGenerateRequest) {
    setAssistantOpen(true);
    setSelection({
      topicId: input.section_id,
      blockId: input.block_id ?? undefined,
    });
    try {
      showReport(
        await generateReportContent(projectId, document!.report_id, input),
      );
      return true;
    } catch (reason) {
      void report.refetch();
      throw reason;
    }
  }
  function selectTopic(id: string) {
    setSelection({ topicId: id });
    setComposeTarget(null);
    window.document
      .getElementById("report-topic-" + id)
      ?.scrollIntoView({ block: "start", behavior: "smooth" });
  }
  function selectBlock(topicId: string, blockId: string) {
    setSelection({ topicId, blockId });
    setComposeTarget(null);
    setAssistantOpen(true);
  }
  function compose(topicId: string, kind: "text" | "figure", blockId?: string) {
    setSelection({ topicId, blockId });
    setAssistantOpen(true);
    const title =
      document?.content.sections.find((section) => section.id === topicId)
        ?.title ?? "this section";
    const prompt =
      kind === "figure"
        ? blockId
          ? "Refine this figure: "
          : `Create a figure in “${title}” showing `
        : blockId
          ? "Revise this paragraph: "
          : `Write a paragraph in “${title}” about `;
    setComposeTarget({ prompt, key: ++composeSequence.current });
  }
  function moveTopic(index: number, direction: number) {
    const section = document!.content.sections[index]!;
    const siblings = document!.content.sections.filter(
      (item) => item.parent_id === section.parent_id,
    );
    const adjacent =
      siblings[
        siblings.findIndex((item) => item.id === section.id) + direction
      ];
    if (!adjacent) return;
    void perform(() =>
      apply(
        [
          {
            op: "move_section",
            section_id: section.id,
            parent_id: section.parent_id,
            before_id: direction < 0 ? adjacent.id : null,
            after_id: direction > 0 ? adjacent.id : null,
          },
        ],
        "Moved section",
      ),
    );
  }
  function actOnFigure(action: FigureAction) {
    if (!menu || !document || menuBlock?.type !== "figure") return;
    if (action === "refine")
      setEditor({
        kind: "figure",
        topicId: menu.topicId,
        blockId: menu.blockId,
      });
    if (action === "new") setEditor({ kind: "figure", topicId: menu.topicId });
    if (action === "code" || action === "export")
      setFigureDetails({ block: menuBlock, mode: action });
    if (action === "link" && menuBlock.version_id) {
      const block = menuBlock;
      const current = figureForBlock(document, block)!;
      void perform(async () => {
        const selected = block.follow_plot_id
          ? current
          : await linkSharedFigure(
              projectId,
              current.plot_id,
              current.version_id,
            );
        return apply(
          [
            {
              op: "replace_block",
              section_id: menu.topicId,
              block: {
                ...block,
                version_id: selected.version_id,
                follow_plot_id: block.follow_plot_id ? null : selected.plot_id,
              },
            },
          ],
          block.follow_plot_id
            ? "Pinned figure version"
            : "Linked figure updates",
        );
      });
    }
    if (action === "remove")
      void perform(() =>
        apply(
          [{ op: "remove_block", block_id: menu.blockId }],
          "Removed figure",
        ),
      );
  }

  function addTopic(parentId?: string) {
    const id = createMutationId();
    void perform(async () => {
      if (
        await apply(
          [
            {
              op: "insert_section",
              section: {
                id,
                title: parentId ? "New subsection" : "New section",
                level: parentId ? 2 : 1,
                parent_id: parentId ?? null,
                blocks: [],
              },
              before_id: null,
              after_id: null,
            },
          ],
          parentId ? "Added subsection" : "Added section",
        )
      ) {
        setSelectedTopic(id);
        window.setTimeout(
          () =>
            window.document.getElementById("report-topic-title-" + id)?.focus(),
          0,
        );
      }
    });
  }
  const working = document?.edits.filter(reportEditActive) ?? [];
  const planning = document?.messages.some((message) =>
    ["running", "awaiting_input", "awaiting_approval"].includes(message.status),
  );
  return (
    <div className="report-workspace">
      <div className="report-toolbar">
        <div>
          <button
            type="button"
            className="report-library-back"
            onClick={() => {
              setParams({});
              setEditor(null);
              setError(null);
            }}
          >
            Reports
          </button>
          {document ? (
            <>
              <span className="report-breadcrumb">/</span>
              <span className="report-current-title">{document.title}</span>
            </>
          ) : (
            <span className="report-toolbar-description">
              Build a story from your data
            </span>
          )}
        </div>
        <div className="report-toolbar-actions">
          {document ? (
            <>
              <span className="report-save-status" aria-live="polite">
                {saving
                  ? "Saving…"
                  : planning || working.length
                    ? "Working…"
                    : "Saved"}
              </span>
              <DatasetSelector
                projectId={projectId}
                ensureProject={async () => projectId}
                selectedIds={document.content.datasets.map(
                  (dataset) => dataset.dataset_id,
                )}
                onSelect={(ids) =>
                  void perform(() =>
                    apply(
                      [
                        {
                          op: "set_datasets",
                          datasets: ids.map((dataset_id) => ({
                            dataset_id,
                            revision_id: null,
                          })),
                        },
                      ],
                      "Updated report datasets",
                    ),
                  )
                }
                resultIds={[]}
                onUseResult={() => {}}
                datasetsOnly
                disabled={saving}
              />
              <button
                type="button"
                aria-pressed={assistantOpen}
                aria-label="Toggle report assistant"
                onClick={() => setAssistantOpen(!assistantOpen)}
              >
                Assistant
              </button>
              <button type="button" onClick={() => setHistory(true)}>
                History
              </button>
              <details className="report-export-options">
                <summary>Export</summary>
                <div>
                  <button
                    type="button"
                    onClick={() =>
                      downloadReportFile(
                        JSON.stringify(document.content, null, 2),
                        "report.json",
                      )
                    }
                  >
                    Pre-report JSON
                  </button>
                  <button type="button" onClick={() => window.print()}>
                    Print / Save PDF
                  </button>
                </div>
              </details>
            </>
          ) : null}
          <button type="button" onClick={() => setCreateMode("import")}>
            Import
          </button>
          <button
            type="button"
            className="report-primary"
            onClick={() => setCreateMode("new")}
          >
            + New report
          </button>
        </div>
      </div>
      {error || report.isError ? (
        <div className="report-page-error" role="alert">
          {error ?? report.error?.message}
          <button
            type="button"
            onClick={() => {
              setError(null);
              void report.refetch();
            }}
          >
            Reload latest
          </button>
        </div>
      ) : null}
      {!reportId ? (
        <div className="report-library">
          <div className="report-welcome">
            <span className="report-eyebrow">
              FROM EXPLORATION TO EXPLANATION
            </span>
            <h1>Give your findings a home.</h1>
            <p>
              Bring data, figures, and writing together.
              <br />
              Build your report one scientific topic at a time.
            </p>
          </div>
          <div className="report-start-options">
            <button type="button" onClick={() => setCreateMode("new")}>
              <span>▤</span>
              <h2>Start with your data</h2>
              <p>Create a report, choose datasets, and add your first topic.</p>
              <strong>New report ↗</strong>
            </button>
            <button type="button" onClick={() => setCreateMode("import")}>
              <span>↥</span>
              <h2>Continue a pre-report</h2>
              <p>Load topics and prepared outputs from a structured report.</p>
              <strong>Import pre-report ↗</strong>
            </button>
          </div>
          <section className="report-library-list">
            <h2>Your reports</h2>
            {list.isPending ? (
              <p>Loading reports…</p>
            ) : list.isError ? (
              <p role="alert">
                {list.error.message}
                <button type="button" onClick={() => void list.refetch()}>
                  Retry
                </button>
              </p>
            ) : list.data.reports.length ? (
              list.data.reports.map((item) => (
                <button
                  type="button"
                  key={item.report_id}
                  onClick={() => {
                    setParams({ id: item.report_id });
                    setSelectedTopic(null);
                  }}
                >
                  <span>▤</span>
                  <strong>{item.title}</strong>
                  <small>
                    Revision {item.revision} ·{" "}
                    {new Date(item.updated_at).toLocaleDateString()}
                  </small>
                  <span>↗</span>
                </button>
              ))
            ) : (
              <p className="report-empty-library">
                Your saved reports will appear here.
              </p>
            )}
            {(list.data?.total ?? 0) > 30 ? (
              <div className="report-pagination">
                <button
                  type="button"
                  disabled={!offset}
                  onClick={() => setOffset(offset - 30)}
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={offset + 30 >= (list.data?.total ?? 0)}
                  onClick={() => setOffset(offset + 30)}
                >
                  Next
                </button>
              </div>
            ) : null}
          </section>
        </div>
      ) : report.isPending ? (
        <div className="report-loading">Loading your report…</div>
      ) : document ? (
        <ResizablePanels
          direction="horizontal"
          label="Resize report assistant"
          className={
            "report-editor-layout " +
            (assistantOpen ? "assistant-open" : "assistant-closed")
          }
          storageKey="vis-platform.report-assistant-width"
          firstMinimum={540}
          secondMinimum={320}
          secondMaximum={550}
          fixedSize={assistantOpen ? undefined : 0}
        >
          <ReportDocumentView
            document={document}
            saving={saving}
            selectedTopic={currentTopic?.id ?? null}
            selectedBlockId={currentBlock?.id}
            selectTopic={selectTopic}
            setSelectedTopic={setSelectedTopic}
            selectBlock={selectBlock}
            compose={compose}
            addTopic={addTopic}
            moveTopic={moveTopic}
            apply={apply}
            perform={perform}
            setEditor={setEditor}
            setLibraryTopic={setLibraryTopic}
            setImageTopic={setImageTopic}
            setMenu={setMenu}
          />
          <ReportAssistantPanel
            key={document.report_id}
            document={document}
            section={currentTopic}
            block={currentBlock}
            composeTarget={composeTarget}
            open={assistantOpen}
            onClose={() => setAssistantOpen(false)}
            onClearSelection={() => {
              setSelection({ topicId: null });
              setComposeTarget(null);
            }}
            onSend={sendMessage}
            onShowReport={showReport}
            onEditDirectly={setEditor}
            refresh={() => report.refetch()}
          />
        </ResizablePanels>
      ) : null}
      {createMode ? (
        <ReportCreateDialog
          projectId={projectId}
          mode={createMode}
          onClose={() => setCreateMode(null)}
          onCreate={async (content, key) => {
            showReport(await createReport(projectId, content, key));
            setCreateMode(null);
          }}
        />
      ) : null}
      {document && editor ? (
        <ReportEditorDialog
          key={`${editor.topicId}:${editor.blockId ?? "new"}:${editor.kind}`}
          document={document}
          target={editor}
          onClose={() => setEditor(null)}
          onGenerate={generate}
          onSaveText={(topic, block) =>
            apply(
              [
                topic.blocks.some((item) => item.id === block.id)
                  ? { op: "replace_block", section_id: topic.id, block }
                  : {
                      op: "insert_block",
                      section_id: topic.id,
                      block,
                      before_id: null,
                      after_id: null,
                    },
              ],
              "Saved paragraph",
            )
          }
        />
      ) : null}
      {document && libraryTopic ? (
        <SavedFigureDialog
          document={document}
          onClose={() => setLibraryTopic(null)}
          onInsert={(block) => insertBlock(libraryTopic, block)}
        />
      ) : null}
      {document && imageTopic ? (
        <ReportImageDialog
          projectId={projectId}
          onClose={() => setImageTopic(null)}
          onInsert={(block) => insertBlock(imageTopic, block)}
        />
      ) : null}
      {document && history ? (
        <ReportHistoryDialog
          document={document}
          onClose={() => setHistory(false)}
          onRestore={(content, revision) =>
            save(content, `Restored revision ${revision}`)
          }
        />
      ) : null}
      {document && figureDetails ? (
        <ReportFigureDetails
          document={document}
          {...figureDetails}
          onClose={() => setFigureDetails(null)}
        />
      ) : null}
      {document && menu && menuBlock?.type === "figure" ? (
        <ReportFigureMenu
          x={menu.x}
          y={menu.y}
          editable={!!menuBlock.version_id}
          linked={!!menuBlock.follow_plot_id}
          busy={working.some((e) => e.block_id === menu.blockId)}
          onAction={actOnFigure}
          onClose={closeMenu}
          trigger={menu.trigger}
        />
      ) : null}
    </div>
  );
}
