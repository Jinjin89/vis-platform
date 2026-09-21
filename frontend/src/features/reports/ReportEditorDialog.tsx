import { useRef, useState } from "react";
import Markdown from "react-markdown";
import { createMutationId, resolveArtifactUrl } from "../../api/client";
import type { ParameterValues } from "../../api/schemas/plotRun";
import type {
  ReportBlock,
  ReportDocument,
  ReportGenerateRequest,
  ReportSection,
} from "../../api/schemas/reports";
import { FigureInspector } from "../plot-run/FigureInspector";
import { validValue } from "../plot-run/ParameterForm";
import { ReportDialog } from "./ReportDialog";

export type ReportEditorTarget = {
  kind: "figure" | "text";
  topicId: string;
  blockId?: string;
  prompt?: string;
};
export function ReportEditorDialog({
  document,
  target,
  onClose,
  onGenerate,
  onSaveText,
}: {
  document: ReportDocument;
  target: ReportEditorTarget;
  onClose: () => void;
  onGenerate: (request: ReportGenerateRequest) => Promise<boolean>;
  onSaveText: (topic: ReportSection, block: ReportBlock) => Promise<boolean>;
}) {
  const currentTopic = document.content.sections.find(
    (t) => t.id === target.topicId,
  );
  const topic = currentTopic ?? {
    id: target.topicId,
    title: "Section unavailable",
    level: 1 as const,
    parent_id: null,
    blocks: [],
  };
  const block = topic.blocks.find((b) => b.id === target.blockId);
  const result =
    block?.type === "figure" && block.version_id
      ? document.figures[
          document.figure_bindings?.[block.id] ?? block.version_id!
        ]
      : undefined;
  const image =
    block?.type === "figure" && block.image_id
      ? document.images[block.image_id]
      : undefined;
  const [prompt, setPrompt] = useState(target.prompt ?? "");
  const [parameters, setParameters] = useState<ParameterValues>({});
  const [body, setBody] = useState(block?.type === "text" ? block.body : "");
  const [textMode, setTextMode] = useState<"write" | "assistant">("write");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const request = useRef({ key: "", id: "" });
  const blockId = useRef(createMutationId());
  const valid =
    !result ||
    (result.controls ?? []).every((c) =>
      validValue(c, parameters[c.id] ?? c.value),
    );
  const needsData =
    target.kind === "figure" &&
    !result &&
    !document.datasets.some((d) => d.state === "ready");
  async function generate(insertNew: boolean, changes = parameters) {
    if (
      inFlight.current ||
      !valid ||
      needsData ||
      (!prompt.trim() && !Object.keys(changes).length)
    )
      return false;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    const input = {
      base_revision: document.revision,
      section_id: topic.id,
      kind: target.kind,
      block_id: target.blockId,
      insert_new: insertNew,
      prompt: prompt.trim(),
      parameter_changes: changes,
    };
    const key = JSON.stringify(input);
    if (request.current.key !== key)
      request.current = { key, id: createMutationId() };
    try {
      const ok = await onGenerate({ ...input, request_id: request.current.id });
      if (ok) onClose();
      return ok;
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The edit could not be started.",
      );
      return false;
    } finally {
      setBusy(false);
      inFlight.current = false;
    }
  }
  if (!currentTopic || (target.blockId && !block)) {
    return (
      <ReportDialog title="Content no longer available" onClose={onClose}>
        <div className="report-dialog-form">
          <p>
            The selected topic or block was removed. Your draft is available
            below to copy into another topic.
          </p>
          <textarea
            aria-label="Preserved report draft"
            readOnly
            rows={8}
            value={
              target.kind === "text" && textMode === "write" ? body : prompt
            }
          />
          <footer>
            <button type="button" onClick={onClose}>
              Close editor
            </button>
          </footer>
        </div>
      </ReportDialog>
    );
  }
  return (
    <ReportDialog
      title={
        target.kind === "figure"
          ? block
            ? "Refine figure"
            : "New figure"
          : block
            ? "Edit text"
            : "Add text"
      }
      wide={target.kind === "figure"}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <div className="report-editor-context">
        <span>{document.content.kind === "slides" ? "SLIDE" : "SECTION"}</span>
        <strong>{topic.title}</strong>
        {result ? (
          <small>Uses this figure's saved data</small>
        ) : (
          <small>{document.datasets.length} datasets available</small>
        )}
      </div>
      {target.kind === "figure" ? (
        <>
          <div className="report-figure-editor">
            <div className="report-editor-preview">
              {result || image ? (
                <img
                  src={resolveArtifactUrl(
                    result?.preview.href ?? image!.links.content,
                  )}
                  alt={result?.title ?? "Current figure"}
                />
              ) : (
                <div className="report-new-figure-placeholder">
                  <span>◩</span>
                  <h3>
                    {document.content.kind === "slides"
                      ? "Add a figure to this slide"
                      : "Give this section its first figure"}
                  </h3>
                  <p>
                    Describe the comparison or relationship you want to show.
                  </p>
                  {document.datasets.map((d) => (
                    <small key={d.dataset_id}>{d.name}</small>
                  ))}
                </div>
              )}
            </div>
            {result ? (
              <FigureInspector
                projectId={document.project_id}
                result={result}
                disabled={busy}
                parameterDraft={parameters}
                onParameterDraftChange={setParameters}
                parameterApplyLabel="Update figure"
                onApply={(changes) => generate(false, changes)}
              />
            ) : (
              <div className="report-editor-data">
                <h3>Data for this figure</h3>
                {document.datasets.length ? (
                  document.datasets.map((d) => (
                    <section key={d.dataset_id}>
                      <strong>{d.name}</strong>
                      <p>{d.description}</p>
                      <small>
                        {d.objects?.length ?? 0} objects · {d.state}
                      </small>
                    </section>
                  ))
                ) : (
                  <p>
                    Add a dataset from the report toolbar, then create a figure.
                  </p>
                )}
              </div>
            )}
          </div>
          <div className="report-editor-instructions">
            <label htmlFor="report-figure-prompt">
              {block ? "What would you like to change?" : "Describe the figure"}
            </label>
            <textarea
              id="report-figure-prompt"
              autoFocus={!result}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              maxLength={8000}
              rows={3}
              placeholder={
                block
                  ? "e.g. Show individual points and use a softer palette…"
                  : "e.g. Compare expression across treatment groups…"
              }
              disabled={busy}
            />
            {needsData ? (
              <p className="report-error">
                Add a ready dataset before creating a figure.
              </p>
            ) : (
              <small>
                {Object.keys(parameters).length
                  ? `${Object.keys(parameters).length} parameter drafts. `
                  : ""}
                The current report stays visible while the new figure runs.
              </small>
            )}
            {error ? (
              <p className="report-error" role="alert">
                {error}
              </p>
            ) : null}
            <footer>
              <button type="button" disabled={busy} onClick={onClose}>
                Cancel
              </button>
              <div>
                {block ? (
                  <button
                    type="button"
                    disabled={
                      busy ||
                      !valid ||
                      needsData ||
                      (!prompt.trim() && !Object.keys(parameters).length)
                    }
                    onClick={() => void generate(true)}
                  >
                    Add as new figure
                  </button>
                ) : null}
                <button
                  type="button"
                  className="report-primary"
                  disabled={
                    busy ||
                    !valid ||
                    needsData ||
                    (!prompt.trim() && !Object.keys(parameters).length)
                  }
                  onClick={() => void generate(false)}
                >
                  {busy
                    ? "Starting…"
                    : block
                      ? "Update figure"
                      : "Create figure"}
                </button>
              </div>
            </footer>
          </div>
        </>
      ) : (
        <div className="report-text-editor">
          <div
            className="report-editor-tabs"
            role="group"
            aria-label="Text editing mode"
          >
            <button
              type="button"
              aria-pressed={textMode === "write"}
              onClick={() => setTextMode("write")}
            >
              Write text
            </button>
            <button
              type="button"
              aria-pressed={textMode === "assistant"}
              onClick={() => setTextMode("assistant")}
            >
              Ask assistant
            </button>
          </div>
          {textMode === "write" ? (
            <>
              <label htmlFor="report-text-body">Report text</label>
              <textarea
                id="report-text-body"
                autoFocus
                value={body}
                onChange={(e) => setBody(e.target.value)}
                maxLength={30000}
                rows={10}
                placeholder="Write the purpose, method, or findings for this section…"
              />
              <small>
                Markdown headings, lists, and emphasis are supported.
              </small>
              <details>
                <summary>Preview text</summary>
                <Markdown>{body}</Markdown>
              </details>
            </>
          ) : (
            <>
              <label htmlFor="report-text-instruction">
                Instructions for this section
              </label>
              <textarea
                id="report-text-instruction"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                maxLength={8000}
                rows={5}
                placeholder="e.g. Summarize what the figures in this section show…"
              />
              <p>
                The assistant uses the section's saved figures, results, and
                dataset descriptions.
              </p>
            </>
          )}
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
              type="button"
              className="report-primary"
              disabled={
                busy || !(textMode === "write" ? body.trim() : prompt.trim())
              }
              onClick={async () => {
                if (textMode === "assistant") {
                  await generate(false);
                  return;
                }
                setBusy(true);
                setError(null);
                try {
                  if (
                    await onSaveText(topic, {
                      id: block?.id ?? blockId.current,
                      type: "text",
                      body,
                      evidence_version_ids:
                        block?.type === "text"
                          ? block.evidence_version_ids
                          : [],
                    })
                  )
                    onClose();
                } catch (reason) {
                  setError(
                    reason instanceof Error
                      ? reason.message
                      : "Text could not be saved.",
                  );
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy
                ? "Saving…"
                : textMode === "assistant"
                  ? "Generate text"
                  : "Save text"}
            </button>
          </footer>
        </div>
      )}
    </ReportDialog>
  );
}
