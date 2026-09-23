import { z } from "zod";
import { apiUrl, checkResponse, request } from "./client";
import type { components } from "./generated/schema";
import { assistantTurnAcceptedSchema } from "./schemas/plotRun";

type Schemas = components["schemas"];
/** A place marked on a plot image. */
export type ImageMark = Schemas["ImageMark"];
/** A point clicked in an interactive point view. */
export type ElementMark = Schemas["ElementMark"];
/** An area dragged in an interactive point view, in data units. */
export type SelectionMark = Schemas["SelectionMark"];
export type PlotMark = ImageMark | ElementMark | SelectionMark;
export type PointView = Schemas["PointView"];

/**
 * Ask about or change a plot. Marks tie the request's words ("this", "①") to places on the
 * version they were placed on. Without a version, a new plot is made. Requests offer
 * interactive views, such as point maps for embeddings and spatial data.
 */
export const sendPinpointRequest = (
  projectId: string,
  {
    text,
    baseVersionId,
    marks,
    requestId,
  }: {
    text: string;
    baseVersionId: string | null;
    marks: PlotMark[];
    requestId: string;
  },
) =>
  request("/api/v1/assistant-turns", assistantTurnAcceptedSchema, {
    method: "POST",
    headers: { Prefer: "respond-async", "Idempotency-Key": requestId },
    body: JSON.stringify({
      schema_version: "1.0",
      project_id: projectId,
      request: {
        text,
        generation_mode: "auto",
        gallery_mode: "off",
        controls_mode: "hybrid",
        interactive: true,
      },
      data_scope: { mode: "auto" },
      ...(baseVersionId ? { base_version_id: baseVersionId } : {}),
      ...(marks.length ? { plot_marks: marks } : {}),
    }),
  });

const axisSchema = z
  .object({
    field: z.string(),
    title: z.string(),
    domain: z.tuple([z.number(), z.number()]),
  })
  .strict();
export const pointViewSchema: z.ZodType<PointView> = z
  .object({
    title: z.string(),
    count: z.number().int().nonnegative(),
    dropped: z.number().int().nonnegative(),
    x: axisSchema,
    y: axisSchema.extend({ direction: z.enum(["up", "down"]) }).strict(),
    equal_aspect: z.boolean(),
    color: z
      .discriminatedUnion("type", [
        z
          .object({
            type: z.literal("categorical"),
            field: z.string(),
            title: z.string(),
            categories: z.array(
              z.object({ value: z.string(), color: z.string() }).strict(),
            ),
            missing_color: z.string(),
          })
          .strict(),
        z
          .object({
            type: z.literal("continuous"),
            field: z.string(),
            title: z.string(),
            domain: z.tuple([z.number(), z.number()]),
            stops: z.array(z.string()),
          })
          .strict(),
      ])
      .nullable(),
    columns: z.array(z.enum(["x", "y", "color"])),
    point_size: z.number(),
    opacity: z.number(),
    image: z
      .object({
        extent: z.tuple([z.number(), z.number(), z.number(), z.number()]),
        visible: z.boolean(),
      })
      .strict()
      .nullable(),
    links: z
      .object({
        columns: z.string(),
        image: z.string().nullable().optional(),
      })
      .strict(),
  })
  .strict();

const viewPath = (projectId: string, plotId: string, versionId: string) =>
  `/api/v1/projects/${encodeURIComponent(projectId)}/plots/${encodeURIComponent(
    plotId,
  )}/versions/${encodeURIComponent(versionId)}/point-view`;

export const getPointView = (
  projectId: string,
  plotId: string,
  versionId: string,
) => request(viewPath(projectId, plotId, versionId), pointViewSchema);

/** The view's binary columns: positions, and colour codes or values when coloured. */
export type PointColumns = {
  x: Float32Array;
  y: Float32Array;
  color?: Float32Array;
};

export async function getPointColumns(view: PointView): Promise<PointColumns> {
  const response = await fetch(apiUrl(view.links.columns));
  await checkResponse(response);
  const buffer = await response.arrayBuffer();
  if (buffer.byteLength !== view.count * view.columns.length * 4)
    throw new Error("The plot's points arrived incomplete. Reload to retry.");
  const column = (name: PointView["columns"][number]) => {
    const index = view.columns.indexOf(name);
    return index < 0
      ? undefined
      : new Float32Array(buffer, index * view.count * 4, view.count);
  };
  return { x: column("x")!, y: column("y")!, color: column("color") };
}
