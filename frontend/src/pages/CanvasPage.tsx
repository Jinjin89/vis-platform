import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import { request } from "../api/client";
import { datasetSchema } from "../api/schemas/datasets";
import type { ParameterValues } from "../api/schemas/plotRun";
import { useProject } from "../app/useProject";
import { SessionSidebar } from "../components/SessionSidebar";
import { WorkspaceSwitcher } from "../components/WorkspaceSwitcher";
import { DatasetSelector } from "../features/datasets/DatasetSelector";
import { validValue } from "../features/plot-run/ParameterForm";
import { InfiniteCanvas } from "../features/infinite-canvas/InfiniteCanvas";
import { CanvasInspector } from "../features/infinite-canvas/CanvasInspector";
import { NodeExecution } from "../features/infinite-canvas/NodeExecution";
import {
  addDataNode,
  createPlotNode,
  datasetSummary,
  isActive,
  newCanvas,
  NODE_HEIGHT,
  NODE_WIDTH,
  readCanvases,
  readGraph,
  sortCanvases,
  storageKey,
  writeCanvases,
} from "../features/infinite-canvas/model";
import type {
  CanvasEntry,
  CanvasGraph,
  CanvasNode,
  NodeDraft,
  PlotNode,
} from "../features/infinite-canvas/model";
import "../features/infinite-canvas/infiniteCanvas.css";

export function CanvasPage() {
  const project = useProject(true);
  return (
    <main className="app-shell canvas-shell">
      <header className="top-bar">
        <div className="brand" aria-label="Vis Platform">
          <span className="brand-name">vis.</span>
        </div>
        <div className="project-title">
          <span className="project-kicker">Research studio</span>
          <strong>Untitled study</strong>
        </div>
        <WorkspaceSwitcher />
      </header>
      {project.projectId ? (
        <CanvasSessions key={project.projectId} projectId={project.projectId} />
      ) : (
        <div className="canvas-loading">
          {project.error ? (
            <>
              <p role="alert">{project.error}</p>
              <button type="button" onClick={project.retry}>
                Retry opening canvas
              </button>
            </>
          ) : (
            <p>Opening your canvas…</p>
          )}
        </div>
      )}
    </main>
  );
}

/** Each canvas is a separate exploration; the latest one opens by default. */
function CanvasSessions({ projectId }: { projectId: string }) {
  const [params, setParams] = useSearchParams();
  const [canvases, setCanvases] = useState(() => readCanvases(projectId));
  const active =
    canvases.find((canvas) => canvas.id === params.get("id")) ?? canvases[0]!;
  useEffect(() => writeCanvases(projectId, canvases), [projectId, canvases]);
  const edited = useCallback(
    (id: string, nodes: number) =>
      setCanvases((current) =>
        sortCanvases(
          current.map((canvas) =>
            canvas.id === id
              ? { ...canvas, nodes, updatedAt: new Date().toISOString() }
              : canvas,
          ),
        ),
      ),
    [],
  );
  return (
    <div className="session-layout">
      <SessionSidebar
        label="Canvases"
        newLabel="New canvas"
        items={canvases.map((canvas: CanvasEntry) => ({
          id: canvas.id,
          title: canvas.title,
          detail: `${canvas.nodes} ${canvas.nodes === 1 ? "node" : "nodes"} · ${new Date(canvas.updatedAt).toLocaleDateString()}`,
        }))}
        activeId={active.id}
        emptyText="Your canvases will appear here."
        onSelect={(id) => setParams({ id })}
        onNew={() => {
          const canvas = newCanvas(canvases);
          setCanvases([canvas, ...canvases]);
          setParams({ id: canvas.id });
        }}
      />
      <CanvasWorkspace
        key={active.id}
        projectId={projectId}
        canvasId={active.id}
        onEdited={edited}
      />
    </div>
  );
}

