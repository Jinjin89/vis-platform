import { afterAll, afterEach, beforeAll, expect, test, vi } from "vitest";
import { datasetSchema } from "../src/api/schemas/datasets";
import {
  addDataNode,
  connections,
  createPlotNode,
  emptyGraph,
  fitNodes,
  readCanvases,
  readGraph,
  storageKey,
  zoomAt,
} from "../src/features/infinite-canvas/model";

const dataset = datasetSchema.parse({
  schema_version: "1.0",
  dataset_id: "dataset_1",
  project_id: "project_1",
  name: "Treatment study",
  description: "Measurements by treatment",
  source_kind: "upload",
  source_id: "source_1",
  revision_id: "revision_1",
  state: "ready",
  created_at: "2026-09-15T00:00:00Z",
  updated_at: "2026-09-15T00:00:00Z",
  objects: [],
});
// Use DOM Storage instead of the host Node runtime's native localStorage.
beforeAll(() => vi.stubGlobal("localStorage", window.sessionStorage));
afterEach(() => window.localStorage.clear());
afterAll(() => vi.unstubAllGlobals());

test("one dataset creates independent branches and each child retains its source", () => {
  let graph = addDataNode(emptyGraph("project_1"), dataset);
  const data = graph.nodes[0]!;
  const first = createPlotNode(graph, data, "Compare treatments", {});
  graph = { ...graph, nodes: [...graph.nodes, first] };
  const second = createPlotNode(graph, data, "Show a distribution", {});
  graph = { ...graph, nodes: [...graph.nodes, second] };
  const child = createPlotNode(graph, first, "Show points", {
    title: "Refined",
  });
  graph = { ...graph, nodes: [...graph.nodes, child] };
  expect(first.position).not.toEqual(second.position);
  expect(first.parentPlotId).toBeNull();
  expect(second.parentPlotId).toBeNull();
  expect(child.parentPlotId).toBe(first.id);
  expect(child.sourceDatasetId).toBe(dataset.dataset_id);
  expect(child.sourceDatasetRevisionId).toBe(dataset.revision_id);
  expect(first.parameters).toEqual({});
  expect(child.parameters).toEqual({ title: "Refined" });
  expect(
    connections(graph.nodes).map((edge) => [edge.source, edge.target]),
  ).toEqual([
    [data.id, first.id],
    [data.id, second.id],
    [first.id, child.id],
  ]);
});

test("browser recovery retains drafts and positions and rejects corrupted or foreign graphs", () => {
  const graph = addDataNode(emptyGraph("project_1"), dataset);
  graph.nodes[0]!.position = { x: -1300, y: 850 };
  graph.drafts[graph.nodes[0]!.id] = {
    prompt: "Compare groups",
    parameters: {},
  };
  window.localStorage.setItem(
    storageKey("project_1", "canvas_1"),
    JSON.stringify(graph),
  );
  expect(readGraph("project_1", "canvas_1")).toEqual(graph);
  expect(readGraph("project_1", "canvas_2").nodes).toEqual([]);
  expect(readGraph("project_2", "canvas_1").nodes).toEqual([]);
  window.localStorage.setItem(
    storageKey("project_2", "canvas_1"),
    JSON.stringify(graph),
  );
  expect(readGraph("project_2", "canvas_1").nodes).toEqual([]);
  window.localStorage.setItem(storageKey("project_1", "canvas_1"), "{broken");
  expect(readGraph("project_1", "canvas_1").nodes).toEqual([]);
});

test("a project always has a canvas, and one saved before canvases were listed becomes the first", () => {
  const [fresh] = readCanvases("project_2");
  expect(fresh).toMatchObject({ title: "Canvas 1", nodes: 0 });
  const graph = addDataNode(emptyGraph("project_1"), dataset);
  window.localStorage.setItem(
    "vis-platform.canvas.v1.project_1",
    JSON.stringify(graph),
  );
  const canvases = readCanvases("project_1");
  expect(canvases).toHaveLength(1);
  expect(canvases[0]).toMatchObject({ title: "Canvas 1", nodes: 1 });
  expect(readGraph("project_1", canvases[0]!.id)).toEqual(graph);
  expect(
    window.localStorage.getItem("vis-platform.canvas.v1.project_1"),
  ).toBeNull();
});

test("zoom preserves the point under the pointer and fit includes negative coordinates", () => {
  const point = { x: 370, y: 250 };
  const before = { x: -80, y: 70, zoom: 0.8 };
  const after = zoomAt(before, point, 1.6);
  expect((point.x - after.x) / after.zoom).toBe(
    (point.x - before.x) / before.zoom,
  );
  expect((point.y - after.y) / after.zoom).toBe(
    (point.y - before.y) / before.zoom,
  );
  const graph = addDataNode(emptyGraph("project_1"), dataset);
  graph.nodes[0]!.position = { x: -1000, y: -500 };
  const fit = fitNodes(graph.nodes, 1000, 700);
  expect(-1000 * fit.zoom + fit.x).toBeGreaterThan(0);
  expect(-500 * fit.zoom + fit.y).toBeGreaterThan(0);
});
