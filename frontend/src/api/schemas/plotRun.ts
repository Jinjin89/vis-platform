import { apiPathSchema, artifactSchema } from "./artifacts";
import { referenceImageSchema } from "./referenceImages";
export { apiPathSchema, artifactSchema } from "./artifacts";
import { analysisResultSchema, objectReferenceSchema } from "./datasets";
import { z } from "zod";
import {
  agentActivitySchema,
  clarificationQuestionSchema,
  plannerQuestionsSchema,
} from "./planner";

import type { components } from "../generated/schema";

export type Project = components["schemas"]["Project"];
export type PlotResult = components["schemas"]["PlotResultSummary"];
export type PlotVersionList = components["schemas"]["PlotVersionList"];
export type ParameterValues =
  components["schemas"]["ParameterUpdateRequest"]["changes"];
export type ControlDefinition = NonNullable<PlotResult["controls"]>[number];
export type AssistantTurnResponse =
  components["schemas"]["AssistantTurnResponse"];
export type AssistantTurnAccepted =
  components["schemas"]["AssistantTurnAccepted"];
export type AssistantTurnSnapshot =
  components["schemas"]["AssistantTurnSnapshot"];
export type IntentDecision = components["schemas"]["IntentDecision"];
export type DeveloperTraceEntry = components["schemas"]["DeveloperTraceEntry"];
export type DeveloperTraceResponse =
  components["schemas"]["DeveloperTraceResponse"];
export type PlotRunAccepted = components["schemas"]["PlotRunAccepted"];
export type PlotRunSnapshot = components["schemas"]["PlotRunSnapshot"];
export type ArtifactReference = components["schemas"]["ArtifactReference"];
export type Question = components["schemas"]["Question"];
export type Approval = components["schemas"]["Approval"];
export type ApiErrorEnvelope = components["schemas"]["ApiErrorEnvelope"];

export const runStatusSchema = z.enum([
  "queued",
  "running",
  "awaiting_input",
  "awaiting_approval",
  "completed",
  "failed",
  "cancelled",
]);

export const runStageSchema = z.enum([
  "received",
  "understanding_intent",
  "selecting_data",
  "profiling_data",
  "planning_transformations",
  "planning_plot",
  "checking_capabilities",
  "generating_code",
  "running_r",
  "validating_plot",
  "committing_version",
]);

const parameterValueSchema = z.union([
  z.boolean(),
  z.number().finite(),
  z.string(),
]);
const controlBase = {
  id: z.string().min(1),
  label: z.string().min(1),
  group: z.string().default("essential"),
  description: z.string().nullable().optional(),
  visible_when: z
    .object({ control_id: z.string(), equals: parameterValueSchema })
    .strict()
    .nullable()
    .optional(),
  update_strategy: z.enum(["rerun", "regenerate", "confirm"]).default("rerun"),
};
const numberControlSchema = z
  .object({
    ...controlBase,
    type: z.literal("number"),
    value: z.number().finite(),
    minimum: z.number().finite(),
    maximum: z.number().finite(),
    step: z.number().positive(),
    unit: z.string().nullable().optional(),
    input_mode: z.enum(["slider", "number"]).nullable().optional(),
  })
  .strict();
const choiceControlSchema = z
  .object({
    ...controlBase,
    type: z.literal("choice"),
    value: z.string(),
    options: z
      .array(z.object({ value: z.string(), label: z.string() }).strict())
      .min(1),
  })
  .strict();
const textControlSchema = z
  .object({
    ...controlBase,
    type: z.literal("text"),
    value: z.string(),
    min_length: z.number().int().nonnegative().default(0),
    max_length: z.number().int().positive().default(200),
  })
  .strict();
const booleanControlSchema = z
  .object({
    ...controlBase,
    type: z.literal("boolean"),
    value: z.boolean(),
  })
  .strict();
export const controlDefinitionSchema = z
  .discriminatedUnion("type", [
    numberControlSchema,
    choiceControlSchema,
    textControlSchema,
    booleanControlSchema,
  ])
  .superRefine((control, context) => {
    if (
      control.type === "number" &&
      !(control.minimum <= control.value && control.value <= control.maximum)
    ) {
      context.addIssue({
        code: "custom",
        message: "The control value is outside its bounds.",
      });
    }
    if (
      control.type === "choice" &&
      (!control.options.some((option) => option.value === control.value) ||
        new Set(control.options.map((option) => option.value)).size !==
          control.options.length)
    ) {
      context.addIssue({
        code: "custom",
        message: "Choice options must be unique and include the value.",
      });
    }
    if (
      control.type === "text" &&
      (control.value.length < (control.min_length ?? 0) ||
        control.value.length > (control.max_length ?? 200))
    ) {
      context.addIssue({
        code: "custom",
        message: "Text value does not satisfy its limits.",
      });
    }
  });

