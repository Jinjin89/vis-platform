import type { ReactNode } from "react";
import type { AnalysisResult } from "../../api/schemas/datasets";
import { AnalysisResultCard } from "../datasets/AnalysisResultCard";
import { useEffect, useRef, useState } from "react";
import type {
  FormEvent,
  KeyboardEvent,
  ClipboardEvent,
  DragEvent,
} from "react";
import type { ReferenceImage } from "../../api/schemas/referenceImages";
import { ReferenceImages } from "../plot-references/ReferenceImages";
import {
  useReferenceImages,
  type UploadReference,
} from "../plot-references/useReferenceImages";
import Markdown from "react-markdown";

import type { QuestionAnswer } from "../../api/client";
import type { PlotRunSnapshot } from "../../api/schemas/plotRun";
import type {
  PlannerAnswer,
  PlannerQuestions,
} from "../../api/schemas/planner";
import {
  ArrowUpIcon,
  CheckIcon,
  SparkIcon,
  ImagePlusIcon,
} from "../../components/Icons";
import { AgentActivity } from "./AgentActivity";
import { PlannerQuestionCard } from "./PlannerQuestionCard";
import type {
  AssistantActivityTurn,
  ConversationMessage,
  DeveloperTraceTarget,
  PendingPlannerQuestion,
} from "./types";

type ConversationPanelProps = {
  projectId?: string | null;
  onUploadReference?: UploadReference;
  onDeleteReference?: (image: ReferenceImage) => Promise<void>;
  dataSelector?: ReactNode;
  dataSelectionLabel?: string;
  draftRequest?: { text: string; key: number };
  onUseResult?: (result: AnalysisResult) => void;
  committedSnapshot: PlotRunSnapshot | null;
  activeSnapshot: PlotRunSnapshot | null;
  messages: ConversationMessage[];
  traceTargets: DeveloperTraceTarget[];
  progressMessage: string;
  progressValue: number;
  isRunning: boolean;
  interactionBusy: boolean;
  interactionError: string | null;
  activities?: AssistantActivityTurn[];
  plannerQuestion?: PendingPlannerQuestion | null;
  plannerConnectionError?: string | null;
  onPlannerAnswer?: (answers: PlannerAnswer[]) => Promise<boolean>;
  onPlannerCancel?: () => Promise<void>;
  onReconnect?: () => void;
  onCancel?: () => Promise<void>;
  onSubmit: (text: string, images?: ReferenceImage[]) => Promise<boolean>;
  onAnswerQuestion: (
    questionId: string,
    answer: QuestionAnswer,
  ) => Promise<void>;
  onDecideApproval: (
    approvalId: string,
    decision: "approve" | "reject",
  ) => Promise<void>;
};
const STARTERS = [
  {
    label: "Compare distributions",
    prompt:
      "Use demonstration data to create a violin plot comparing treatment groups",
  },
  {
    label: "Explore survival",
    prompt: "Use demonstration data to show a survival curve by cohort",
  },
  {
    label: "Reveal a relationship",
    prompt:
      "Use demonstration data to plot response versus dose by study group",
  },
];

