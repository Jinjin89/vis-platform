import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import { createMutationId } from "../../api/client";
import {
  answerReportMessage,
  cancelReportEdit,
  cancelReportMessage,
} from "../../api/reports";
import type {
  ReportBlock,
  ReportDocument,
  ReportMessageRequest,
  ReportSection,
} from "../../api/schemas/reports";
import { SparkIcon, ArrowUpIcon } from "../../components/Icons";
import { PlannerQuestionCard } from "../plot-run/PlannerQuestionCard";
import { ReportEditStatus } from "./ReportEditStatus";
import type { ReportEditorTarget } from "./ReportEditorDialog";
import { reportItemNumbers } from "./reportPresentation";
import "./reportAssistant.css";

export type ReportComposeTarget = { prompt: string; key: number };
export function ReportAssistantPanel({
  document,
  section,
  block,
  composeTarget,
  open,
  onClose,
  onClearSelection,
  onSend,
  onShowReport,
  onEditDirectly,
  refresh,
}: {
  document: ReportDocument;
  section?: ReportSection;
  block?: ReportBlock;
  composeTarget: ReportComposeTarget | null;
  open: boolean;
  onClose: () => void;
  onClearSelection: () => void;
  onSend: (input: ReportMessageRequest) => Promise<boolean>;
  onShowReport: (document: ReportDocument) => void;
  onEditDirectly: (target: ReportEditorTarget) => void;
  refresh: () => Promise<unknown>;
}) {
  const isSlides = document.content.kind === "slides";
  const formatName = isSlides ? "Slides" : "Report";
  const noun = isSlides ? "presentation" : "report";
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const request = useRef<{
    fingerprint: string;
    input: ReportMessageRequest;
  } | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null),
    end = useRef<HTMLDivElement>(null);
  const figures = reportItemNumbers(document.content, "figure");
  const turns = [
    ...document.messages.map((message) => ({
      type: "message" as const,
      id: message.message_id,
      created: message.created_at,
      message,
    })),
    ...document.edits
      .filter((edit) => !edit.message_id && !edit.dismissed)
      .map((edit) => ({
        type: "edit" as const,
        id: edit.edit_id,
        created: edit.created_at,
        edit,
      })),
  ].sort((a, b) => a.created.localeCompare(b.created));
  const last = turns.at(-1);
  const lastStatus =
    last?.type === "message" ? last.message.status : last?.edit.status;
  useEffect(() => {
    if (composeTarget) {
      setDraft(composeTarget.prompt);
      setError(null);
      composer.current?.focus();
    }
  }, [composeTarget]);
  useEffect(() => {
    if (open) end.current?.scrollIntoView({ block: "nearest" });
  }, [turns.length, lastStatus, open]);
  function starter(text: string) {
    setDraft(text);
    composer.current?.focus();
  }
  async function submit() {
    if (!draft.trim() || inFlight.current) return;
    const message = draft.trim();
    const selection =
      section || block
        ? { section_id: section?.id, block_id: block?.id }
        : undefined;
    const fingerprint = JSON.stringify([message, selection]);
    if (request.current?.fingerprint !== fingerprint)
      request.current = {
        fingerprint,
        input: { request_id: createMutationId(), message, selection },
      };
    const pending = request.current;
    if (!pending) return;
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      if (await onSend(pending.input)) {
        setDraft((current) => (current.trim() === message ? "" : current));
        request.current = null;
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Your message could not be sent.",
      );
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  async function cancel(messageId: string) {
    try {
      onShowReport(
        await cancelReportMessage(
          document.project_id,
          document.report_id,
          messageId,
        ),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The request could not be stopped.",
      );
    }
  }
  return (
    <aside
      className="report-assistant"
      aria-label={`${formatName} assistant`}
      hidden={!open}
    >
      <header className="report-assistant-heading">
        <div className="report-assistant-mark">
          <SparkIcon />
        </div>
        <div>
          <strong>Research assistant</strong>
          <span>Write, plot, and organize your {noun}</span>
        </div>
        <button
          type="button"
          aria-label={`Hide ${formatName.toLowerCase()} assistant`}
          onClick={onClose}
        >
          ×
        </button>
      </header>
      {section || block ? (
        <div className="report-assistant-selection report-selection-hint">
          <span>
            Context:{" "}
            {block?.type === "figure"
              ? `Figure ${figures.get(block.id)}`
              : block?.type === "text"
                ? "Selected paragraph"
                : block?.type === "table"
                  ? "Selected table"
                  : section?.title}
          </span>
          <button
            type="button"
            aria-label="Clear selected content"
            onClick={onClearSelection}
          >
            ×
          </button>
        </div>
      ) : null}
      <div
        className="report-assistant-thread"
        role="log"
        aria-label={`${formatName} conversation`}
      >
        {!turns.length ? (
          <section className="report-assistant-welcome">
            <span className="section-kicker">
              Start with what you want to achieve.
            </span>
            <h2>What would you like to change?</h2>
            <p>
              Describe a figure, ask for{" "}
              {isSlides ? "a slide summary" : "a paragraph"}, or reorganize the{" "}
              {noun}. I’ll find the right place.
            </p>
            <div className="report-assistant-starters">
              <button
                type="button"
                onClick={() =>
                  starter(
                    isSlides
                      ? "Build a short presentation from the available figures and findings. Use clear slide titles and concise summaries."
                      : "Write an abstract summarizing the available report findings.",
                  )
                }
              >
                {isSlides ? "Build my presentation" : "Write an abstract"}{" "}
                <span>↗</span>
              </button>
              <button
                type="button"
                onClick={() =>
                  starter(
                    isSlides
                      ? "Create a slide comparing the groups, with a figure and a short summary."
                      : "Create a figure comparing the groups and place it in the results.",
                  )
                }
              >
                Add a supporting figure <span>↗</span>
              </button>
              <button
                type="button"
                onClick={() =>
                  starter(
                    isSlides
                      ? "Review the slide sequence and suggest a clearer story."
                      : "Review the report's structure and suggest a clearer order.",
                  )
                }
              >
                Improve the {noun}’s flow <span>↗</span>
              </button>
            </div>
          </section>
        ) : null}
        {turns.map((turn) => {
          const prompt =
            turn.type === "message" ? turn.message.prompt : turn.edit.prompt;
          return (
            <div className="report-assistant-turn" key={turn.id}>
              <article className="conversation-message message-user">
                <span className="message-author">You</span>
                <div className="message-content">
                  <Markdown disallowedElements={["img"]}>
                    {prompt || "Apply the selected figure parameters."}
                  </Markdown>
                </div>
              </article>
              {turn.type === "edit" ? (
                turn.edit.status === "completed" ? (
                  <Reply
                    text={turn.edit.response_text ?? `Updated the ${noun}.`}
                  />
                ) : (
                  <ReportEditStatus
                    edit={turn.edit}
                    projectId={document.project_id}
                    refresh={refresh}
                    showPrompt={false}
                    onCancel={async () =>
                      onShowReport(
                        await cancelReportEdit(
                          document.project_id,
                          document.report_id,
                          turn.edit.edit_id,
                        ),
                      )
                    }
                    onRetry={() => starter(prompt)}
                  />
                )
              ) : (
                <>
                  {turn.message.response_text ? (
                    <Reply text={turn.message.response_text} />
                  ) : null}
                  {turn.message.question ? (
                    <PlannerQuestionCard
                      key={turn.message.question.interaction_id}
                      question={turn.message.question}
                      onAnswer={async (answers) => {
                        onShowReport(
                          await answerReportMessage(
                            document.project_id,
                            document.report_id,
                            turn.message.message_id,
                            turn.message.question!.interaction_id,
                            answers,
                          ),
                        );
                        return true;
                      }}
                      onCancel={() => cancel(turn.message.message_id)}
                    />
                  ) : null}
                  {turn.message.active_edit_id &&
                  document.edits.find(
                    (edit) => edit.edit_id === turn.message.active_edit_id,
                  ) ? (
                    <ReportEditStatus
                      edit={document.edits.find(
                        (edit) => edit.edit_id === turn.message.active_edit_id,
                      )!}
                      projectId={document.project_id}
                      refresh={refresh}
                      showPrompt={false}
                      onCancel={() => cancel(turn.message.message_id)}
                      onRetry={() => starter(prompt)}
                    />
                  ) : turn.message.status === "running" ? (
                    <div className="report-message-working" role="status">
                      <span className="report-spinner" />
                      {turn.message.phase === "planning"
                        ? "Finding the right action and placement…"
                        : `Updating the ${noun}…`}
                    </div>
                  ) : null}
                  {turn.message.status === "failed" ||
                  turn.message.status === "cancelled" ? (
                    <div
                      className="report-edit-status"
                      data-status={turn.message.status}
                    >
                      <p>{turn.message.error ?? "Request cancelled."}</p>
                      {turn.message.completed_actions.length ? (
                        <details>
                          <summary>Changes already saved</summary>
                          <ul>
                            {turn.message.completed_actions.map((action, i) => (
                              <li key={i}>{action}</li>
                            ))}
                          </ul>
                        </details>
                      ) : null}
                      <button type="button" onClick={() => starter(prompt)}>
                        Edit and retry
                      </button>
                    </div>
                  ) : null}
                  {turn.message.status === "running" &&
                  !turn.message.active_edit_id ? (
                    <button
                      type="button"
                      className="report-text-button"
                      onClick={() => void cancel(turn.message.message_id)}
                    >
                      Cancel request
                    </button>
                  ) : null}
                </>
              )}
            </div>
          );
        })}
        <div ref={end} />
      </div>
      <form
        className="report-assistant-compose"
        aria-label={`${formatName} assistant composer`}
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <textarea
          ref={composer}
          aria-label={`Message the ${formatName.toLowerCase()} assistant`}
          value={draft}
          maxLength={8000}
          rows={3}
          placeholder="Ask a question or describe a change…"
          disabled={busy}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault();
              void submit();
            }
          }}
        />
        {error ? (
          <p className="report-error" role="alert">
            {error}
          </p>
        ) : null}
        <footer>
          <div>
            {block?.type === "figure" && section ? (
              <button
                type="button"
                className="report-manual-edit"
                onClick={() =>
                  onEditDirectly({
                    kind: "figure",
                    topicId: section.id,
                    blockId: block.id,
                  })
                }
              >
                Figure controls
              </button>
            ) : (
              <span>Selection is optional · Shift + Enter for a new line</span>
            )}
          </div>
          <button
            type="submit"
            className="report-assistant-send"
            disabled={busy || !draft.trim()}
          >
            {busy ? "Sending…" : "Send"}
            <ArrowUpIcon />
          </button>
        </footer>
      </form>
    </aside>
  );
}
function Reply({ text }: { text: string }) {
  return (
    <article className="conversation-message message-assistant">
      <span className="message-author">Assistant</span>
      <div className="message-content">
        <Markdown disallowedElements={["img"]}>{text}</Markdown>
      </div>
    </article>
  );
}
