import { z } from "zod";
import type { components } from "../generated/schema";
import { datasetSchema } from "./datasets";
import { referenceImageSchema } from "./referenceImages";
import { plannerQuestionsSchema } from "./planner";
import {
  assistantTurnAcceptedSchema,
  assistantTurnSnapshotSchema,
  plotResultSchema,
  plotRunAcceptedSchema,
  plotRunSnapshotSchema,
} from "./plotRun";

const cell = z.union([z.string(), z.number().finite(), z.boolean(), z.null()]);
export const reportDatasetSchema = z
  .object({
    dataset_id: z.string().min(1),
    revision_id: z.string().nullable().default(null),
  })
  .strict();
export const reportTextSchema = z
  .object({
    id: z.string().min(1),
    type: z.literal("text"),
    body: z.string().max(30000).default(""),
    evidence_version_ids: z.array(z.string()).max(100).default([]),
  })
  .strict();
export const reportFigureSchema = z
  .object({
    id: z.string().min(1),
    type: z.literal("figure"),
    version_id: z.string().nullable().default(null),
    follow_plot_id: z.string().nullable().optional(),
    image_id: z.string().nullable().default(null),
    caption: z.string().max(4000).default(""),
  })
  .strict()
  .refine(
    (b) => Boolean(b.version_id) !== Boolean(b.image_id),
    "A figure needs one saved plot or image.",
  );
export const reportTableSchema = z
  .object({
    id: z.string().min(1),
    type: z.literal("table"),
    title: z.string().max(200).default(""),
    columns: z.array(z.string()).min(1).max(30),
    rows: z.array(z.array(cell)).max(200).default([]),
    source_description: z.string().max(2000).default(""),
  })
  .strict()
  .refine(
    (table) => table.rows.every((row) => row.length === table.columns.length),
    "Table rows must match the columns.",
  );
export const reportBlockSchema = z.discriminatedUnion("type", [
  reportTextSchema,
  reportFigureSchema,
  reportTableSchema,
]);
export const slideFrameSchema = z
  .object({
    x: z.number().min(0).max(1),
    y: z.number().min(0).max(1),
    width: z.number().positive().max(1),
    height: z.number().positive().max(1),
  })
  .strict()
  .refine(
    (f) => f.x + f.width <= 1.001 && f.y + f.height <= 1.001,
    "Keep elements inside the slide.",
  );
export const slideSettingsSchema = z
  .object({
    layout: z
      .enum(["title", "figure-summary", "two-column", "statement", "table"])
      .default("figure-summary"),
    notes: z.string().max(12000).default(""),
    frames: z.record(z.string(), slideFrameSchema).default({}),
  })
  .strict();
export const presentationSettingsSchema = z
  .object({
    aspect_ratio: z.literal("16:9").default("16:9"),
    theme: z.enum(["paper", "midnight"]).default("paper"),
  })
  .strict();
export type SlideSettings = z.infer<typeof slideSettingsSchema>;
export type SlideFrame = z.infer<typeof slideFrameSchema>;
export const reportSectionSchema = z
  .object({
    id: z.string().min(1),
    title: z.string().min(1).max(200),
    level: z.union([z.literal(1), z.literal(2)]).default(1),
    parent_id: z.string().nullable().default(null),
    slide: slideSettingsSchema.nullable().optional(),
    blocks: z.array(reportBlockSchema).max(200).default([]),
  })
  .strict();
export const reportContentSchema = z
  .object({
    schema_version: z.literal("2.0").default("2.0"),
    kind: z.enum(["report", "slides"]).default("report"),
    presentation: presentationSettingsSchema.nullable().optional(),
    title: z.string().min(1).max(200),
    datasets: z.array(reportDatasetSchema).max(50).default([]),
    sections: z.array(reportSectionSchema).max(100).default([]),
  })
  .strict()
  .superRefine((content, ctx) => {
    const ids = content.sections.flatMap((topic) => [
      topic.id,
      ...topic.blocks.map((b) => b.id),
    ]);
    for (const section of content.sections)
      for (const block of section.blocks) {
        if (block.type === "figure" && block.version_id && block.caption)
          ctx.addIssue({
            code: "custom",
            message: "Plot descriptions come from the shared plot version.",
          });
      }
    let parent: string | null = null;
    for (const section of content.sections) {
      if (section.level === 1 && section.parent_id === null)
        parent = section.id;
      else if (
        section.level !== 2 ||
        section.parent_id === null ||
        section.parent_id !== parent
      )
        ctx.addIssue({
          code: "custom",
          message: "Subsections must follow their first-level parent.",
        });
    }
    if (new Set(ids).size !== ids.length)
      ctx.addIssue({
        code: "custom",
        message: "Topic and block IDs must be unique.",
      });
  }) satisfies z.ZodType<components["schemas"]["ReportContent"]>;