export const questionSchema: z.ZodType<Question> = z
  .object({
    question_id: z.string(),
    prompt: z.string(),
    reason: z.string(),
    choices: z.array(
      z
        .object({
          choice_id: z.string(),
          label: z.string(),
          description: z.string().nullable().optional(),
        })
        .strict(),
    ),
    allow_free_text: z.boolean(),
  })
  .strict();

export const approvalSchema: z.ZodType<Approval> = z
  .object({
    approval_id: z.string(),
    operation: z.string(),
    summary: z.string(),
    scientific_effect: z.string(),
  })
  .strict();

export const projectSchema: z.ZodType<Project> = z
  .object({
    schema_version: z.literal("1.0"),
    project_id: z.string(),
    name: z.string(),
    created_at: z.string(),
  })
  .strict();

export const plotRunAcceptedSchema: z.ZodType<PlotRunAccepted> = z
  .object({
    schema_version: z.literal("1.0"),
    run_id: z.string(),
    status: runStatusSchema,
    stage: runStageSchema,
    links: z
      .object({
        status: apiPathSchema,
        events: apiPathSchema,
        cancel: apiPathSchema,
      })
      .strict(),
  })
  .strict();

const modeRequestsSchema = z
  .object({
    data: z.enum(["auto", "demo"]).nullable().optional(),
    generation: z.enum(["auto", "skill", "raw_code"]).nullable().optional(),
    gallery: z.enum(["off", "auto", "selected"]).nullable().optional(),
    controls: z.enum(["language", "panel", "hybrid"]).nullable().optional(),
  })
  .strict();

const variableMentionsSchema = z
  .object({
    x: z.array(z.string()).optional(),
    y: z.array(z.string()).optional(),
    group: z.array(z.string()).optional(),
    color: z.array(z.string()).optional(),
    facet: z.array(z.string()).optional(),
  })
  .strict();

const plotIntentSchema = z
  .object({
    goal: z.string(),
    explicit_family: z.string().nullable().optional(),
    variable_mentions: variableMentionsSchema.optional(),
    data_hints: z.array(z.string()).optional(),
    filters: z.array(z.string()).optional(),
    statistics: z.array(z.string()).optional(),
    appearance: z.array(z.string()).optional(),
  })
  .strict();

const refinementIntentSchema = z
  .object({
    changes: z.array(
      z
        .object({
          target: z.string(),
          value: z
            .union([z.string(), z.number(), z.boolean()])
            .nullable()
            .optional(),
          change_class: z.enum([
            "visual",
            "computational",
            "interpretation_sensitive",
          ]),
        })
        .strict(),
    ),
    reuse_data: z.boolean(),
    execution_strategy: z
      .enum(["parameters", "regenerate_render", "replan_analysis"])
      .default("parameters"),
  })
  .strict();

export const intentDecisionSchema: z.ZodType<IntentDecision> = z
  .object({
    kind: z.enum([
      "social",
      "plot_create",
      "plot_refine",
      "data_query",
      "analysis_create",
      "plot_query",
      "workspace_action",
      "out_of_scope",
      "unsafe",
      "unclear",
    ]),
    subtype: z.string(),
    normalized_request: z.string(),
    confidence: z.number().min(0).max(1),
    next_action: z.enum([
      "reply",
      "build_context",
      "refine_context",
      "call_data_tools",
      "execute_analysis",
      "read_plot_context",
      "execute_workspace_action",
      "ask_user",
      "reject",
    ]),
    mode_requests: modeRequestsSchema.optional(),
    plot: plotIntentSchema.nullable().optional(),
    analysis: plotIntentSchema.nullable().optional(),
    dataset_ids: z.array(z.string()).optional(),
    refinement: refinementIntentSchema.nullable().optional(),
    reference_image_ids: z.array(z.string()).max(3).nullable().optional(),
    missing_context: z.array(z.string()).optional(),
    decision_summary: z.string(),
    user_reply: z.string().nullable().optional(),
    questions: z.array(clarificationQuestionSchema).optional(),
  })
  .strict();

export const assistantLinksSchema = z
  .object({
    trace: apiPathSchema,
    status: apiPathSchema.nullable().optional(),
    events: apiPathSchema.nullable().optional(),
    cancel: apiPathSchema.nullable().optional(),
  })
  .strict();

