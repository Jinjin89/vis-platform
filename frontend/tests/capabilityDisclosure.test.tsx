import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import { ConversationPanel } from "../src/features/plot-run/ConversationPanel";

const props = {
  committedSnapshot: null,
  activeSnapshot: null,
  messages: [],
  traceTargets: [],
  progressMessage: "Ready",
  progressValue: 0,
  isRunning: false,
  interactionBusy: false,
  interactionError: null,
  onSubmit: async () => true,
  onAnswerQuestion: async () => undefined,
  onDecideApproval: async () => undefined,
};

test("example starters explicitly request demonstration data", async () => {
  const user = userEvent.setup();
  const onSubmit = vi.fn(async () => true);
  render(<ConversationPanel {...props} onSubmit={onSubmit} />);

  expect(screen.getByText("No dataset")).toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: /Compare distributions/ }),
  );
  expect(
    screen.getByRole("textbox", { name: "Describe the plot you want" }),
  ).toHaveValue(
    "Use demonstration data to create a violin plot comparing treatment groups",
  );
  await user.click(screen.getByRole("button", { name: "Send" }));
  expect(onSubmit).toHaveBeenCalledWith(
    "Use demonstration data to create a violin plot comparing treatment groups",
  );
});

test("conversation does not repeatedly push the demo workflow", () => {
  render(
    <ConversationPanel
      {...props}
      messages={[
        {
          id: "message_1",
          role: "user",
          content: "Explain a confidence interval",
        },
        {
          id: "message_2",
          role: "assistant",
          content: "It describes uncertainty in an estimate.",
        },
      ]}
    />,
  );
  expect(
    screen.getByText("It describes uncertainty in an estimate."),
  ).toBeInTheDocument();
  expect(
    screen.queryByLabelText("Workspace capability"),
  ).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Plot starters")).not.toBeInTheDocument();
  expect(screen.getByRole("textbox")).toHaveAttribute(
    "placeholder",
    "Ask a question or describe a change…",
  );
});