const reportEditSchema = z
  .object({
    edit_id: z.string(),
    section_id: z.string(),
    block_id: z.string().nullable().default(null),
    output_block_id: z.string(),
    kind: z.enum(["figure", "text", "discussion"]),
    prompt: z.string(),
    status: z.enum([
      "running",
      "awaiting_input",
      "awaiting_approval",
      "completed",
      "failed",
      "cancelled",
    ]),
    error: z.string().nullable().default(null),
    response_text: z.string().nullable().default(null),
    dismissed: z.boolean().default(false),
    message_id: z.string().nullable().default(null),
    created_at: z.string(),
    assistant: assistantTurnAcceptedSchema.nullable().default(null),
    assistant_state: assistantTurnSnapshotSchema.nullable().default(null),
    run: plotRunAcceptedSchema.nullable().default(null),
    run_state: plotRunSnapshotSchema.nullable().default(null),
  })
  .strict();
export const reportMessageSchema = z
  .object({
    message_id: z.string(),
    prompt: z.string(),
    selection: z
      .object({
        section_id: z.string().nullable().optional(),
        block_id: z.string().nullable().optional(),
      })
      .strict()
      .nullable()
      .optional(),
    status: z.enum([
      "running",
      "awaiting_input",
      "awaiting_approval",
      "completed",
      "failed",
      "cancelled",
    ]),
    phase: z
      .enum(["planning", "applying", "generating", "finished"])
      .default("planning"),
    response_text: z.string().nullable().default(null),
    error: z.string().nullable().default(null),
    question: plannerQuestionsSchema.nullable().default(null),
    active_edit_id: z.string().nullable().default(null),
    completed_actions: z.array(z.string()).default([]),
    created_at: z.string(),
  })
  .strict();

const summarySchema = z
  .object({
    report_id: z.string(),
    project_id: z.string(),
    title: z.string(),
    revision: z.number().int(),
    updated_at: z.string(),
  })
  .strict();
export const reportDocumentSchema = summarySchema
  .extend({
    schema_version: z.literal("1.0"),
    created_at: z.string(),
    content: reportContentSchema,
    datasets: z.array(datasetSchema),
    figure_bindings: z.record(z.string(), z.string()).optional(),
    figures: z.record(z.string(), plotResultSchema),
    images: z.record(z.string(), referenceImageSchema),
    edits: z.array(reportEditSchema),
    messages: z.array(reportMessageSchema).default([]),
    stale_text_ids: z.array(z.string()).default([]),
  })
  .strict() satisfies z.ZodType<components["schemas"]["ReportDocument"]>;
export const reportListSchema = z
  .object({
    schema_version: z.literal("1.0"),
    reports: z.array(summarySchema),
    total: z.number(),
    offset: z.number(),
  })
  .strict();
export const reportHistorySchema = z
  .object({
    schema_version: z.literal("1.0"),
    total: z.number(),
    revisions: z.array(
      z
        .object({
          revision: z.number(),
          summary: z.string(),
          created_at: z.string(),
        })
        .strict(),
    ),
  })
  .strict();
export const reportFiguresSchema = z
  .object({
    schema_version: z.literal("1.0"),
    figures: z.array(plotResultSchema),
    total: z.number(),
    offset: z.number(),
  })
  .strict();

export type ReportDocument = z.infer<typeof reportDocumentSchema>;
export type ReportContent = z.infer<typeof reportContentSchema>;
export type ReportSection = z.infer<typeof reportSectionSchema>;
export type ReportBlock = z.infer<typeof reportBlockSchema>;
export type ReportFigure = z.infer<typeof reportFigureSchema>;
export type ReportText = z.infer<typeof reportTextSchema>;
export type ReportEdit = z.infer<typeof reportEditSchema>;
export type ReportGenerateRequest =
  components["schemas"]["ReportGenerateRequest"];
export const reportEditActive = (edit: Pick<ReportEdit, "status">) =>
  ["running", "awaiting_input", "awaiting_approval"].includes(edit.status);
/** The parts of a plotting request that its status card shows and answers. */
export type PlotRequestProgress = Pick<
  ReportEdit,
  | "kind"
  | "status"
  | "error"
  | "prompt"
  | "block_id"
  | "assistant"
  | "assistant_state"
  | "run"
  | "run_state"
>;

export const legacyReportContentSchema = z
  .object({
    schema_version: z.literal("1.0").default("1.0"),
    title: z.string().min(1).max(200),
    datasets: z.array(reportDatasetSchema).max(50).default([]),
    topics: z
      .array(
        z
          .object({
            id: z.string().min(1),
            title: z.string().min(1).max(200),
            blocks: z.array(reportBlockSchema).max(100).default([]),
          })
          .strict(),
      )
      .max(100)
      .default([]),
  })
  .strict();
export const reportImportSchema = z.union([
  reportContentSchema,
  legacyReportContentSchema,
]);
export type ReportImportContent = z.infer<typeof reportImportSchema>;
export type ReportMessage = z.infer<typeof reportMessageSchema>;
export type ReportOperation =
  import("../generated/schema").components["schemas"]["ReportOperationsRequest"]["operations"][number];
export type ReportSelection =
  import("../generated/schema").components["schemas"]["ReportSelection"];
export type ReportMessageRequest =
  import("../generated/schema").components["schemas"]["ReportMessageRequest"];

export function figureForBlock(document: ReportDocument, block: ReportFigure) {
  return block.version_id
    ? document.figures[document.figure_bindings?.[block.id] ?? block.version_id]
    : undefined;
}
