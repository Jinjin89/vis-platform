import { z } from "zod";
import type { components } from "./generated/schema";
import { request } from "./client";
import { objectReferenceSchema } from "./schemas/datasets";

export type PlotSource = components["schemas"]["PlotSource"];
export const plotSourceSchema: z.ZodType<PlotSource> = z
  .object({
    schema_version: z.literal("1.0"),
    project_id: z.string(),
    plot_id: z.string(),
    version_id: z.string(),
    code: z.string().nullable().optional(),
    render_code: z.string().nullable().optional(),
    parameters: z
      .record(
        z.string(),
        z.union([z.boolean(), z.number().finite(), z.string()]),
      )
      .optional(),
    input_objects: z.array(objectReferenceSchema).optional(),
    result_bindings: z.record(z.string(), objectReferenceSchema).optional(),
    message: z.string(),
  })
  .strict();

export function getPlotSource(
  projectId: string,
  plotId: string,
  versionId: string,
) {
  return request(
    `/api/v1/projects/${encodeURIComponent(projectId)}/plots/${encodeURIComponent(plotId)}/versions/${encodeURIComponent(versionId)}/source`,
    plotSourceSchema,
  );
}
