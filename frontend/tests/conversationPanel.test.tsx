import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import type { PlotRunSnapshot } from "../src/api/schemas/plotRun";
import { ConversationPanel } from "../src/features/plot-run/ConversationPanel";

const waitingSnapshot: PlotRunSnapshot = {
  schema_version: "1.0",
  run_id: "run_1",
  project_id: "project_1",
  status: "awaiting_input",
  stage: "selecting_data",
  created_at: "2026-09-03T00:00:00Z",
  updated_at: "2026-09-03T00:00:01Z",
  result: null,
  progress: { progress: 20, message: "Finding relevant data" },
  pending_question: {
    question_id: "question_1",
    prompt: "Which survival outcome should be shown?",
    reason: "Two valid outcomes are available.",
    choices: [
      { choice_id: "os", label: "Overall survival" },
      { choice_id: "pfs", label: "Progression-free survival" },
    ],
    allow_free_text: false,
  },
  pending_approval: null,
  failure: null,
};

test("renders and answers an essential question", async () => {
  const answer = vi.fn(async () => undefined);
  const user = userEvent.setup();
  render(
    <ConversationPanel
      committedSnapshot={null}
      activeSnapshot={waitingSnapshot}
      messages={[
        {
          id: "message_1",
          role: "user",
          content: "Show survival differences",
        },
      ]}
      traceTargets={[]}
      progressMessage="Finding relevant data"
      progressValue={20}
      isRunning={false}
      interactionBusy={false}
      interactionError={null}
      onSubmit={async () => true}
      onAnswerQuestion={answer}
      onDecideApproval={async () => undefined}
    />,
  );

  await user.click(screen.getByRole("radio", { name: "Overall survival" }));

  expect(answer).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Continue" }));

  expect(answer).toHaveBeenCalledWith("question_1", {
    choiceId: "os",
  });
  expect(
    screen.getByRole("textbox", { name: "Describe the plot you want" }),
  ).toBeDisabled();
});

test("submits a trimmed free-text answer when the question allows it", async () => {
  const answer = vi.fn(async () => undefined);
  const user = userEvent.setup();
  const freeTextSnapshot: PlotRunSnapshot = {
    ...waitingSnapshot,
    pending_question: {
      ...waitingSnapshot.pending_question!,
      allow_free_text: true,
      choices: [
        {
          choice_id: "custom",
          label: "Another endpoint",
          description: "Choose this only when neither listed endpoint applies.",
        },
      ],
    },
  };

  render(
    <ConversationPanel
      committedSnapshot={null}
      activeSnapshot={freeTextSnapshot}
      messages={[]}
      traceTargets={[]}
      progressMessage="Waiting for your answer"
      progressValue={20}
      isRunning={false}
      interactionBusy={false}
      interactionError={null}
      onSubmit={async () => true}
      onAnswerQuestion={answer}
      onDecideApproval={async () => undefined}
    />,
  );

  expect(
    screen.getByText("Choose this only when neither listed endpoint applies."),
  ).toBeInTheDocument();

  const input = screen.getByRole("textbox", {
    name: "Or answer in your own words",
  });
  await user.type(input, "  Disease-specific survival  ");
  await user.click(screen.getByRole("button", { name: "Continue" }));

  expect(answer).toHaveBeenCalledTimes(1);
  expect(answer).toHaveBeenCalledWith("question_1", {
    freeText: "Disease-specific survival",
  });
});

test("shows agent activity inline while preserving the conversation input", async () => {
  const user = userEvent.setup();
  render(
    <ConversationPanel
      committedSnapshot={null}
      activeSnapshot={null}
      messages={[]}
      traceTargets={[]}
      activities={[
        {
          turnId: "turn_1",
          request: "Explain a plot",
          status: "completed",
          traceHref: "/api/v1/assistant-turns/turn_1/trace",
          activity: [
            {
              sequence: 1,
              step_id: "intent",
              kind: "agent",
              actor: "Intent planner",
              label: "Understand and plan",
              status: "completed",
              summary: "Answer using the current figure context.",
              occurred_at: "2026-09-10T00:00:00Z",
            },
          ],
        },
      ]}
      progressMessage="Ready"
      progressValue={0}
      isRunning={false}
      interactionBusy={false}
      interactionError={null}
      onSubmit={async () => true}
      onAnswerQuestion={async () => undefined}
      onDecideApproval={async () => undefined}
    />,
  );

  expect(
    screen.queryByRole("button", { name: "Open diagnostics" }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByText(/Activity · 1/));
  expect(screen.getByText("Intent planner")).toBeVisible();
  expect(
    screen.getByRole("textbox", { name: "Describe the plot you want" }),
  ).toBeVisible();
  await user.click(screen.getByText("Developer diagnostics"));

  expect(
    screen.getByText("Private model reasoning is not exposed.", {
      exact: false,
    }),
  ).toBeInTheDocument();
  expect(screen.getByLabelText("Developer trace token")).toBeInTheDocument();
});