export const assistantTurnResponseSchema: z.ZodType<AssistantTurnResponse> = z
  .object({
    schema_version: z.literal("1.0"),
    turn_id: z.string(),
    outcome: z.enum(["message", "plot_run", "question"]),
    intent: intentDecisionSchema,
    message: z.string().nullable().optional(),
    plot_run: plotRunAcceptedSchema.nullable().optional(),
    links: assistantLinksSchema,
    created_at: z.string(),
    question: plannerQuestionsSchema.nullable().optional(),
    activity: z.array(agentActivitySchema).optional(),
  })
  .strict()
  .superRefine((value, context) => {
    if (value.outcome === "message") {
      if (value.message == null || value.plot_run != null) {
        context.addIssue({
          code: "custom",
          message: "Message outcome must contain only a message.",
        });
      }
    } else if (value.outcome === "question") {
      if (value.question == null || value.plot_run != null)
        context.addIssue({
          code: "custom",
          message: "Question outcome requires a question.",
        });
    } else if (value.plot_run == null || value.message != null) {
      context.addIssue({
        code: "custom",
        message: "Plot-run outcome must contain only a plot run.",
      });
    }
  });

export const assistantTurnAcceptedSchema: z.ZodType<AssistantTurnAccepted> = z
  .object({
    schema_version: z.literal("1.0"),
    turn_id: z.string(),
    status: z.literal("running"),
    links: assistantLinksSchema,
  })
  .strict();
export const assistantSubmissionSchema = z.union([
  assistantTurnResponseSchema,
  assistantTurnAcceptedSchema,
]);
export const assistantTurnSnapshotSchema: z.ZodType<AssistantTurnSnapshot> = z
  .object({
    schema_version: z.literal("1.0"),
    turn_id: z.string(),
    project_id: z.string(),
    request_text: z.string(),
    reference_images: z.array(referenceImageSchema).optional(),
    revision: z.number().int(),
    status: z.enum([
      "running",
      "awaiting_input",
      "completed",
      "failed",
      "cancelled",
    ]),
    activity: z.array(agentActivitySchema).optional(),
    question: plannerQuestionsSchema.nullable().optional(),
    response: assistantTurnResponseSchema.nullable().optional(),
    error: z
      .object({ code: z.string(), message: z.string() })
      .strict()
      .nullable()
      .optional(),
    run_status: z.string().nullable().optional(),
  })
  .strict();

export const developerTraceEntrySchema: z.ZodType<DeveloperTraceEntry> = z
  .object({
    trace_id: z.string(),
    sequence: z.number().int().positive(),
    kind: z.enum([
      "llm_turn",
      "intent_decision",
      "routing",
      "stage",
      "tool_call",
      "r_execution",
      "error",
    ]),
    actor: z.string(),
    name: z.string(),
    status: z.enum(["started", "succeeded", "failed", "blocked"]),
    occurred_at: z.string(),
    duration_ms: z.number().int().nonnegative().nullable().optional(),
    input: z.record(z.string(), z.unknown()).nullable().optional(),
    output: z.record(z.string(), z.unknown()).nullable().optional(),
    error: z.record(z.string(), z.unknown()).nullable().optional(),
  })
  .strict();

export const developerTraceResponseSchema: z.ZodType<DeveloperTraceResponse> = z
  .object({
    schema_version: z.literal("1.0"),
    turn_id: z.string(),
    run_id: z.string().nullable().optional(),
    entries: z.array(developerTraceEntrySchema),
    reasoning_content_exposed: z.literal(false),
  })
  .strict();

export const plotResultSchema = z
  .object({
    plot_id: z.string(),
    version_id: z.string(),
    execution_mode: z.enum(["demo", "r"]),
    interactive_view: z.enum(["points"]).nullable().optional(),
    reference_images: z.array(referenceImageSchema).optional(),
    figure_size: z
      .object({ width: z.number(), height: z.number(), unit: z.literal("in") })
      .strict()
      .nullable()
      .optional(),
    contains_demo_data: z.boolean().nullable().optional(),
    preview: artifactSchema,
    controls_mode: z.enum(["language", "panel", "hybrid"]),
    controls: z.array(controlDefinitionSchema).optional(),
    control_groups: z
      .array(
        z
          .object({
            id: z.string(),
            label: z.string(),
            description: z.string().nullable().optional(),
          })
          .strict(),
      )
      .optional(),
    parameter_schema_version: z.literal("1.0").default("1.0"),
    parameter_updates_available: z.boolean().default(false),
    data_summary: z
      .string()
      .default("Data provenance was not recorded for this version."),
    data_used: z
      .array(
        z
          .object({
            object_id: z.string(),
            name: z.string(),
            source: z.string(),
            summary: z.string(),
            variable_mappings: z.record(z.string(), z.string()).optional(),
          })
          .strict(),
      )
      .optional(),
    input_objects: z.array(objectReferenceSchema).optional(),
    analysis_results: z.array(analysisResultSchema).optional(),
    caption: z.string().nullable().optional(),
    title: z.string().nullable().optional(),
    validation: z
      .object({
        status: z.enum(["demo_only", "passed", "passed_with_warnings"]),
        warnings: z.array(z.string()).optional(),
      })
      .strict(),
  })
  .strict();

