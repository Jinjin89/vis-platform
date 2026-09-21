import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import type { PlannerQuestions } from "../src/api/schemas/planner";
import { PlannerQuestionCard } from "../src/features/plot-run/PlannerQuestionCard";

const question: PlannerQuestions = {
  interaction_id: "interaction_1",
  questions: [
    {
      question_id: "goal",
      header: "Comparison",
      prompt: "What should the comparison emphasize?",
      reason: "Choose the information that matters.",
      selection: "single",
      allow_free_text: true,
      choices: [
        {
          choice_id: "distribution",
          label: "Distribution",
          description: "Show the spread.",
          recommended: true,
        },
        {
          choice_id: "mean",
          label: "Means",
          description: "Show averages.",
          recommended: false,
        },
      ],
    },
    {
      question_id: "details",
      header: "Details",
      prompt: "Which details should be shown?",
      reason: "Choose one or more.",
      selection: "multiple",
      allow_free_text: true,
      choices: [
        {
          choice_id: "points",
          label: "Observations",
          description: "Show individual values.",
          recommended: false,
        },
        {
          choice_id: "box",
          label: "Box summary",
          description: "Show the median.",
          recommended: false,
        },
      ],
    },
  ],
};

test("recommended choices require an explicit answer and grouped questions submit together", async () => {
  const user = userEvent.setup();
  const answer = vi.fn(async () => true);
  render(<PlannerQuestionCard question={question} onAnswer={answer} />);
  expect(screen.getByRole("radio", { name: /Distribution/ })).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  await user.click(screen.getByRole("radio", { name: /Distribution/ }));
  expect(answer).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("checkbox", { name: /Observations/ }));
  await user.click(screen.getByRole("checkbox", { name: /Box summary/ }));
  await user.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByRole("radio", { name: /Distribution/ })).toBeChecked();
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: "Confirm choices" }));
  expect(answer).toHaveBeenCalledWith([
    { question_id: "goal", choice_ids: ["distribution"], free_text: null },
    { question_id: "details", choice_ids: ["points", "box"], free_text: null },
  ]);
});

test("a failed answer preserves the selection and allows a retry", async () => {
  const user = userEvent.setup();
  const answer = vi
    .fn()
    .mockRejectedValueOnce(new Error("Unable to save the answer"))
    .mockResolvedValue(true);
  render(
    <PlannerQuestionCard
      question={{ ...question, questions: [question.questions[0]!] }}
      onAnswer={answer}
    />,
  );
  await user.type(
    screen.getByRole("textbox", { name: "Or answer in your own words" }),
    "  Show raw observations  ",
  );
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Unable to save the answer",
  );
  expect(screen.getByRole("textbox")).toHaveValue("  Show raw observations  ");
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(answer).toHaveBeenLastCalledWith([
    { question_id: "goal", choice_ids: [], free_text: "Show raw observations" },
  ]);
});
