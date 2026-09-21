import { z } from "zod";

export const agentActivitySchema = z
  .object({
    sequence: z.number().int().positive(),
    step_id: z.string(),
    kind: z.enum(["agent", "tool", "routing", "question", "render"]),
    actor: z.string(),
    label: z.string(),
    status: z.enum([
      "running",
      "completed",
      "waiting",
      "blocked",
      "failed",
      "cancelled",
    ]),
    summary: z.string().nullable().optional(),
    tool_name: z.string().nullable().optional(),
    occurred_at: z.string(),
    duration_ms: z.number().int().nonnegative().nullable().optional(),
  })
  .strict();
export const clarificationQuestionSchema = z
  .object({
    question_id: z.string(),
    header: z.string(),
    prompt: z.string(),
    reason: z.string().default(""),
    selection: z.enum(["single", "multiple", "text"]).default("single"),
    choices: z
      .array(
        z
          .object({
            choice_id: z.string(),
            label: z.string(),
            description: z.string().default(""),
            recommended: z.boolean().default(false),
          })
          .strict(),
      )
      .default([]),
    allow_free_text: z.boolean().default(true),
  })
  .strict();
export const plannerQuestionsSchema = z
  .object({
    interaction_id: z.string(),
    questions: z.array(clarificationQuestionSchema).min(1).max(4),
  })
  .strict();
export type AgentActivity = z.infer<typeof agentActivitySchema>;
export type PlannerQuestions = z.infer<typeof plannerQuestionsSchema>;
export type PlannerAnswer = {
  question_id: string;
  choice_ids: string[];
  free_text?: string | null;
};
