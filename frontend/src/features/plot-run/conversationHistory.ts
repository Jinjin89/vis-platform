import type { AnalysisResult } from "../../api/schemas/datasets";
import type {
  PlannerAnswer,
  PlannerQuestions,
} from "../../api/schemas/planner";
import type {
  AssistantTurnAccepted,
  PlotRunAccepted,
  PlotRunSnapshot,
} from "../../api/schemas/plotRun";
import type { WorkspaceSessionDocument } from "../../api/schemas/workspaceSessions";
import type {
  AssistantActivityTurn,
  ConversationMessage,
  DeveloperTraceTarget,
} from "./types";

const FINISHED = new Set(["completed", "failed", "cancelled"]);

type RunMessage = {
  content: string;
  tone: "default" | "error";
  analysisResults?: AnalysisResult[];
};

/** What the conversation says when a plot or analysis run ends. */
export function runMessage(snapshot: PlotRunSnapshot): RunMessage | null {
  if (snapshot.status === "completed" && snapshot.result != null)
    return {
      content:
        snapshot.result.execution_mode === "demo"
          ? "The demonstration figure is ready. Fine-tune it below or export the figure."
          : "Your figure is ready. Its data, analysis, and parameters are saved with this version.",
      tone: "default",
    };
  if (snapshot.status === "completed" && snapshot.analysis_results?.length)
    return {
      content:
        "Your analysis is saved. You can inspect its outputs or use them in a figure.",
      tone: "default",
      analysisResults: snapshot.analysis_results,
    };
  if (snapshot.status === "failed")
    return {
      content:
        (snapshot.failure?.message ?? "The figure run failed.") +
        (snapshot.analysis_results?.length
          ? " Your completed analysis is saved below."
          : ""),
      tone: "error",
      analysisResults: snapshot.analysis_results,
    };
  if (snapshot.status === "cancelled")
    return {
      content: "I stopped this run. Your last saved figure is unchanged.",
      tone: "default",
    };
  return null;
}

/** The question and the answer as they read in the conversation. */
export function answeredQuestions(
  question: PlannerQuestions,
  answers: PlannerAnswer[],
): { prompt: string; answer: string } {
  return {
    prompt: question.questions.map((item) => item.prompt).join(" "),
    answer: question.questions
      .map((item) => {
        const answer = answers.find(
          (value) => value.question_id === item.question_id,
        );
        return (
          answer?.free_text ||
          item.choices
            .filter((choice) => answer?.choice_ids.includes(choice.choice_id))
            .map((choice) => choice.label)
            .join(", ")
        );
      })
      .join("; "),
  };
}

export type RestoredConversation = {
  messages: ConversationMessage[];
  traceTargets: DeveloperTraceTarget[];
  activities: AssistantActivityTurn[];
  interactions: string[];
  figure: PlotRunSnapshot | null;
  /** The last request, when the assistant is still planning it or waiting for an answer. */
  pendingTurn: { accepted: AssistantTurnAccepted; text: string } | null;
  /** The last run, when it is still being drawn. */
  pendingRun: { accepted: PlotRunAccepted; turnId: string } | null;
};

/** Rebuild a saved conversation as the Workspace shows it. */
export function restoreConversation(
  session: WorkspaceSessionDocument,
): RestoredConversation {
  const restored: RestoredConversation = {
    messages: [],
    traceTargets: [],
    activities: [],
    interactions: [],
    figure: session.figure?.result ? session.figure : null,
    pendingTurn: null,
    pendingRun: null,
  };
  function say(message: Omit<ConversationMessage, "id">) {
    restored.messages.push({
      ...message,
      id: `message_${restored.messages.length + 1}`,
    });
  }
  session.turns.forEach(({ turn, links, answers, run }, index) => {
    const last = index === session.turns.length - 1;
    const turnId = turn.turn_id;
    say({
      role: "user",
      content: turn.request_text,
      turnId,
      referenceImages: turn.reference_images ?? [],
    });
    restored.traceTargets.push({
      turnId,
      traceHref: links.trace,
      request: turn.request_text,
    });
    restored.activities.push({
      turnId,
      request: turn.request_text,
      status: turn.status,
      activity: turn.activity ?? [],
      traceHref: links.trace,
      runStatus: turn.run_status,
    });
    for (const { question, answer } of answers) {
      const exchange = answeredQuestions(question, answer.answers);
      restored.interactions.push(question.interaction_id);
      say({ role: "assistant", content: exchange.prompt });
      say({ role: "user", content: exchange.answer });
    }
    const response = turn.response;
    if (turn.status === "completed" && response?.outcome === "message")
      say({ role: "assistant", content: response.message ?? "", turnId });
    else if (turn.status === "completed" && response?.plot_run) {
      const ended = run && FINISHED.has(run.status) ? runMessage(run) : null;
      if (ended) say({ role: "assistant", turnId, ...ended });
      else if (last && run && !FINISHED.has(run.status))
        restored.pendingRun = { accepted: response.plot_run, turnId };
    } else if (turn.status === "failed")
      say({
        role: "assistant",
        content: turn.error?.message ?? "The assistant request failed.",
        tone: "error",
        turnId,
      });
    else if (turn.status === "cancelled")
      say({
        role: "assistant",
        content: "I stopped this request. Your saved figure is unchanged.",
        turnId,
      });
    else if (last)
      restored.pendingTurn = {
        accepted: {
          schema_version: "1.0",
          turn_id: turnId,
          status: "running",
          links,
        },
        text: turn.request_text,
      };
  });
  return restored;
}
