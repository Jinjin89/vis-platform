import { useState } from "react";
import {
  answerPlanner,
  answerQuestion,
  decideApproval,
} from "../../api/client";
import { plannerQuestionsSchema } from "../../api/schemas/planner";
import {
  reportEditActive,
  type PlotRequestProgress,
} from "../../api/schemas/reports";
import { PlannerQuestionCard } from "../plot-run/PlannerQuestionCard";

export function ReportEditStatus({
  edit,
  projectId,
  refresh,
  onCancel,
  onRetry,
  showPrompt = true,
}: {
  edit: PlotRequestProgress;
  projectId: string;
  refresh: () => Promise<unknown>;
  onCancel: () => Promise<unknown>;
  onRetry: () => void;
  showPrompt?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const planner = edit.assistant_state?.question
    ? plannerQuestionsSchema.parse(edit.assistant_state.question)
    : null;
  const question = edit.run_state?.pending_question;
  const approval = edit.run_state?.pending_approval;
  async function perform(action: () => Promise<unknown>) {
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
    <section
      className="report-edit-status"
      data-status={edit.status}
      aria-label={`${edit.kind} edit status`}
    >
      <div className="report-edit-status-heading">
        <span className={reportEditActive(edit) ? "report-spinner" : ""}>
          {reportEditActive(edit) ? "" : "!"}
        </span>
        <strong>
          {edit.status === "running"
            ? edit.kind === "discussion"
              ? "Thinking…"
              : edit.block_id
                ? "Refining content…"
                : `Creating ${edit.kind}…`
            : edit.status === "awaiting_input"
              ? "One detail before continuing"
              : edit.status === "awaiting_approval"
                ? "Review this change"
                : edit.status === "cancelled"
                  ? "Request cancelled"
                  : "This edit needs attention"}
        </strong>
      </div>
      <p>
        {edit.error ??
          edit.run_state?.progress?.message ??
          (showPrompt ? edit.prompt : null)}
      </p>
      {planner && edit.assistant ? (
        <PlannerQuestionCard
          question={planner}
          disabled={busy}
          onAnswer={async (answers) => {
            await answerPlanner(
              edit.assistant!.turn_id,
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
          <div className="report-question-options">
            {question.choices.map((choice) => (
              <button
                type="button"
                key={choice.choice_id}
                disabled={busy}
                onClick={() =>
                  void perform(() =>
                    answerQuestion(edit.run!.run_id, question.question_id, {
                      choiceId: choice.choice_id,
                    }),
                  )
                }
              >
                {choice.label}
              </button>
            ))}
          </div>
          {question.allow_free_text ? (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (answer.trim())
                  void perform(() =>
                    answerQuestion(edit.run!.run_id, question.question_id, {
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
                  edit.run!.run_id,
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
                  edit.run!.run_id,
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
      {error ? (
        <p role="alert" className="report-error">
          {error}
        </p>
      ) : null}
      <footer>
        {!reportEditActive(edit) ? (
          <button type="button" onClick={onRetry}>
            Edit instructions and retry
          </button>
        ) : null}
        <button
          type="button"
          disabled={busy}
          onClick={() => void perform(onCancel)}
        >
          {reportEditActive(edit) ? "Cancel request" : "Dismiss"}
        </button>
      </footer>
    </section>
  );
}