export const plotRunSnapshotSchema: z.ZodType<PlotRunSnapshot> = z
  .object({
    schema_version: z.literal("1.0"),
    run_id: z.string(),
    project_id: z.string(),
    status: runStatusSchema,
    stage: runStageSchema,
    created_at: z.string(),
    updated_at: z.string(),
    result: plotResultSchema.nullable().optional(),
    analysis_results: z.array(analysisResultSchema).optional(),
    progress: z
      .object({
        progress: z.number().int().min(0).max(100),
        message: z.string(),
      })
      .strict()
      .nullable()
      .optional(),
    pending_question: questionSchema.nullable().optional(),
    pending_approval: approvalSchema.nullable().optional(),
    failure: z
      .object({
        code: z.string(),
        message: z.string(),
        recoverable: z.boolean(),
      })
      .strict()
      .nullable()
      .optional(),
  })
  .strict();

export const plotVersionListSchema: z.ZodType<PlotVersionList> = z
  .object({
    schema_version: z.literal("1.0"),
    project_id: z.string(),
    plot_id: z.string(),
    current_version_id: z.string(),
    versions: z.array(
      z
        .object({
          version_id: z.string(),
          run_id: z.string(),
          parent_version_id: z.string().nullable(),
          created_at: z.string(),
          change_summary: z.string(),
          result: plotResultSchema,
        })
        .strict(),
    ),
  })
  .strict();

export const apiErrorEnvelopeSchema: z.ZodType<ApiErrorEnvelope> = z
  .object({
    schema_version: z.literal("1.0"),
    error: z
      .object({
        code: z.string(),
        message: z.string(),
        recoverable: z.boolean(),
        details: z.record(z.string(), z.unknown()).nullable().optional(),
      })
      .strict(),
  })
  .strict();

const eventBase = z.object({
  schema_version: z.literal("1.0"),
  event_id: z.string(),
  run_id: z.string(),
  sequence: z.number().int().positive(),
  occurred_at: z.string(),
});

export const runEventSchema = z.discriminatedUnion("type", [
  eventBase
    .extend({
      type: z.literal("run.started"),
      payload: z
        .object({
          status: z.literal("queued"),
          stage: z.literal("received"),
        })
        .strict(),
    })
    .strict(),
  eventBase
    .extend({
      type: z.literal("progress.updated"),
      payload: z
        .object({
          status: z.literal("running"),
          stage: runStageSchema,
          progress: z.number().int().min(0).max(100),
          message: z.string(),
        })
        .strict(),
    })
    .strict(),
  eventBase
    .extend({
      type: z.literal("question.required"),
      payload: z
        .object({
          status: z.literal("awaiting_input"),
          stage: runStageSchema,
          question: questionSchema,
        })
        .strict(),
    })
    .strict(),
  eventBase
    .extend({
      type: z.literal("approval.required"),
      payload: z
        .object({
          status: z.literal("awaiting_approval"),
          stage: runStageSchema,
          approval: approvalSchema,
        })
        .strict(),
    })
    .strict(),
  eventBase
    .extend({
      type: z.literal("preview.ready"),
      payload: z
        .object({
          artifact: artifactSchema,
          provisional: z.boolean(),
        })
        .strict(),
    })
    .strict(),
  eventBase
    .extend({
      type: z.literal("run.completed"),
      payload: z
        .object({
          status: z.literal("completed"),
          plot_id: z.string().nullable().optional(),
          version_id: z.string().nullable().optional(),
        })
        .strict(),
    })
    .strict(),
  eventBase
    .extend({
      type: z.literal("run.failed"),
      payload: z
        .object({
          status: z.literal("failed"),
          code: z.string(),
          message: z.string(),
          recoverable: z.boolean(),
        })
        .strict(),
    })
    .strict(),
  eventBase
    .extend({
      type: z.literal("run.cancelled"),
      payload: z.object({ status: z.literal("cancelled") }).strict(),
    })
    .strict(),
]);

export type RunEvent = z.infer<typeof runEventSchema>;
