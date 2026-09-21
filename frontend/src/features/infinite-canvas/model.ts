import { z } from "zod";
import { createMutationId } from "../../api/client";
import { datasetSchema, type Dataset } from "../../api/schemas/datasets";
import { plotSourceSchema } from "../../api/plotSource";
import {
  apiPathSchema,
  plotRunAcceptedSchema,
  plotRunSnapshotSchema,
  assistantTurnSnapshotSchema,
  type ParameterValues,
} from "../../api/schemas/plotRun";

export const NODE_WIDTH = 264;
export const NODE_HEIGHT = 248;
export const MIN_ZOOM = 0.2;
export const MAX_ZOOM = 2;

const pointSchema = z.object({
  x: z.number().finite(),
  y: z.number().finite(),
});
const parameterValues = z.record(
  z.string(),
  z.union([z.boolean(), z.number().finite(), z.string()]),
);
const nodeBase = {
  id: z.string(),
  label: z.string(),
  title: z.string(),
  position: pointSchema,
};
export const dataNodeSchema = z.object({
  ...nodeBase,
  type: z.literal("data"),
  dataset: datasetSchema,
  summary: z.string(),
});
export const plotNodeSchema = z.object({
  ...nodeBase,
  type: z.literal("plot"),
  sourceDataNodeId: z.string(),
  sourceDatasetId: z.string(),
  sourceDatasetRevisionId: z.string().nullable(),
  parentPlotId: z.string().nullable(),
  prompt: z.string(),
  createdAt: z.string(),
  status: z.enum([
    "running",
    "completed",
    "failed",
    "cancelled",
    "awaiting_input",
    "awaiting_approval",
  ]),
  request: z.object({
    id: z.string(),
    baseVersionId: z.string().optional(),
    plotId: z.string().optional(),
    changes: parameterValues,
    mode: z.enum(["language", "parameters"]),
  }),
  parameters: parameterValues,
  run: plotRunAcceptedSchema.nullable(),
  assistant: z
    .object({
      turnId: z.string(),
      status: apiPathSchema,
      cancel: apiPathSchema.nullable(),
    })
    .nullable(),
  assistantSnapshot: assistantTurnSnapshotSchema.nullable(),
  snapshot: plotRunSnapshotSchema.nullable(),
  source: plotSourceSchema.nullable(),
  error: z.string().nullable(),
});
const graphSchema = z.object({
  schemaVersion: z.literal(1),
  projectId: z.string(),
  nodes: z.array(
    z.discriminatedUnion("type", [dataNodeSchema, plotNodeSchema]),
  ),
  viewport: pointSchema.extend({
    zoom: z.number().min(MIN_ZOOM).max(MAX_ZOOM),
  }),
  selectedId: z.string().nullable(),
  drafts: z.record(
    z.string(),
    z.object({ prompt: z.string(), parameters: parameterValues }),
  ),
});
export type DataNode = z.infer<typeof dataNodeSchema>;
export type PlotNode = z.infer<typeof plotNodeSchema>;
export type CanvasNode = DataNode | PlotNode;
export type CanvasGraph = z.infer<typeof graphSchema>;
export type Point = z.infer<typeof pointSchema>;
export type Viewport = CanvasGraph["viewport"];
export type NodeDraft = CanvasGraph["drafts"][string];

