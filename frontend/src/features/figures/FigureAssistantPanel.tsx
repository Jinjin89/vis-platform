import { useEffect, useRef, useState, type RefObject } from "react";
import Markdown from "react-markdown";
import { createMutationId } from "../../api/client";
import {
  answerFigureMessage,
  cancelFigureMessage,
} from "../../api/figureCompositions";
import type {
  FigureDocument,
  FigureMessage,
  PanelProgress,
} from "../../api/schemas/figureCompositions";
import { reportEditActive } from "../../api/schemas/reports";
import { PlannerQuestionCard } from "../plot-run/PlannerQuestionCard";
import { ReportEditStatus } from "../reports/ReportEditStatus";

type MessageInput = {
  request_id: string;
  message: string;
  selection?: { panel_ids: string[] };
};

const PHASES: Record<FigureMessage["phase"], string> = {
  planning: "Planning the figure…",
  editing: "Updating the figure…",
  plotting: "Creating the plot with the plotting agent…",
  arranging: "Arranging panels and rendering plots at size…",
  reviewing: "Checking the layout…",
  finished: "",
};

const PROGRESS: Record<PanelProgress["status"], string> = {
  waiting: "waiting",
  plotting: "creating the plot…",
  completed: "done",
  failed: "could not be created",
};

const STARTERS = [
  "Build a figure from the data that summarises the main result in four panels.",
  "Arrange the panels so the main result leads the figure.",
  "Write a legend entry for every panel.",
];

function MessageView({
  message,
  document,
  onShow,
  refresh,
}: {
  message: FigureMessage;
  document: FigureDocument;
  onShow: (next: FigureDocument) => void;
  refresh: () => Promise<unknown>;
}) {
  const [error, setError] = useState<string | null>(null);
  const active = reportEditActive(message);
  async function perform(action: () => Promise<FigureDocument>) {
    setError(null);
    try {
      onShow(await action());
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "The request failed.",
      );
    }
  }
  const cancel = () =>
    perform(() =>
      cancelFigureMessage(
        document.project_id,
        document.composition_id,
        message.message_id,
      ),
    );
  return (
    <article className="composition-message" data-status={message.status}>
      <p className="composition-message-user">{message.prompt}</p>
      <div className="composition-message-reply">
        {message.response_text ? (
          <Markdown>{message.response_text}</Markdown>
        ) : null}
        {message.panels.length && active ? (
          <ol className="composition-message-panels" aria-label="Panels">
            {message.panels.map((item) => (
              <li key={item.panel_id} data-status={item.status}>
                Panel{" "}
                {document.panels[item.panel_id]?.label ?? `“${item.panel_id}”`}{" "}
                · {PROGRESS[item.status]}
              </li>
            ))}
          </ol>
        ) : null}
        {message.completed_actions.length ? (
          <ul aria-label="Completed changes">
            {message.completed_actions.map((action, index) => (
              <li key={index}>{action}</li>
            ))}
          </ul>
        ) : null}
        {message.question && message.status === "awaiting_input" ? (
          <PlannerQuestionCard
            question={message.question}
            onAnswer={async (answers) => {
              try {
                onShow(
                  await answerFigureMessage(
                    document.project_id,
                    document.composition_id,
                    message.message_id,
                    message.question!.interaction_id,
                    answers,
                  ),
                );
                return true;
              } catch (reason) {
                setError(
                  reason instanceof Error
                    ? reason.message
                    : "The answer was not accepted.",
                );
                return false;
              }
            }}
          />
        ) : null}
        {message.active_step ? (
          <ReportEditStatus
            edit={message.active_step}
            projectId={document.project_id}
            refresh={refresh}
            onCancel={cancel}
            onRetry={() => undefined}
            showPrompt={false}
          />
        ) : active && !message.question ? (
          <p className="composition-message-progress" role="status">
            <span className="report-spinner" /> {PHASES[message.phase]}
            <button type="button" onClick={() => void cancel()}>
              Stop
            </button>
          </p>
        ) : null}
        {message.status === "cancelled" ? <p>Stopped.</p> : null}
        {message.error ? (
          <p className="report-error" role="alert">
            {message.error}
          </p>
        ) : null}
        {error ? (
          <p className="report-error" role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </article>
  );
}

export function FigureAssistantPanel({
  document,
  selected,
  composer,
  initialDraft = "",
  onSend,
  onShow,
  onClearSelection,
  refresh,
}: {
  document: FigureDocument;
  selected: string[];
  composer: RefObject<HTMLTextAreaElement | null>;
  initialDraft?: string;
  onSend: (input: MessageInput) => Promise<boolean>;
  onShow: (next: FigureDocument) => void;
  onClearSelection: () => void;
  refresh: () => Promise<unknown>;
}) {
  const [draft, setDraft] = useState(initialDraft);
  const [busy, setBusy] = useState(false);
  const pending = useRef<{ fingerprint: string; input: MessageInput } | null>(
    null,
  );
  const end = useRef<HTMLDivElement>(null);
  const messages = document.messages;
  const last = messages.at(-1);
  const working = messages.some(reportEditActive);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest" });
  }, [messages.length, last?.status, last?.completed_actions.length]);
  const labels = selected.map((id) => document.panels[id]?.label ?? `“${id}”`);
  async function submit() {
    const message = draft.trim();
    if (!message || busy || working) return;
    const selection = selected.length ? { panel_ids: selected } : undefined;
    const fingerprint = JSON.stringify([message, selection]);
    // A retried submission keeps its request ID, so it cannot run twice.
    if (pending.current?.fingerprint !== fingerprint)
      pending.current = {
        fingerprint,
        input: { request_id: createMutationId(), message, selection },
      };
    setBusy(true);
    try {
      if (await onSend(pending.current.input)) {
        setDraft((current) => (current.trim() === message ? "" : current));
        pending.current = null;
      }
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="composition-assistant" aria-label="Figure assistant">
      <div
        className="composition-conversation"
        role="log"
        aria-label="Figure conversation"
      >
        {messages.length ? (
          messages.map((message) => (
            <MessageView
              key={message.message_id}
              message={message}
              document={document}
              onShow={onShow}
              refresh={refresh}
            />
          ))
        ) : (
          <section className="composition-assistant-welcome">
            <span className="composition-kicker">Figure assistant</span>
            <h2>Describe the figure you need.</h2>
            <p>
              The assistant plans the panels and lays out the page, then creates
              each plot from the figure’s data with the plotting agent, one at a
              time. It also arranges existing panels and writes the legend. You
              can adjust everything afterwards.
            </p>
            {STARTERS.map((text) => (
              <button
                type="button"
                key={text}
                onClick={() => {
                  setDraft(text);
                  composer.current?.focus();
                }}
              >
                {text}
              </button>
            ))}
          </section>
        )}
        <div ref={end} />
      </div>
      <form
        className="composition-composer"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        {selected.length ? (
          <p className="composition-selection-hint">
            About panel{selected.length > 1 ? "s" : ""} {labels.join(", ")}
            <button
              type="button"
              aria-label="Clear the panel selection"
              onClick={onClearSelection}
            >
              ×
            </button>
          </p>
        ) : null}
        <textarea
          ref={composer}
          value={draft}
          rows={3}
          maxLength={8000}
          aria-label="Message the figure assistant"
          placeholder="For example: a figure on treatment response with growth curves, final volumes, and marker expression."
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submit();
            }
          }}
        />
        <button
          type="submit"
          className="composition-primary"
          disabled={busy || working || !draft.trim()}
        >
          Send
        </button>
      </form>
    </div>
  );
}