function CanvasWorkspace({
  projectId,
  canvasId,
  onEdited,
}: {
  projectId: string;
  canvasId: string;
  onEdited: (canvasId: string, nodes: number) => void;
}) {
  const [graph, setGraph] = useState<CanvasGraph>(() =>
    readGraph(projectId, canvasId),
  );
  const graphRef = useRef(graph);
  graphRef.current = graph;
  const opened = useRef(graph.nodes);
  useEffect(() => {
    if (graph.nodes !== opened.current) onEdited(canvasId, graph.nodes.length);
  }, [graph.nodes, canvasId, onEdited]);
  const [storageError, setStorageError] = useState(false);
  const [datasetIds, setDatasetIds] = useState<string[]>(() =>
    graph.nodes.flatMap((node) =>
      node.type === "data" &&
      ["processing", "uploading"].includes(node.dataset.state ?? "ready")
        ? [node.dataset.dataset_id]
        : [],
    ),
  );
  const [outline, setOutline] = useState(false);
  const frame = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const lastCreated = useRef<string | null>(null);
  const knownDataNodes = useRef(
    new Set(
      graph.nodes.filter((node) => node.type === "data").map((node) => node.id),
    ),
  );
  useEffect(() => {
    const added = graph.nodes.filter(
      (node) => node.type === "data" && !knownDataNodes.current.has(node.id),
    );
    for (const node of added) knownDataNodes.current.add(node.id);
    if (added.length) focusNode(added[added.length - 1]!);
  }, [graph.nodes]);
  const catalog = useQuery({
    queryKey: ["canvas-datasets", projectId, datasetIds],
    queryFn: () =>
      Promise.all(
        datasetIds.map((id) =>
          request(
            `/api/v1/data-bundles/${encodeURIComponent(id)}?project_id=${encodeURIComponent(projectId)}`,
            datasetSchema,
          ),
        ),
      ),
    enabled: !!datasetIds.length,
    refetchInterval: (query) =>
      query.state.data?.some(
        (d) => d.state === "processing" || d.state === "uploading",
      )
        ? 1000
        : false,
  });
  useEffect(() => {
    if (catalog.data)
      setGraph((current) => {
        let next = current;
        for (const dataset of catalog.data!) {
          // Imported datasets may still be processing; keep their visible summary current.
          const existing = next.nodes.find(
            (n) =>
              n.type === "data" &&
              n.dataset.dataset_id === dataset.dataset_id &&
              (n.dataset.revision_id === dataset.revision_id ||
                !n.dataset.revision_id),
          );
          if (existing?.type === "data") {
            next = {
              ...next,
              nodes: next.nodes.map((n) =>
                n.id === existing.id
                  ? {
                      ...existing,
                      dataset,
                      title: dataset.name,
                      summary: datasetSummary(dataset),
                    }
                  : n,
              ),
            };
          } else next = addDataNode(next, dataset);
        }
        return next;
      });
  }, [catalog.data]);
  useEffect(() => {
    const timeout = window.setTimeout(() => {
      try {
        window.localStorage.setItem(
          storageKey(projectId, canvasId),
          JSON.stringify(graph),
        );
        setStorageError(false);
      } catch {
        setStorageError(true);
      }
    }, 180);
    return () => clearTimeout(timeout);
  }, [graph, projectId, canvasId]);
  useEffect(() => {
    const save = () => {
      try {
        window.localStorage.setItem(
          storageKey(projectId, canvasId),
          JSON.stringify(graphRef.current),
        );
      } catch {
        /* The visible storage notice handles unavailable storage. */
      }
    };
    window.addEventListener("pagehide", save);
    return () => {
      save();
      window.removeEventListener("pagehide", save);
    };
  }, [projectId, canvasId]);
  const updatePlot = useCallback((id: string, update: Partial<PlotNode>) => {
    setGraph((current) => ({
      ...current,
      nodes: current.nodes.map((node) =>
        node.id === id && node.type === "plot" ? { ...node, ...update } : node,
      ),
    }));
  }, []);
  const selected = graph.nodes.find((node) => node.id === graph.selectedId);
  const draft: NodeDraft = (selected && graph.drafts[selected.id]) || {
    prompt: "",
    parameters: {},
  };
  function updateDraft(id: string, update: Partial<NodeDraft>) {
    setGraph((current) => ({
      ...current,
      drafts: {
        ...current.drafts,
        [id]: {
          ...(current.drafts[id] ?? { prompt: "", parameters: {} }),
          ...update,
        },
      },
    }));
  }
  function select(id: string | null) {
    setGraph((current) => ({ ...current, selectedId: id }));
  }
  function focusNode(node: CanvasNode) {
    const rect = frame.current
      ?.querySelector(".infinite-canvas")
      ?.getBoundingClientRect();
    if (!rect) return;
    setGraph((current) => ({
      ...current,
      selectedId: node.id,
      viewport: {
        ...current.viewport,
        x:
          rect.width / 2 -
          (node.position.x + NODE_WIDTH / 2) * current.viewport.zoom,
        y:
          (rect.height - 160) / 2 -
          (node.position.y + NODE_HEIGHT / 2) * current.viewport.zoom,
      },
    }));
  }
  function compose(id: string) {
    select(id);
    window.setTimeout(() => composer.current?.focus(), 0);
  }
  const ready =
    selected?.type === "data"
      ? selected.dataset.state === "ready" &&
        (selected.dataset.objects ?? []).some((o) => o.readiness === "ready")
      : selected?.type === "plot" &&
        selected.status === "completed" &&
        !!selected.snapshot?.result;
  const validDraft =
    selected?.type !== "plot" ||
    (selected.snapshot?.result?.controls ?? []).every((control) =>
      validValue(control, draft.parameters[control.id] ?? control.value),
    );
  function create(prompt: string, changes: ParameterValues): boolean {
    if (
      !selected ||
      !ready ||
      !validDraft ||
      (!prompt.trim() && !Object.keys(changes).length)
    )
      return false;
    const fingerprint = JSON.stringify([selected.id, prompt, changes]);
    if (lastCreated.current === fingerprint) return false;
    lastCreated.current = fingerprint;
    const node = createPlotNode(graphRef.current, selected, prompt, changes);
    setGraph((current) => ({
      ...current,
      nodes: [...current.nodes, node],
      selectedId: node.id,
      drafts: {
        ...current.drafts,
        [selected.id]: { prompt: "", parameters: {} },
      },
    }));
    window.setTimeout(() => {
      focusNode(node);
      lastCreated.current = null;
    }, 0);
    return true;
  }
  function reuseInstructions() {
    if (selected?.type !== "plot") return;
    const source = selected.parentPlotId ?? selected.sourceDataNodeId;
    updateDraft(source, {
      prompt: selected.prompt,
      parameters: selected.request.changes,
    });
    compose(source);
  }
  const runningCount = graph.nodes.filter(
    (node) => node.type === "plot" && isActive(node),
  ).length;
  return (
    <div className="canvas-workspace" ref={frame}>
      <div className="canvas-topline">
        <div className="canvas-heading">
          <strong>Plot canvas</strong>
          <span>
            {graph.nodes.length} nodes
            {runningCount ? ` · ${runningCount} running` : ""}
          </span>
        </div>
        <div className="canvas-toolbar">
          <button
            type="button"
            className="canvas-outline-toggle"
            aria-pressed={outline}
            onClick={() => setOutline(!outline)}
          >
            Outline
          </button>
          <DatasetSelector
            projectId={projectId}
            ensureProject={async () => projectId}
            selectedIds={datasetIds}
            resultIds={[]}
            onSelect={setDatasetIds}
            onUseResult={() => {}}
            datasetsOnly
            disabled={false}
          />
        </div>
      </div>
      {catalog.error || storageError ? (
        <div className="canvas-notice" role="status">
          {catalog.error ? (
            <>
              {catalog.error.message}{" "}
              <button type="button" onClick={() => void catalog.refetch()}>
                Retry adding data
              </button>
            </>
          ) : (
            "Browser storage is unavailable. Keep this page open to retain the canvas layout."
          )}
        </div>
      ) : null}
      <div
        className="canvas-main"
        data-inspector={!!selected}
        data-outline={outline}
      >
        {outline ? (
          <nav className="canvas-outline" aria-label="Canvas nodes">
            <h2>EXPLORATIONS</h2>
            {graph.nodes.length ? (
              graph.nodes.map((node) => (
                <button
                  type="button"
                  key={node.id}
                  data-kind={node.type}
                  aria-current={selected?.id === node.id ? "true" : undefined}
                  onClick={() => focusNode(node)}
                >
                  <b>{node.label}</b>
                  <span>{node.title}</span>
                  {node.type === "plot" && node.status === "running" ? (
                    <i className="canvas-spinner" />
                  ) : null}
                </button>
              ))
            ) : (
              <p>Add data to begin.</p>
            )}
          </nav>
        ) : null}
        <InfiniteCanvas
          nodes={graph.nodes}
          selectedId={graph.selectedId}
          viewport={graph.viewport}
          onViewport={(viewport) =>
            setGraph((current) => ({ ...current, viewport }))
          }
          onSelect={select}
          onCompose={compose}
          onMove={(id, position) =>
            setGraph((current) => ({
              ...current,
              nodes: current.nodes.map((node) =>
                node.id === id ? { ...node, position } : node,
              ),
            }))
          }
        >
          {selected ? (
            <form
              className="canvas-composer canvas-overlay"
              aria-label="Canvas plot instructions"
              onSubmit={(event) => {
                event.preventDefault();
                create(draft.prompt, draft.parameters);
              }}
            >
              <div className="canvas-composer-context">
                <span>{selected.label}</span>
                <strong>
                  {selected.type === "data"
                    ? "Start a new plot branch"
                    : "Create a refinement"}
                </strong>
                {Object.keys(draft.parameters).length ? (
                  <small>
                    {Object.keys(draft.parameters).length} parameter drafts
                  </small>
                ) : null}
              </div>
              <textarea
                ref={composer}
                aria-label={
                  selected.type === "data"
                    ? "Describe a new plot"
                    : "Describe a refinement"
                }
                value={draft.prompt}
                onChange={(event) =>
                  updateDraft(selected.id, { prompt: event.target.value })
                }
                placeholder={
                  ready
                    ? selected.type === "data"
                      ? "e.g. Compare expression across treatment groups…"
                      : "e.g. Use a softer palette and show individual points…"
                    : "Select a ready dataset or completed plot to continue."
                }
                disabled={!ready}
                maxLength={9700}
                rows={2}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    (event.metaKey || event.ctrlKey)
                  ) {
                    event.preventDefault();
                    create(draft.prompt, draft.parameters);
                  }
                }}
              />
              <footer>
                <span>
                  {selected.type === "plot"
                    ? "The original plot stays in your canvas."
                    : "Each idea starts an independent branch."}
                </span>
                <button
                  type="submit"
                  disabled={
                    !ready ||
                    !validDraft ||
                    (!draft.prompt.trim() &&
                      !Object.keys(draft.parameters).length)
                  }
                >
                  {selected.type === "data"
                    ? "Create plot"
                    : "Create refinement"}{" "}
                  <span aria-hidden="true">↗</span>
                </button>
              </footer>
            </form>
          ) : null}
        </InfiniteCanvas>
        {selected ? (
          <CanvasInspector
            key={selected.id}
            node={selected}
            projectId={projectId}
            draft={draft}
            parentLabel={
              selected.type === "plot"
                ? graph.nodes.find(
                    (n) =>
                      n.id ===
                      (selected.parentPlotId ?? selected.sourceDataNodeId),
                  )?.label
                : undefined
            }
            onClose={() => select(null)}
            onDraft={(parameters) => updateDraft(selected.id, { parameters })}
            onCreate={async (changes) => create(draft.prompt, changes)}
            onReuse={reuseInstructions}
          />
        ) : null}
      </div>
      {graph.nodes
        .filter((n): n is PlotNode => n.type === "plot")
        .map((node) => (
          <NodeExecution
            key={node.id}
            node={node}
            projectId={projectId}
            onUpdate={updatePlot}
          />
        ))}
    </div>
  );
}