export function ConversationPanel({
  projectId,
  onUploadReference,
  onDeleteReference,
  dataSelector,
  dataSelectionLabel,
  draftRequest,
  onUseResult,
  committedSnapshot,
  activeSnapshot,
  messages,
  progressMessage,
  isRunning,
  interactionBusy,
  interactionError,
  activities = [],
  plannerQuestion,
  plannerConnectionError,
  onPlannerAnswer,
  onPlannerCancel,
  onReconnect,
  onCancel,
  onSubmit,
  onAnswerQuestion,
  onDecideApproval,
}: ConversationPanelProps) {
  const [draft, setDraft] = useState("");
  const references = useReferenceImages(
    onUploadReference,
    onDeleteReference,
    projectId,
  );
  const imageInput = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);
  const composer = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (draftRequest) {
      setDraft(draftRequest.text);
      composer.current?.focus();
    }
  }, [draftRequest]);
  const question = activeSnapshot?.pending_question;
  const approval = activeSnapshot?.pending_approval;
  const result = committedSnapshot?.result;
  const waiting = Boolean(question || approval || plannerQuestion);
  const unattached = activities.filter(
    (turn) =>
      !messages.some(
        (message) =>
          message.role === "assistant" && message.turnId === turn.turnId,
      ),
  );
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [
    messages.length,
    question?.question_id,
    plannerQuestion?.question.interaction_id,
  ]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (
      (!text && !references.ready.length) ||
      isRunning ||
      waiting ||
      references.blocked
    )
      return;
    const accepted = references.ready.length
      ? await onSubmit(text, references.ready)
      : await onSubmit(text);
    if (accepted) {
      setDraft("");
      references.commit();
    }
  }
  function paste(event: ClipboardEvent<HTMLTextAreaElement>) {
    if (!onUploadReference || isRunning || waiting) return;
    const files = Array.from(event.clipboardData.items)
      .filter((item) => item.kind === "file")
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null);
    if (!files.length) return;
    event.preventDefault();
    const pasted = event.clipboardData.getData("text/plain");
    if (pasted) {
      const start = event.currentTarget.selectionStart;
      const finish = event.currentTarget.selectionEnd;
      setDraft((value) => value.slice(0, start) + pasted + value.slice(finish));
      requestAnimationFrame(() =>
        composer.current?.setSelectionRange(
          start + pasted.length,
          start + pasted.length,
        ),
      );
    }
    references.add(files);
  }
  function fileDrag(event: DragEvent) {
    return Array.from(event.dataTransfer.types).includes("Files");
  }
  function drop(event: DragEvent) {
    if (!fileDrag(event) || !onUploadReference) return;
    event.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    if (!isRunning && !waiting)
      references.add(Array.from(event.dataTransfer.files));
  }
  function keyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }
  const legacyQuestion: PlannerQuestions | null = question
    ? {
        interaction_id: question.question_id,
        questions: [
          {
            question_id: question.question_id,
            header: "Figure choice",
            prompt: question.prompt,
            reason: question.reason,
            selection: "single",
            choices: question.choices.map((choice) => ({
              ...choice,
              description: choice.description ?? "",
              recommended: false,
            })),
            allow_free_text: question.allow_free_text,
          },
        ],
      }
    : null;
  return (
    <aside className="conversation-panel" aria-label="Plot conversation">
      <div className="conversation-context">
        {dataSelector ? (
          <div className="conversation-data">{dataSelector}</div>
        ) : null}
        <header className="conversation-header">
          <div className="assistant-identity">
            <span className="assistant-mark">
              <SparkIcon />
            </span>
            <div>
              <strong>Studio assistant</strong>
              <span>
                {isRunning
                  ? "Working on your request"
                  : waiting
                    ? "Your input is needed"
                    : "Ready to help"}
              </span>
            </div>
          </div>
          <span className="workspace-mode-badge">
            {result?.execution_mode === "demo" || result?.contains_demo_data
              ? "Demo"
              : result?.execution_mode === "r"
                ? "Connected"
                : (dataSelectionLabel ?? "No dataset")}
          </span>
        </header>
      </div>
      <div className="conversation-thread" role="log" aria-label="Conversation">
        {!messages.length && !isRunning ? (
          <section className="assistant-welcome">
            <span className="section-kicker">Start with an idea</span>
            <h2>What would you like to explore?</h2>
            <p>
              Ask a question, plan a figure, or try an illustrative example.
            </p>
            <div className="starter-prompts" aria-label="Example requests">
              {STARTERS.map((starter) => (
                <button
                  key={starter.label}
                  type="button"
                  onClick={() => {
                    setDraft(starter.prompt);
                    composer.current?.focus();
                  }}
                >
                  <strong>{starter.label}</strong>
                  <span>{starter.prompt}</span>
                  <span aria-hidden="true">↗</span>
                </button>
              ))}
            </div>
          </section>
        ) : null}
        {messages.map((message) => (
          <article
            className={`conversation-message message-${message.role}${message.tone === "error" ? " message-error" : ""}`}
            key={message.id}
            role={message.tone === "error" ? "alert" : undefined}
          >
            {message.role === "assistant" && message.turnId
              ? activities
                  .filter((turn) => turn.turnId === message.turnId)
                  .map((turn) => (
                    <AgentActivity key={turn.turnId} turn={turn} />
                  ))
              : null}
            <span className="message-author">
              {message.role === "user" ? "You" : "Assistant"}
            </span>
            <div className="message-content">
              <ReferenceImages images={message.referenceImages} />
              <Markdown disallowedElements={["img"]}>
                {message.content}
              </Markdown>
            </div>
            {message.analysisResults?.map((analysis) => (
              <AnalysisResultCard
                key={analysis.result_id}
                result={analysis}
                onUse={onUseResult}
                disabled={isRunning}
              />
            ))}
          </article>
        ))}
        {unattached.map((turn) => (
          <AgentActivity key={turn.turnId} turn={turn} />
        ))}
        {isRunning &&
        !unattached.some(
          (turn) => turn.status === "running" || turn.runStatus === "running",
        ) ? (
          <div className="inline-working" role="status">
            <span className="activity-spinner" aria-hidden="true" />
            {progressMessage}
          </div>
        ) : null}
        {plannerConnectionError ? (
          <div className="connection-notice" role="alert">
            <p>{plannerConnectionError}</p>
            <button type="button" onClick={onReconnect}>
              Reconnect
            </button>
          </div>
        ) : null}
        {plannerQuestion && onPlannerAnswer ? (
          <PlannerQuestionCard
            key={plannerQuestion.question.interaction_id}
            question={plannerQuestion.question}
            onAnswer={onPlannerAnswer}
            onCancel={onPlannerCancel}
            disabled={interactionBusy}
          />
        ) : null}
        {legacyQuestion && question ? (
          <PlannerQuestionCard
            key={question.question_id}
            question={legacyQuestion}
            disabled={interactionBusy}
            onAnswer={async (answers) => {
              const answer = answers[0]!;
              await onAnswerQuestion(
                question.question_id,
                answer.free_text
                  ? { freeText: answer.free_text }
                  : { choiceId: answer.choice_ids[0]! },
              );
              return true;
            }}
          />
        ) : null}
        {approval ? (
          <section
            className="planner-question"
            aria-label="Scientific decision"
          >
            <div className="question-meta">Scientific decision</div>
            <h3>{approval.summary}</h3>
            <p className="question-reason">{approval.scientific_effect}</p>
            <p className="question-reason">
              Your choice will be recorded with the figure.
            </p>
            <div className="question-actions">
              <button
                type="button"
                className="quiet-button"
                disabled={interactionBusy}
                onClick={() =>
                  void onDecideApproval(approval.approval_id, "reject")
                }
              >
                Keep data unchanged
              </button>
              <button
                type="button"
                className="primary-button"
                disabled={interactionBusy}
                onClick={() =>
                  void onDecideApproval(approval.approval_id, "approve")
                }
              >
                <CheckIcon />
                Approve change
              </button>
            </div>
          </section>
        ) : null}
        {interactionError ? (
          <p className="interaction-error" role="alert">
            {interactionError}
          </p>
        ) : null}
        <div ref={end} />
      </div>
      <form
        className="conversation-compose"
        onSubmit={(event) => void submit(event)}
      >
        <div
          className={`composer-surface${dragging ? " reference-dragging" : ""}`}
          onDrop={drop}
          onDragOver={(event) => {
            if (fileDrag(event) && onUploadReference) {
              event.preventDefault();
              event.dataTransfer.dropEffect = "copy";
            }
          }}
          onDragEnter={(event) => {
            if (
              fileDrag(event) &&
              onUploadReference &&
              !isRunning &&
              !waiting
            ) {
              event.preventDefault();
              dragDepth.current += 1;
              setDragging(true);
            }
          }}
          onDragLeave={(event) => {
            if (!fileDrag(event)) return;
            dragDepth.current = Math.max(0, dragDepth.current - 1);
            if (!dragDepth.current) setDragging(false);
          }}
        >
          <ReferenceImages
            drafts={references.items}
            onRemove={references.remove}
            onRetry={references.retry}
            disabled={isRunning || waiting}
          />
          <input
            ref={imageInput}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            multiple
            hidden
            aria-label="Choose plot reference images"
            onChange={(event) => {
              references.add(Array.from(event.currentTarget.files ?? []));
              event.currentTarget.value = "";
            }}
          />
          <textarea
            ref={composer}
            name="request"
            rows={2}
            aria-label="Describe the plot you want"
            placeholder={
              waiting
                ? "Answer the question above to continue…"
                : onUploadReference
                  ? "Describe a plot or paste a reference image…"
                  : "Ask a question or describe a change…"
            }
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={keyDown}
            onPaste={paste}
            disabled={isRunning || waiting}
          />
          {references.error ? (
            <p className="reference-upload-error" role="alert">
              {references.error}
            </p>
          ) : null}
          <div className="composer-footer">
            {onUploadReference ? (
              <button
                type="button"
                className="add-reference-image"
                disabled={isRunning || waiting}
                onClick={() => imageInput.current?.click()}
              >
                <ImagePlusIcon />
                Add image
              </button>
            ) : null}
            <span>
              {result
                ? "Current figure included"
                : onUploadReference
                  ? ""
                  : "Your conversation stays in context"}
            </span>
            {isRunning && onCancel ? (
              <button
                type="button"
                className="stop-assistant"
                aria-label="Stop current request"
                onClick={() => void onCancel()}
              >
                <span aria-hidden="true" />
                Stop
              </button>
            ) : (
              <button
                type="submit"
                aria-label="Send"
                disabled={
                  (!draft.trim() && !references.ready.length) ||
                  references.blocked ||
                  waiting ||
                  isRunning
                }
              >
                <ArrowUpIcon />
              </button>
            )}
          </div>
        </div>
        <p className="composer-disclaimer">
          {dragging
            ? "Drop plot images here"
            : "Enter to send · Paste or drop plot images"}
        </p>
      </form>
    </aside>
  );
}
