import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  answerPlanner,
  answerQuestion,
  cancelAssistant,
  cancelPlotRun,
  decideApproval,
} from "../../api/client";
import { getPlotSource } from "../../api/plotSource";
import { plannerQuestionsSchema } from "../../api/schemas/planner";
import type { ParameterValues } from "../../api/schemas/plotRun";
import { FigureInspector } from "../plot-run/FigureInspector";
import { FigureExportMenu } from "../plot-run/FigureExportMenu";
import { PlannerQuestionCard } from "../plot-run/PlannerQuestionCard";
import { CanvasImage, NodeStatus } from "./CanvasNodeCard";
import type { CanvasNode, NodeDraft, PlotNode } from "./model";
import { isActive } from "./model";

type Props = {
  node: CanvasNode;
  projectId: string;
  draft: NodeDraft;
  parentLabel?: string;
  onClose: () => void;
  onDraft: (changes: ParameterValues) => void;
  onCreate: (changes: ParameterValues) => Promise<boolean>;
  onReuse: () => void;
};
export function CanvasInspector({
  node,
  projectId,
  draft,
  parentLabel,
  onClose,
  onDraft,
  onCreate,
  onReuse,
}: Props) {
  const [view, setView] = useState<"preview" | "code">("preview");
  const result = node.type === "plot" ? node.snapshot?.result : null;
  const source = useQuery({
    queryKey: ["plot-source", projectId, result?.version_id],
    queryFn: () =>
      getPlotSource(projectId, result!.plot_id, result!.version_id),
    enabled: !!result && view === "code",
    staleTime: Infinity,
  });
  const code = node.type === "plot" ? (node.source ?? source.data) : null;
  function exportCode() {
    if (!code?.code) return;
    const url = URL.createObjectURL(
      new Blob([code.code], { type: "text/plain;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `${node.label}-plot.R`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <aside className="canvas-inspector" aria-label="Node preview">
      <header className="canvas-inspector-header">
        <div>
          <span className="canvas-eyebrow">
            {node.type === "data" ? "DATASET" : "PLOT"} <b>{node.label}</b>
          </span>
          <h2>{node.title}</h2>
        </div>
        <button
          type="button"
          className="canvas-icon-button"
          aria-label="Close node preview"
          onClick={onClose}
        >
          ×
        </button>
      </header>
      <div className="canvas-inspector-body">
        {node.type === "data" ? (
          <div className="canvas-dataset-preview">
            <div className="canvas-dataset-summary">
              <span>▤</span>
              <strong>{node.summary}</strong>
            </div>
            <p>
              {node.dataset.description ||
                "A collection of data objects ready for exploration."}
            </p>
            {node.dataset.contains_demo_data ? (
              <p className="data-demo-badge">Synthetic demonstration data</p>
            ) : null}
            <dl className="canvas-metadata">
              <div>
                <dt>Source</dt>
                <dd>
                  {node.dataset.source_kind === "upload"
                    ? "Uploaded dataset"
                    : "Analysis platform"}
                </dd>
              </div>
              <div>
                <dt>Revision</dt>
                <dd>{node.dataset.revision_id ?? "Processing"}</dd>
              </div>
            </dl>
            {(node.dataset.notices ?? []).map((notice) => (
              <p key={notice} className="data-help">
                {notice}
              </p>
            ))}
            {(node.dataset.objects ?? []).map((object) => (
              <section className="canvas-object-preview" key={object.object_id}>
                <h3>{object.name}</h3>
                <p>{object.description}</p>
                <small>
                  {object.kind} · {(object.dimensions ?? []).join(" × ")} ·{" "}
                  {object.readiness}
                </small>
                {(object.columns ?? []).length ? (
                  <div className="canvas-table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Column</th>
                          <th>Type</th>
                          <th>Missing</th>
                        </tr>
                      </thead>
                      <tbody>
                        {object.columns!.map((column) => (
                          <tr key={column.name}>
                            <td title={column.description ?? undefined}>
                              {column.name}
                            </td>
                            <td>{column.data_type}</td>
                            <td>{column.missing_count ?? 0}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
                {(object.limitations ?? []).map((text) => (
                  <p key={text} className="data-help">
                    {text}
                  </p>
                ))}
              </section>
            ))}
            <p className="canvas-panel-note">
              Describe a plot below the canvas to start a new branch from this
              dataset.
            </p>
          </div>
        ) : (
          <>
            <div className="canvas-inspector-meta">
              <NodeStatus node={node} />
              <span>{parentLabel ? `From ${parentLabel}` : "New branch"}</span>
            </div>
            {result ? (
              <>
                <div className="canvas-preview-toolbar">
                  <div role="group" aria-label="Preview display">
                    <button
                      type="button"
                      aria-pressed={view === "preview"}
                      onClick={() => setView("preview")}
                    >
                      Preview
                    </button>
                    <button
                      type="button"
                      aria-pressed={view === "code"}
                      onClick={() => setView("code")}
                    >
                      R code
                    </button>
                  </div>
                  {view === "preview" ? (
                    <FigureExportMenu projectId={projectId} result={result} />
                  ) : (
                    <button
                      type="button"
                      disabled={!code?.code}
                      onClick={exportCode}
                    >
                      Export .R
                    </button>
                  )}
                </div>
                {view === "preview" ? (
                  <div className="canvas-large-preview">
                    <CanvasImage
                      key={result.preview.href}
                      href={result.preview.href}
                      description={node.title}
                    />
                  </div>
                ) : (
                  <div className="canvas-code-preview">
                    {code ? (
                      <>
                        {code.code ? (
                          <pre
                            tabIndex={0}
                            role="region"
                            aria-label="Complete R plotting code"
                          >
                            <code>{code.code}</code>
                          </pre>
                        ) : null}
                        <p>{code.message}</p>
                      </>
                    ) : source.isError ? (
                      <p role="alert">
                        {source.error.message}{" "}
                        <button
                          type="button"
                          onClick={() => void source.refetch()}
                        >
                          Retry code loading
                        </button>
                      </p>
                    ) : (
                      <p>Loading saved R code…</p>
                    )}
                  </div>
                )}
                <div className="canvas-draft-note">
                  Parameter edits are drafts. Create a refinement to save a new
                  plot.
                </div>
                <FigureInspector
                  key={node.id}
                  projectId={projectId}
                  result={result}
                  disabled={false}
                  onApply={(changes) => onCreate(changes)}
                  parameterDraft={draft.parameters}
                  onParameterDraftChange={onDraft}
                  parameterApplyLabel="Create refinement"
                />
              </>
            ) : (
              <NodeInteraction
                key={node.id}
                node={node}
                projectId={projectId}
              />
            )}
            {!isActive(node) && !result ? (
              <button
                type="button"
                className="canvas-reuse-button"
                onClick={onReuse}
              >
                Reuse these instructions
              </button>
            ) : null}
            <details className="canvas-provenance">
              <summary>Creation details</summary>
              <dl className="canvas-metadata">
                <div>
                  <dt>Instructions</dt>
                  <dd>{node.prompt || "Parameter refinement"}</dd>
                </div>
                <div>
                  <dt>Dataset</dt>
                  <dd>{node.sourceDatasetId}</dd>
                </div>
                <div>
                  <dt>Dataset revision</dt>
                  <dd>
                    {node.sourceDatasetRevisionId ?? "Recorded in plot inputs"}
                  </dd>
                </div>
                <div>
                  <dt>Parent</dt>
                  <dd>{parentLabel ?? "Dataset"}</dd>
                </div>
                <div>
                  <dt>Created</dt>
                  <dd>{new Date(node.createdAt).toLocaleString()}</dd>
                </div>
              </dl>
              {Object.keys(node.request.changes).length ? (
                <pre>{JSON.stringify(node.request.changes, null, 2)}</pre>
              ) : null}
            </details>
          </>
        )}
      </div>
    </aside>
  );
}

function NodeInteraction({
  node,
  projectId,
}: {
  node: PlotNode;
  projectId: string;
}) {
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const question = node.snapshot?.pending_question;
  const approval = node.snapshot?.pending_approval;
  const planner = node.assistantSnapshot?.question
    ? plannerQuestionsSchema.parse(node.assistantSnapshot.question)
    : null;
  async function refresh() {
    await Promise.all([
      client.invalidateQueries({
        queryKey: ["canvas-run", projectId, node.run?.run_id],
      }),
      client.invalidateQueries({
        queryKey: ["canvas-assistant", projectId, node.assistant?.turnId],
      }),
    ]);
  }
  async function perform(action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The request could not be updated.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="canvas-execution-details">
      {node.status === "running" ? (
        <>
          <span className="canvas-spinner" />
          <h3>Following your instructions</h3>
          <p>
            {node.snapshot?.progress?.message ??
              "Planning the plot and preparing R execution…"}
          </p>
          <progress value={node.snapshot?.progress?.progress} max={100} />
        </>
      ) : null}
      {node.error ? (
        <p role="alert" className="canvas-error">
          {node.error}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="canvas-error">
          {error}
        </p>
      ) : null}
      {planner && node.assistant ? (
        <PlannerQuestionCard
          key={planner.interaction_id}
          question={planner}
          disabled={busy}
          onAnswer={async (answers) => {
            await answerPlanner(
              node.assistant!.turnId,
              projectId,
              planner.interaction_id,
              answers,
            );
            await refresh();
            return true;
          }}
        />
      ) : null}
      {question ? (
        <section>
          <h3>{question.prompt}</h3>
          <p>{question.reason}</p>
          {question.choices.map((choice) => (
            <button
              className="canvas-question-choice"
              type="button"
              disabled={busy}
              key={choice.choice_id}
              onClick={() =>
                void perform(() =>
                  answerQuestion(node.run!.run_id, question.question_id, {
                    choiceId: choice.choice_id,
                  }),
                )
              }
            >
              {choice.label}
            </button>
          ))}
          {question.allow_free_text ? (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (answer.trim())
                  void perform(() =>
                    answerQuestion(node.run!.run_id, question.question_id, {
                      freeText: answer.trim(),
                    }),
                  );
              }}
            >
              <label>
                Your answer
                <input
                  value={answer}
                  onChange={(event) => setAnswer(event.target.value)}
                />
              </label>
              <button type="submit" disabled={busy || !answer.trim()}>
                Continue
              </button>
            </form>
          ) : null}
        </section>
      ) : null}
      {approval ? (
        <section>
          <h3>{approval.summary}</h3>
          <p>{approval.scientific_effect}</p>
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              void perform(() =>
                decideApproval(
                  node.run!.run_id,
                  approval.approval_id,
                  "approve",
                ),
              )
            }
          >
            Approve change
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              void perform(() =>
                decideApproval(
                  node.run!.run_id,
                  approval.approval_id,
                  "reject",
                ),
              )
            }
          >
            Reject change
          </button>
        </section>
      ) : null}
      {isActive(node) && node.error ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => void perform(refresh)}
        >
          Reconnect updates
        </button>
      ) : null}
      {isActive(node) && (node.run || node.assistant?.cancel) ? (
        <button
          className="canvas-cancel"
          type="button"
          disabled={busy}
          onClick={() =>
            void perform(() =>
              node.run
                ? cancelPlotRun(node.run.links.cancel)
                : cancelAssistant(node.assistant!.cancel!),
            )
          }
        >
          Cancel request
        </button>
      ) : null}
    </div>
  );
}
