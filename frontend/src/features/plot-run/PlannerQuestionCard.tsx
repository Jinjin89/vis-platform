import { useId, useRef, useState } from "react";
import type {
  PlannerAnswer,
  PlannerQuestions,
} from "../../api/schemas/planner";

type Props = {
  question: PlannerQuestions;
  disabled?: boolean;
  onAnswer: (answers: PlannerAnswer[]) => Promise<boolean>;
  onCancel?: () => Promise<void>;
};
export function PlannerQuestionCard({
  question,
  disabled = false,
  onAnswer,
  onCancel,
}: Props) {
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, PlannerAnswer>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inFlight = useRef(false);
  const id = useId();
  const current = question.questions[index]!;
  const answer = answers[current.question_id] ?? {
    question_id: current.question_id,
    choice_ids: [],
    free_text: "",
  };
  const valid =
    answer.choice_ids.length > 0 || Boolean(answer.free_text?.trim());
  function change(update: Partial<PlannerAnswer>) {
    setAnswers((existing) => ({
      ...existing,
      [current.question_id]: { ...answer, ...update },
    }));
    setError(null);
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid || disabled || inFlight.current) return;
    if (index < question.questions.length - 1) {
      setIndex(index + 1);
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      await onAnswer(
        question.questions.map((item) => ({
          ...answers[item.question_id]!,
          free_text: answers[item.question_id]?.free_text?.trim() || null,
        })),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Your answer could not be saved.",
      );
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  return (
    <form
      className="planner-question"
      aria-label="Question from the planner"
      onSubmit={(event) => void submit(event)}
    >
      <div className="question-meta">
        <span>{current.header}</span>
        <span>
          {index + 1} of {question.questions.length}
        </span>
      </div>
      <h3>{current.prompt}</h3>
      {current.reason ? (
        <p className="question-reason">{current.reason}</p>
      ) : null}
      <div className="question-options">
        {current.choices.map((choice) => (
          <label className="question-option" key={choice.choice_id}>
            <input
              name={`${id}-choice`}
              type={current.selection === "multiple" ? "checkbox" : "radio"}
              checked={answer.choice_ids.includes(choice.choice_id)}
              disabled={disabled || busy}
              onChange={() =>
                change({
                  choice_ids:
                    current.selection === "multiple"
                      ? answer.choice_ids.includes(choice.choice_id)
                        ? answer.choice_ids.filter(
                            (value) => value !== choice.choice_id,
                          )
                        : [...answer.choice_ids, choice.choice_id]
                      : [choice.choice_id],
                })
              }
            />
            <span>
              <strong>
                {choice.label}
                {choice.recommended ? (
                  <small className="recommended-choice">Recommended</small>
                ) : null}
              </strong>
              {choice.description ? <span>{choice.description}</span> : null}
            </span>
          </label>
        ))}
      </div>
      {current.allow_free_text ? (
        <label className="question-free-text" htmlFor={`${id}-text`}>
          {current.selection === "text"
            ? "Your answer"
            : "Or answer in your own words"}
          <input
            id={`${id}-text`}
            value={answer.free_text ?? ""}
            disabled={disabled || busy}
            onChange={(event) => change({ free_text: event.target.value })}
            placeholder="Add your answer…"
          />
        </label>
      ) : null}
      {error ? (
        <p role="alert" className="interaction-error">
          {error}
        </p>
      ) : null}
      <div className="question-actions">
        {index > 0 ? (
          <button
            type="button"
            className="quiet-button"
            onClick={() => setIndex(index - 1)}
            disabled={busy || disabled}
          >
            Back
          </button>
        ) : onCancel ? (
          <button
            type="button"
            className="quiet-button"
            onClick={() => void onCancel()}
            disabled={busy || disabled}
          >
            Cancel request
          </button>
        ) : (
          <span />
        )}
        <button
          type="submit"
          className="primary-button"
          disabled={!valid || busy || disabled}
        >
          {busy
            ? "Saving…"
            : index < question.questions.length - 1
              ? "Continue"
              : question.questions.length > 1
                ? "Confirm choices"
                : "Continue"}
        </button>
      </div>
    </form>
  );
}
