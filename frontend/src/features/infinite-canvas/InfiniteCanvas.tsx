import { useEffect, useId, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { CanvasNodeCard } from "./CanvasNodeCard";
import {
  connections,
  fitNodes,
  zoomAt,
  NODE_HEIGHT,
  NODE_WIDTH,
} from "./model";
import type { CanvasNode, Point, Viewport } from "./model";

type Props = {
  nodes: CanvasNode[];
  selectedId: string | null;
  viewport: Viewport;
  onViewport: (view: Viewport) => void;
  onSelect: (id: string | null) => void;
  onMove: (id: string, position: Point) => void;
  onCompose: (id: string) => void;
  children?: ReactNode;
};
export function InfiniteCanvas({
  nodes,
  selectedId,
  viewport,
  onViewport,
  onSelect,
  onMove,
  onCompose,
  children,
}: Props) {
  const surface = useRef<HTMLDivElement>(null);
  const current = useRef({ viewport, onViewport });
  current.current = { viewport, onViewport };
  const arrow = useId().replace(/:/g, "");
  const [dragging, setDragging] = useState(false);
  const [hand, setHand] = useState(false);
  const space = useRef(false);
  const pointers = useRef(new Map<number, Point>());
  const drag = useRef<{
    start: Point;
    origin: Point;
    view: Viewport;
    nodeId?: string;
    distance?: number;
  } | null>(null);
  const edges = connections(nodes);
  function local(client: Point) {
    const bounds = surface.current!.getBoundingClientRect();
    return { x: client.x - bounds.left, y: client.y - bounds.top };
  }
  function fit() {
    const bounds = surface.current?.getBoundingClientRect();
    if (bounds) onViewport(fitNodes(nodes, bounds.width, bounds.height));
  }
  function zoom(factor: number) {
    const bounds = surface.current?.getBoundingClientRect();
    if (bounds)
      onViewport(
        zoomAt(
          viewport,
          { x: bounds.width / 2, y: bounds.height / 2 },
          viewport.zoom * factor,
        ),
      );
  }
  useEffect(() => {
    const element = surface.current!;
    function wheel(event: WheelEvent) {
      if ((event.target as Element).closest("button, textarea, input")) return;
      event.preventDefault();
      const { viewport: view, onViewport: update } = current.current;
      const bounds = element.getBoundingClientRect();
      if (event.ctrlKey || event.metaKey)
        update(
          zoomAt(
            view,
            { x: event.clientX - bounds.left, y: event.clientY - bounds.top },
            view.zoom * Math.exp(-event.deltaY * 0.008),
          ),
        );
      else {
        const unit =
          event.deltaMode === 1
            ? 16
            : event.deltaMode === 2
              ? bounds.height
              : 1;
        update({
          ...view,
          x: view.x - (event.shiftKey ? event.deltaY : event.deltaX) * unit,
          y: view.y - (event.shiftKey ? 0 : event.deltaY) * unit,
        });
      }
    }
    function clearSpace() {
      space.current = false;
    }
    element.addEventListener("wheel", wheel, { passive: false });
    window.addEventListener("blur", clearSpace);
    return () => {
      element.removeEventListener("wheel", wheel);
      window.removeEventListener("blur", clearSpace);
    };
  }, []);
  function pointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (
      ![0, 1].includes(event.button) ||
      (event.target as Element).closest(
        "button, a, textarea, input, .canvas-overlay",
      )
    )
      return;
    const point = local({ x: event.clientX, y: event.clientY });
    pointers.current.set(event.pointerId, point);
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()] as [Point, Point];
      drag.current = {
        start: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
        origin: viewport,
        view: viewport,
        distance: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)),
      };
    } else {
      const nodeId =
        !hand && !space.current && event.button !== 1
          ? (event.target as Element).closest<HTMLElement>("[data-canvas-node]")
              ?.dataset.canvasNode
          : undefined;
      const node = nodes.find((n) => n.id === nodeId);
      if (node) onSelect(node.id);
      event.currentTarget.focus({ preventScroll: true });
      drag.current = {
        start: point,
        origin: node?.position ?? viewport,
        view: viewport,
        nodeId: node?.id,
      };
    }
    setDragging(true);
  }
  function pointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    if (!pointers.current.has(event.pointerId) || !drag.current) return;
    const point = local({ x: event.clientX, y: event.clientY });
    pointers.current.set(event.pointerId, point);
    const state = drag.current;
    if (state.distance && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()] as [Point, Point];
      const center = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      const view = zoomAt(
        state.view,
        state.start,
        (state.view.zoom * Math.hypot(a.x - b.x, a.y - b.y)) / state.distance,
      );
      onViewport({
        ...view,
        x: view.x + center.x - state.start.x,
        y: view.y + center.y - state.start.y,
      });
    } else if (state.nodeId)
      onMove(state.nodeId, {
        x: state.origin.x + (point.x - state.start.x) / viewport.zoom,
        y: state.origin.y + (point.y - state.start.y) / viewport.zoom,
      });
    else
      onViewport({
        ...state.view,
        x: state.origin.x + point.x - state.start.x,
        y: state.origin.y + point.y - state.start.y,
      });
  }
  function pointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    pointers.current.delete(event.pointerId);
    if (pointers.current.size === 1) {
      const point = [...pointers.current.values()][0]!;
      drag.current = { start: point, origin: viewport, view: viewport };
    } else {
      drag.current = null;
      setDragging(false);
    }
  }
  return (
    <div
      className="infinite-canvas"
      ref={surface}
      role="region"
      aria-label="Infinite plotting canvas"
      tabIndex={0}
      data-dragging={dragging}
      data-hand={hand}
      style={{
        backgroundPosition: `${viewport.x}px ${viewport.y}px`,
        backgroundSize: `${24 * viewport.zoom}px ${24 * viewport.zoom}px`,
      }}
      onPointerDown={pointerDown}
      onPointerMove={pointerMove}
      onPointerUp={pointerUp}
      onPointerCancel={pointerUp}
      onLostPointerCapture={pointerUp}
      onKeyUp={(event) => {
        if (event.code === "Space") space.current = false;
      }}
      onKeyDown={(event) => {
        if (
          (event.target as Element).closest(
            "button, a, textarea, input, select",
          )
        )
          return;
        if (event.code === "Space") {
          event.preventDefault();
          space.current = true;
        } else if (event.key.toLowerCase() === "f") {
          event.preventDefault();
          fit();
        } else if (["+", "="].includes(event.key)) {
          event.preventDefault();
          zoom(1.2);
        } else if (event.key === "-") {
          event.preventDefault();
          zoom(1 / 1.2);
        } else if (event.key === "Escape") onSelect(null);
        else if (event.key.startsWith("Arrow")) {
          event.preventDefault();
          const dx =
            event.key === "ArrowLeft"
              ? -24
              : event.key === "ArrowRight"
                ? 24
                : 0;
          const dy =
            event.key === "ArrowUp" ? -24 : event.key === "ArrowDown" ? 24 : 0;
          const node = nodes.find(
            (n) => n.id === (event.target as HTMLElement).dataset.canvasNode,
          );
          if (node)
            onMove(node.id, {
              x: node.position.x + dx / viewport.zoom,
              y: node.position.y + dy / viewport.zoom,
            });
          else
            onViewport({ ...viewport, x: viewport.x + dx, y: viewport.y + dy });
        }
      }}
    >
      <div
        className="canvas-world"
        style={{
          transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`,
        }}
      >
        <svg
          className="canvas-connections"
          width="1"
          height="1"
          aria-label="Plot creation and refinement connections"
        >
          <defs>
            <marker
              id={arrow}
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
            </marker>
          </defs>
          {edges.map((edge) => {
            const from = nodes.find((n) => n.id === edge.source);
            const to = nodes.find((n) => n.id === edge.target);
            if (!from || !to) return null;
            const x1 = from.position.x + NODE_WIDTH + 5,
              y1 = from.position.y + NODE_HEIGHT / 2;
            const x2 = to.position.x - 6,
              y2 = to.position.y + NODE_HEIGHT / 2;
            const curve = Math.max(60, Math.abs(x2 - x1) / 2);
            return (
              <g
                key={edge.id}
                data-connection={edge.id}
                data-active={selectedId === to.id || selectedId === from.id}
              >
                <title>{`${from.label} → ${to.label}: ${edge.kind}`}</title>
                <path
                  d={`M ${x1} ${y1} C ${x1 + curve} ${y1}, ${x2 - curve} ${y2}, ${x2} ${y2}`}
                  markerEnd={`url(#${arrow})`}
                />
              </g>
            );
          })}
        </svg>
        {nodes.map((node) => (
          <CanvasNodeCard
            key={node.id}
            node={node}
            selected={selectedId === node.id}
            onSelect={() => onSelect(node.id)}
            onCompose={() => onCompose(node.id)}
          />
        ))}
      </div>
      {!nodes.length ? (
        <div className="canvas-empty canvas-overlay">
          <div className="canvas-empty-diagram" aria-hidden="true">
            <span>▤</span>
            <i>→</i>
            <span>◩</span>
            <i>→</i>
            <span>◩</span>
          </div>
          <p className="canvas-eyebrow">ROOM TO EXPLORE</p>
          <h1>One dataset. Many directions.</h1>
          <p>
            Add a dataset, describe a plot, and follow your ideas.
            <br />
            Every refinement becomes a new branch.
          </p>
          <span className="canvas-empty-hint">
            Start with <strong>Data</strong> in the toolbar above
          </span>
        </div>
      ) : null}
      <div
        className="canvas-navigation canvas-overlay"
        role="group"
        aria-label="Canvas navigation"
      >
        <button
          type="button"
          aria-label="Hand tool"
          aria-pressed={hand}
          onClick={() => setHand(!hand)}
        >
          ✥
        </button>
        <span />
        <button
          type="button"
          aria-label="Zoom out canvas"
          disabled={viewport.zoom <= 0.2}
          onClick={() => zoom(1 / 1.2)}
        >
          −
        </button>
        <output aria-label="Canvas zoom">
          {Math.round(viewport.zoom * 100)}%
        </output>
        <button
          type="button"
          aria-label="Zoom in canvas"
          disabled={viewport.zoom >= 2}
          onClick={() => zoom(1.2)}
        >
          +
        </button>
        <span />
        <button type="button" aria-label="Fit all nodes" onClick={fit}>
          Fit
        </button>
      </div>
      <div className="canvas-gesture-hint canvas-overlay">
        Drag to pan · Ctrl + scroll to zoom · F to fit
      </div>
      {children}
    </div>
  );
}
