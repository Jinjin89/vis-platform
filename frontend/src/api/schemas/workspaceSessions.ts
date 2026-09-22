import { z } from "zod";
import { plannerQuestionsSchema } from "./planner";
import {
  assistantLinksSchema,
  assistantTurnSnapshotSchema,
  plotRunSnapshotSchema,
} from "./plotRun";

export const workspaceSessionSchema = z
  .object({
    schema_version: z.literal("1.0"),
    session_id: z.string(),
    project_id: z.string(),
    title: z.string(),
    created_at: z.string(),
    updated_at: z.string(),
  })
  .strict();
export const workspaceSessionListSchema = z
  .object({
    sessions: z.array(workspaceSessionSchema),
    total: z.number().int(),
    offset: z.number().int(),
  })
  .strict();
const answeredQuestionsSchema = z
  .object({
    question: plannerQuestionsSchema,
    answer: z
      .object({
        project_id: z.string(),
        interaction_id: z.string(),
        answers: z.array(
          z
            .object({
              question_id: z.string(),
              choice_ids: z.array(z.string()),
              free_text: z.string().nullable().optional(),
            })
            .strict(),
        ),
      })
      .strict(),
  })
  .strict();
export const workspaceSessionDocumentSchema = workspaceSessionSchema
  .extend({
    turns: z.array(
      z
        .object({
          turn: assistantTurnSnapshotSchema,
          links: assistantLinksSchema,
          answers: z.array(answeredQuestionsSchema),
          run: plotRunSnapshotSchema.nullable(),
        })
        .strict(),
    ),
    figure: plotRunSnapshotSchema.nullable(),
  })
  .strict();

export type WorkspaceSession = z.infer<typeof workspaceSessionSchema>;
export type WorkspaceSessionDocument = z.infer<
  typeof workspaceSessionDocumentSchema
>;
