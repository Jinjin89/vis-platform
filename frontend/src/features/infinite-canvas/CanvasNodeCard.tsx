import { useState } from "react";
import { resolveArtifactUrl } from "../../api/client";
import type { CanvasNode, PlotNode } from "./model";

export const statusLabels: Record<PlotNode["status"], string> = {
  running: "Running",
  completed: "Ready",
  failed: "Failed",
  cancelled: "Cancelled",
  awaiting_input: "Needs input",
  awaiting_approval: "Needs approval",
};
export function CanvasImage({
  href,
  description,
}: {
  href: string;
  description: string;
}) {
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  return failed ? (
    <div className="canvas-image-error">
      <span>Preview could not load.</span>
      <button
        type="button"
        onClick={() => {
          setFailed(false);
          setAttempt(attempt + 1);
        }}
      >
        Reload image
      </button>
    </div>
  ) : (
    <img
      key={attempt}
      src={resolveArtifactUrl(href)}
      alt={description}
      draggable={false}
      onError={() => setFailed(true)}
    />
  );
}
export function NodeStatus({ node }: { node: PlotNode }) {
  return (
    <span className="canvas-node-status" data-status={node.status}>
      <i />
      {statusLabels[node.status]}
    </span>
  );
}
export function CanvasNodeCard({
  node,
  selected,
  onSelect,
  onCompose,
}: {
  node: CanvasNode;
  selected: boolean;
  onSelect: () => void;
  onCompose: () => void;
}) {
  const result = node.type === "plot" ? node.snapshot?.result : null;
  return (
    <article
      className="canvas-node"
      data-canvas-node={node.id}
      data-kind={node.type}
      data-selected={selected}
      style={{ left: node.position.x, top: node.position.y }}
      tabIndex={0}
      aria-label={`${node.label}: ${node.title}`}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (
          event.target === event.currentTarget &&
          ["Enter", " "].includes(event.key)
        ) {
          event.preventDefault();
          onSelect();
        }
      }}
    >
      {node.type === "plot" ? (
        <span className="canvas-port canvas-port-in" />
      ) : null}
      <header>
        <span className="canvas-node-kind">
          {node.type === "data" ? "▤" : "◩"}
        </span>
        <span>{node.type === "data" ? "DATASET" : "PLOT"}</span>
        <span className="canvas-node-id">{node.label}</span>
      </header>
      <h3 title={node.title}>{node.title}</h3>
      {node.type === "data" ? (
        <div className="canvas-data-body">
          <strong>{node.summary}</strong>
          <p>
            {node.dataset.description ||
              "Select this dataset to start a new plot branch."}
          </p>
          <div className="canvas-column-tags">
            {(node.dataset.objects ?? [])
              .flatMap((o) => o.columns ?? [])
              .slice(0, 3)
              .map((c, i) => (
                <span key={c.name + i}>{c.name}</span>
              ))}
          </div>
          {node.dataset.contains_demo_data ? (
            <small>Demonstration data</small>
          ) : null}
        </div>
      ) : (
        <div className="canvas-node-thumbnail">
          {result ? (
            <CanvasImage
              key={result.preview.href}
              href={result.preview.href}
              description={node.title}
            />
          ) : (
            <div className="canvas-node-placeholder" data-status={node.status}>
              <span
                className={
                  node.status === "running"
                    ? "canvas-spinner"
                    : "canvas-placeholder-symbol"
                }
              >
                {node.status === "running"
                  ? ""
                  : node.status === "failed"
                    ? "!"
                    : "…"}
              </span>
              <span>
                {node.status === "running"
                  ? "Creating your figure"
                  : statusLabels[node.status]}
              </span>
            </div>
          )}
        </div>
      )}
      <footer>
        {node.type === "plot" ? (
          <NodeStatus node={node} />
        ) : (
          <span className="canvas-data-ready">● Dataset</span>
        )}
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onCompose();
          }}
          disabled={node.type === "plot" && node.status !== "completed"}
        >
          {node.type === "data" ? "Create plot" : "Refine"}{" "}
          <span aria-hidden="true">↗</span>
        </button>
      </footer>
      <span className="canvas-port canvas-port-out" />
    </article>
  );
}
