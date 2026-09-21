import { z } from "zod";
import type { components } from "../generated/schema";
import { plotResultSchema } from "./plotRun";
import { referenceImageSchema } from "./referenceImages";

const identifier = z.string().min(1).max(160);
const millimetres = z.number().finite().min(0).max(1000);

export const figurePageSchema = z
  .object({
    width_mm: z.number().finite().min(20).max(500),
    height_mm: z.number().finite().min(20).max(1000),
    height_mode: z.enum(["fixed", "auto"]).default("auto"),
    margin_mm: z.number().finite().min(0).max(50).default(5),
  })
  .strict()
  .refine(
    (page) => 2 * page.margin_mm < Math.min(page.width_mm, page.height_mm),
    "Page margins must leave room for panels.",
  );
export const panelLabelStyleSchema = z
  .object({
    case: z.enum(["upper", "lower"]).default("upper"),
    size_pt: z.number().finite().min(5).max(24).default(10),
    bold: z.boolean().default(true),
    font_family: z
      .string()
      .regex(/^[A-Za-z0-9][A-Za-z0-9 -]*$/)
      .max(80)
      .default("Arial"),
  })
  .strict();
export const panelContentSchema = z.discriminatedUnion("type", [
  z
    .object({
      type: z.literal("plot"),
      version_id: identifier,
      source_version_id: identifier.nullable().default(null),
      ignored_version_id: identifier.nullable().default(null),
    })
    .strict(),
  z.object({ type: z.literal("image"), image_id: identifier }).strict(),
]);
export const figurePanelSchema = z
  .object({
    id: identifier,
    content: panelContentSchema,
    x_mm: millimetres,
    y_mm: millimetres,
    scale: z.number().finite().min(0.05).max(10).default(1),
    label: z
      .string()
      .min(1)
      .max(8)
      .regex(/^\S(.*\S)?$/)
      .nullable()
      .default(null),
    show_label: z.boolean().default(true),
    locked: z.boolean().default(false),
  })
  .strict();
export const figureLegendSchema = z
  .object({
    title: z.string().max(1000).default(""),
    entries: z.record(identifier, z.string().max(4000)).default({}),
  })
  .strict();
export const figureContentSchema = z
  .object({
    schema_version: z.literal("1.0").default("1.0"),
    title: z.string().min(1).max(200),
    page: figurePageSchema,
    labels: panelLabelStyleSchema.default({
      case: "upper",
      size_pt: 10,
      bold: true,
      font_family: "Arial",
    }),
    panels: z.array(figurePanelSchema).max(40).default([]),
    legend: figureLegendSchema.default({ title: "", entries: {} }),
    min_font_pt: z.number().finite().min(4).max(12).default(5),
  })
  .strict()
  .refine(
    (content) =>
      new Set(content.panels.map((panel) => panel.id)).size ===
      content.panels.length,
    "Panel IDs must be unique within a figure.",
  )
  .refine(
    (content) =>
      Object.keys(content.legend.entries).every((id) =>
        content.panels.some((panel) => panel.id === id),
      ),
    "Legend entries must refer to panels in this figure.",
  );

const frameSchema = z
  .object({
    x_mm: z.number(),
    y_mm: z.number(),
    width_mm: z.number(),
    height_mm: z.number(),
  })
  .strict();
const checkSchema = z
  .object({
    code: z.enum([
      "outside_margin",
      "overlap",
      "small_text",
      "low_resolution",
      "label_order",
      "unused_space",
    ]),
    severity: z.enum(["warning", "info"]),
    message: z.string(),
    panel_ids: z.array(z.string()).default([]),
  })
  .strict();
const jobSchema = z
  .object({
    job_id: z.string(),
    panel_id: z.string(),
    status: z.enum(["running", "completed", "failed", "discarded"]),
    width_mm: z.number(),
    height_mm: z.number(),
    error: z.string().nullable().default(null),
    created_at: z.string(),
  })
  .strict();
const summarySchema = z
  .object({
    composition_id: z.string(),
    project_id: z.string(),
    title: z.string(),
    revision: z.number().int(),
    updated_at: z.string(),
  })
  .strict();
export const figureDocumentSchema = summarySchema
  .extend({
    schema_version: z.literal("1.0"),
    created_at: z.string(),
    content: figureContentSchema,
    page_height_mm: z.number(),
    panels: z.record(
      z.string(),
      z
        .object({
          label: z.string().nullable(),
          frame: frameSchema,
          natural_width_mm: z.number(),
          natural_height_mm: z.number(),
        })
        .strict(),
    ),
    figures: z.record(z.string(), plotResultSchema),
    images: z.record(z.string(), referenceImageSchema),
    updates: z.record(z.string(), z.string()).default({}),
    checks: z.array(checkSchema).default([]),
    jobs: z.array(jobSchema).default([]),
  })
  .strict() satisfies z.ZodType<
  components["schemas"]["FigureCompositionDocument"]
>;
export const figureListSchema = z
  .object({
    schema_version: z.literal("1.0"),
    compositions: z.array(summarySchema),
    total: z.number(),
    offset: z.number(),
  })
  .strict();
export const figureHistorySchema = z
  .object({
    schema_version: z.literal("1.0"),
    revisions: z.array(
      z
        .object({
          revision: z.number(),
          summary: z.string(),
          created_at: z.string(),
        })
        .strict(),
    ),
    total: z.number(),
  })
  .strict();

export type FigureDocument = z.infer<typeof figureDocumentSchema>;
export type FigureContent = z.infer<typeof figureContentSchema>;
export type FigurePage = z.infer<typeof figurePageSchema>;
export type FigurePanel = z.infer<typeof figurePanelSchema>;
export type FigureLegend = z.infer<typeof figureLegendSchema>;
export type PanelLabelStyle = z.infer<typeof panelLabelStyleSchema>;
export type PanelFrame = z.infer<typeof frameSchema>;
export type FigureCheck = z.infer<typeof checkSchema>;
export type FigureRenderJob = z.infer<typeof jobSchema>;
export type FigureArrangement =
  components["schemas"]["ArrangeRequest"]["arrangement"];
export type PanelGeometry = Pick<FigurePanel, "x_mm" | "y_mm" | "scale">;
export type FigureOperation =
  components["schemas"]["FigureOperationsRequest"]["operations"][number];
