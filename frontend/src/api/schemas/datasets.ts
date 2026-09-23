import { z } from "zod";
import type { components } from "../generated/schema";
import { artifactSchema } from "./artifacts";

export type Dataset = components["schemas"]["Dataset"];
export type AnalysisResult = components["schemas"]["AnalysisResult"];
export type ObjectDescription = components["schemas"]["ObjectDescription"];
export const objectReferenceSchema = z
  .object({ object_id: z.string(), revision_id: z.string() })
  .strict();
const columnSchema = z
  .object({
    name: z.string(),
    data_type: z.enum(["number", "boolean", "string", "unknown"]),
    missing_count: z.number().int().nonnegative().default(0),
    unique_count: z.number().int().nullable().optional(),
    numeric: z
      .object({ minimum: z.number(), maximum: z.number(), mean: z.number() })
      .strict()
      .nullable()
      .optional(),
    description: z.string().nullable().optional(),
    unit: z.string().nullable().optional(),
    meaning_origin: z
      .enum(["source", "inferred", "user"])
      .nullable()
      .optional(),
  })
  .strict();
export const objectDescriptionSchema: z.ZodType<ObjectDescription> = z
  .object({
    object_id: z.string(),
    revision_id: z.string(),
    owner_id: z.string(),
    owner_kind: z.enum(["dataset", "analysis_result"]).default("dataset"),
    name: z.string(),
    description: z.string().default(""),
    kind: z
      .enum(["table", "matrix", "model", "scalar", "image", "unknown"])
      .default("table"),
    format: z.string(),
    dimensions: z.array(z.number().int()).optional(),
    scalar: z.union([z.number(), z.boolean()]).nullable().optional(),
    columns: z.array(columnSchema).optional(),
    observation_unit: z.string().nullable().optional(),
    description_origin: z
      .enum(["source", "parser", "inferred", "user"])
      .default("parser"),
    readiness: z
      .enum(["ready", "unsupported", "unavailable", "failed"])
      .default("ready"),
    limitations: z.array(z.string()).optional(),
    capabilities: z.array(z.enum(["inspect", "materialize"])).optional(),
    content_hash: z.string().nullable().optional(),
    extensions: z.record(z.string(), z.json()).optional(),
    artifact: artifactSchema.nullable().optional(),
  })
  .strict();
const relationshipSchema = z
  .object({
    relationship_id: z.string(),
    left_object_id: z.string(),
    right_object_id: z.string(),
    kind: z
      .enum(["join", "annotates", "derived_from", "related"])
      .default("related"),
    left_key: z.string().nullable().optional(),
    right_key: z.string().nullable().optional(),
    left_axis: z.enum(["rows", "columns"]).nullable().optional(),
    right_axis: z.enum(["rows", "columns"]).nullable().optional(),
    cardinality: z
      .enum([
        "one_to_one",
        "many_to_one",
        "one_to_many",
        "many_to_many",
        "unknown",
      ])
      .default("unknown"),
    description: z.string().default(""),
    origin: z.enum(["source", "inferred", "user"]).default("source"),
    validation: z.enum(["declared", "verified", "invalid"]).default("declared"),
    matched_rows: z.number().int().nullable().optional(),
    limitations: z.array(z.string()).optional(),
  })
  .strict();
export const datasetSchema: z.ZodType<Dataset> = z
  .object({
    schema_version: z.literal("1.0").default("1.0"),
    dataset_id: z.string(),
    contains_demo_data: z.boolean().default(false),
    project_id: z.string(),
    name: z.string(),
    description: z.string().default(""),
    source_kind: z.enum(["upload", "analysis_platform"]),
    source_id: z.string(),
    source_revision: z.string().nullable().optional(),
    revision_id: z.string().nullable().optional(),
    state: z
      .enum(["uploading", "processing", "ready", "failed"])
      .default("uploading"),
    objects: z.array(objectDescriptionSchema).optional(),
    relationships: z.array(relationshipSchema).optional(),
    interpretation_status: z
      .enum(["pending", "source_provided", "interpreted", "unavailable"])
      .default("pending"),
    notices: z.array(z.string()).optional(),
    created_at: z.string(),
    updated_at: z.string(),
  })
  .strict();
export const datasetListSchema = z
  .object({
    schema_version: z.literal("1.0").default("1.0"),
    datasets: z.array(datasetSchema),
    total: z.number().int(),
    offset: z.number().int().optional(),
    complete: z.boolean(),
  })
  .strict();
export const analysisResultSchema: z.ZodType<AnalysisResult> = z
  .object({
    result_id: z.string(),
    contains_demo_data: z.boolean().default(false),
    project_id: z.string(),
    run_id: z.string(),
    name: z.string(),
    description: z.string(),
    created_at: z.string(),
    inputs: z.array(objectReferenceSchema),
    objects: z.array(objectDescriptionSchema),
    artifacts: z.array(artifactSchema).optional(),
    code_hash: z.string(),
    parameters: z.record(z.string(), z.json()).optional(),
    environment: z.record(z.string(), z.string()).optional(),
    random_seed: z.number().int(),
    relationships_used: z.array(relationshipSchema).optional(),
  })
  .strict();
export const analysisResultListSchema = z
  .object({
    schema_version: z.literal("1.0").default("1.0"),
    results: z.array(analysisResultSchema),
    total: z.number().int(),
    offset: z.number().int().optional(),
    complete: z.boolean(),
  })
  .strict();
export const platformDatasetListSchema = z
  .object({
    schema_version: z.literal("1.0").default("1.0"),
    connected: z.boolean(),
    datasets: z
      .array(
        z
          .object({
            source_id: z.string(),
            contains_demo_data: z.boolean().default(false),
            revision: z.string(),
            name: z.string(),
            description: z.string().default(""),
            object_count: z.number().int().optional(),
          })
          .strict(),
      )
      .optional(),
    next_cursor: z.string().nullable().optional(),
    complete: z.boolean().optional(),
    message: z.string().nullable().optional(),
  })
  .strict();
export const uploadReceiptSchema = z
  .object({
    schema_version: z.literal("1.0").default("1.0"),
    file_id: z.string(),
    name: z.string(),
    size: z.number().int(),
  })
  .strict();
