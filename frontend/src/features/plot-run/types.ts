import type { AnalysisResult } from "../../api/schemas/datasets";
import type {
  AgentActivity,
  PlannerQuestions,
} from "../../api/schemas/planner";
export type ConversationMessage = {
  referenceImages?: import("../../api/schemas/referenceImages").ReferenceImage[];
  id: string;
  role: "user" | "assistant";
  content: string;
  tone?: "default" | "error";
  turnId?: string;
  analysisResults?: AnalysisResult[];
};

export type DeveloperTraceTarget = {
  turnId: string;
  traceHref: string;
  request: string;
};

export type AssistantActivityTurn = {
  turnId: string;
  request: string;
  status: "running" | "awaiting_input" | "completed" | "failed" | "cancelled";
  activity: AgentActivity[];
  traceHref?: string;
  runStatus?: string | null;
};
export type PendingPlannerQuestion = {
  turnId: string;
  projectId: string;
  question: PlannerQuestions;
};