export function emptyGraph(projectId: string): CanvasGraph {
  return {
    schemaVersion: 1,
    projectId,
    nodes: [],
    viewport: { x: 72, y: 100, zoom: 1 },
    selectedId: null,
    drafts: {},
  };
}
export function storageKey(projectId: string) {
  return `vis-platform.canvas.v1.${projectId}`;
}
export function readGraph(projectId: string): CanvasGraph {
  try {
    const parsed = graphSchema.safeParse(
      JSON.parse(window.localStorage.getItem(storageKey(projectId)) ?? "null"),
    );
    if (parsed.success && parsed.data.projectId === projectId)
      return parsed.data;
  } catch {
    /* Storage is optional. */
  }
  return emptyGraph(projectId);
}
export function datasetSummary(dataset: Dataset): string {
  const objects = dataset.objects ?? [];
  const table = objects.find((object) => object.dimensions?.length);
  return table
    ? `${table.dimensions![0]!.toLocaleString()} rows · ${table.dimensions![1] ?? table.columns?.length ?? 0} columns${objects.length > 1 ? ` · ${objects.length} objects` : ""}`
    : `${objects.length} ${objects.length === 1 ? "object" : "objects"} · ${dataset.state ?? "ready"}`;
}
export function nextPosition(nodes: CanvasNode[], parent?: CanvasNode): Point {
  const x = parent ? parent.position.x + NODE_WIDTH + 104 : 0;
  let y = parent?.position.y ?? 0;
  while (
    nodes.some(
      (node) =>
        Math.abs(node.position.x - x) < NODE_WIDTH + 40 &&
        Math.abs(node.position.y - y) < NODE_HEIGHT + 40,
    )
  )
    y += NODE_HEIGHT + 56;
  return { x, y };
}
export function addDataNode(graph: CanvasGraph, dataset: Dataset): CanvasGraph {
  const existing = graph.nodes.find(
    (node) =>
      node.type === "data" &&
      node.dataset.dataset_id === dataset.dataset_id &&
      node.dataset.revision_id === dataset.revision_id,
  );
  if (existing) return { ...graph, selectedId: existing.id };
  const node: DataNode = {
    id: createMutationId(),
    type: "data",
    label: `D${graph.nodes.filter((n) => n.type === "data").length + 1}`,
    title: dataset.name,
    dataset,
    summary: datasetSummary(dataset),
    position: nextPosition(graph.nodes),
  };
  return { ...graph, nodes: [...graph.nodes, node], selectedId: node.id };
}
export function createPlotNode(
  graph: CanvasGraph,
  parent: CanvasNode,
  prompt: string,
  changes: ParameterValues,
): PlotNode {
  const dataset = parent.type === "data" ? parent.dataset : null;
  const source = parent.type === "plot" ? parent.snapshot?.result : null;
  return {
    id: createMutationId(),
    type: "plot",
    label: `P${graph.nodes.filter((node) => node.type === "plot").length + 1}`,
    title: prompt.trim()
      ? prompt.trim().slice(0, 70)
      : `Refinement of ${parent.label}`,
    position: nextPosition(graph.nodes, parent),
    sourceDataNodeId:
      parent.type === "data" ? parent.id : parent.sourceDataNodeId,
    sourceDatasetId:
      dataset?.dataset_id ?? (parent as PlotNode).sourceDatasetId,
    sourceDatasetRevisionId:
      dataset?.revision_id ??
      (parent.type === "plot" ? parent.sourceDatasetRevisionId : null),
    parentPlotId: parent.type === "plot" ? parent.id : null,
    prompt: prompt.trim(),
    createdAt: new Date().toISOString(),
    status: "running",
    request: {
      id: createMutationId(),
      baseVersionId: source?.version_id,
      plotId: source?.plot_id,
      changes: { ...changes },
      mode: !prompt.trim() && source ? "parameters" : "language",
    },
    parameters: {
      ...(parent.type === "plot" ? parent.parameters : {}),
      ...changes,
    },
    run: null,
    assistant: null,
    assistantSnapshot: null,
    snapshot: null,
    source: null,
    error: null,
  };
}
export function connections(nodes: CanvasNode[]) {
  return nodes.flatMap((node) =>
    node.type === "plot"
      ? [
          {
            id: node.id,
            source: node.parentPlotId ?? node.sourceDataNodeId,
            target: node.id,
            kind: node.parentPlotId ? "Refinement" : "Creation",
          },
        ]
      : [],
  );
}
export function zoomAt(view: Viewport, point: Point, zoom: number): Viewport {
  const next = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, zoom));
  return {
    x: point.x - ((point.x - view.x) * next) / view.zoom,
    y: point.y - ((point.y - view.y) * next) / view.zoom,
    zoom: next,
  };
}
export function fitNodes(
  nodes: CanvasNode[],
  width: number,
  height: number,
): Viewport {
  if (!nodes.length || width <= 0 || height <= 0)
    return { x: 72, y: 100, zoom: 1 };
  const left = Math.min(...nodes.map((n) => n.position.x));
  const top = Math.min(...nodes.map((n) => n.position.y));
  const right = Math.max(...nodes.map((n) => n.position.x + NODE_WIDTH));
  const bottom = Math.max(...nodes.map((n) => n.position.y + NODE_HEIGHT));
  const zoom = Math.max(
    MIN_ZOOM,
    Math.min(
      1,
      (width - 100) / (right - left),
      (height - 160) / (bottom - top),
    ),
  );
  return {
    x: (width - (right - left) * zoom) / 2 - left * zoom,
    y: (height - 80 - (bottom - top) * zoom) / 2 - top * zoom,
    zoom,
  };
}
export function isActive(node: PlotNode) {
  return ["running", "awaiting_input", "awaiting_approval"].includes(
    node.status,
  );
}
