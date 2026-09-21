import { useEffect, useRef, useState } from "react";
import type { PlotResult } from "../../api/schemas/plotRun";
import "./figureStage.css";

type Point = { x: number; y: number };
type FigureStageProps = {
  src: string;
  description: string;
  size?: PlotResult["figure_size"];
  containsDemoData: boolean;
  onError: () => void;
};

export function FigureStage({
  src,
  description,
  size,
  containsDemoData,
  onError,
}: FigureStageProps) {
  const viewport = useRef<HTMLDivElement>(null);
  const [bounds, setBounds] = useState({ width: 0, height: 0 });
  const [intrinsic, setIntrinsic] = useState({ width: 864, height: 576 });
  const [mode, setMode] = useState<"fit" | "manual">("fit");
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<Point>({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{
    pointer: number;
    start: Point;
    pan: Point;
    scale: number;
  } | null>(null);
  const paper = size
    ? { width: size.width * 96, height: size.height * 96 }
    : intrinsic;
  const fit = Math.max(
    0.01,
    Math.min(
      (bounds.width - 48) / paper.width,
      (bounds.height - 48) / paper.height,
      4,
    ),
  );
  const scale = mode === "fit" ? fit : zoom;
  const percentage = Math.round(scale * 100);
  useEffect(() => {
    const node = viewport.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry)
        setBounds({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  function clampPan(next: Point, targetScale = scale) {
    const maxX = Math.max(
      0,
      (bounds.width + paper.width * targetScale) / 2 - 40,
    );
    const maxY = Math.max(
      0,
      (bounds.height + paper.height * targetScale) / 2 - 40,
    );
    return {
      x: Math.max(-maxX, Math.min(maxX, next.x)),
      y: Math.max(-maxY, Math.min(maxY, next.y)),
    };
  }
  function changeZoom(next: number) {
    const value = Math.max(0.1, Math.min(4, next));
    setMode("manual");
    setZoom(value);
    setPan((current) => clampPan(current, value));
  }
  function fitFigure() {
    setMode("fit");
    setPan({ x: 0, y: 0 });
  }
  function stopDrag() {
    drag.current = null;
    setDragging(false);
  }
  const visiblePan = mode === "fit" ? { x: 0, y: 0 } : clampPan(pan);
  return (
    <section
      className="figure-stage"
      aria-label="Figure stage"
      data-view-mode={mode}
    >
      <div className="figure-stage-toolbar">
        <span className="figure-stage-label">Figure 01</span>
        {containsDemoData ? (
          <span className="stage-demo-badge">Demo data</span>
        ) : null}
        <div
          className="figure-stage-actions"
          role="group"
          aria-label="Figure view controls"
        >
          <button
            type="button"
            className="stage-fit"
            aria-label="Fit figure"
            aria-pressed={mode === "fit"}
            title="Fit figure to the stage (F)"
            onClick={fitFigure}
          >
            Fit
          </button>
          <span className="stage-action-separator" aria-hidden="true" />
          <button
            type="button"
            aria-label="Zoom out"
            disabled={scale <= 0.1}
            onClick={() => changeZoom(scale / 1.25)}
          >
            −
          </button>
          <button
            type="button"
            className="stage-zoom-value"
            aria-label="Actual size"
            title="View at 100%"
            onClick={() => {
              changeZoom(1);
              setPan({ x: 0, y: 0 });
            }}
          >
            <output aria-label="Figure zoom" aria-live="polite">
              {percentage}%
            </output>
          </button>
          <button
            type="button"
            aria-label="Zoom in"
            disabled={scale >= 4}
            onClick={() => changeZoom(scale * 1.25)}
          >
            +
          </button>
        </div>
      </div>
      <div
        className="figure-stage-viewport"
        ref={viewport}
        tabIndex={0}
        role="group"
        aria-label="Pan figure with arrow keys or drag; press F to fit"
        data-dragging={dragging}
        onKeyDown={(event) => {
          if (event.key.toLowerCase() === "f") {
            event.preventDefault();
            fitFigure();
          } else if (["+", "="].includes(event.key)) {
            event.preventDefault();
            changeZoom(scale * 1.25);
          } else if (event.key === "-") {
            event.preventDefault();
            changeZoom(scale / 1.25);
          } else if (
            ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(
              event.key,
            )
          ) {
            event.preventDefault();
            setMode("manual");
            setZoom(scale);
            setPan(
              clampPan({
                x:
                  visiblePan.x +
                  (event.key === "ArrowLeft"
                    ? -24
                    : event.key === "ArrowRight"
                      ? 24
                      : 0),
                y:
                  visiblePan.y +
                  (event.key === "ArrowUp"
                    ? -24
                    : event.key === "ArrowDown"
                      ? 24
                      : 0),
              }),
            );
          }
        }}
        onPointerDown={(event) => {
          if (event.button !== 0 || !event.isPrimary) return;
          event.preventDefault();
          event.currentTarget.focus();
          event.currentTarget.setPointerCapture(event.pointerId);
          drag.current = {
            pointer: event.pointerId,
            start: { x: event.clientX, y: event.clientY },
            pan: visiblePan,
            scale,
          };
          setDragging(true);
        }}
        onPointerMove={(event) => {
          const current = drag.current;
          if (!current || event.pointerId !== current.pointer) return;
          if (
            Math.abs(event.clientX - current.start.x) +
              Math.abs(event.clientY - current.start.y) <
            3
          )
            return;
          setMode("manual");
          setZoom(current.scale);
          setPan(
            clampPan({
              x: current.pan.x + event.clientX - current.start.x,
              y: current.pan.y + event.clientY - current.start.y,
            }),
          );
        }}
        onPointerUp={stopDrag}
        onPointerCancel={stopDrag}
        onLostPointerCapture={stopDrag}
        onDoubleClick={fitFigure}
      >
        <div
          className="figure-stage-paper"
          style={{
            width: paper.width,
            height: paper.height,
            transform: `translate(-50%, -50%) translate(${visiblePan.x}px, ${visiblePan.y}px) scale(${scale})`,
          }}
        >
          <img
            src={src}
            alt={description}
            className="plot-preview"
            draggable={false}
            onError={onError}
            onLoad={(event) => {
              if (
                event.currentTarget.naturalWidth &&
                event.currentTarget.naturalHeight
              )
                setIntrinsic({
                  width: event.currentTarget.naturalWidth,
                  height: event.currentTarget.naturalHeight,
                });
            }}
          />
        </div>
      </div>
      <footer className="figure-stage-footer">
        <span>{size ? `${size.width} × ${size.height} in` : "SVG figure"}</span>
        <span>Drag to pan · double-click to fit</span>
      </footer>
    </section>
  );
}
