import { useEffect, useRef, useState } from "react";
import { resolveArtifactUrl } from "../../api/client";
import type {
  FigureDocument,
  FigurePanel,
  PanelFrame,
  PanelGeometry,
} from "../../api/schemas/figureCompositions";
import {
  MM_PER_POINT,
  PX_PER_MM,
  clampMove,
  clampScale,
  frameAt,
  round,
  snapFrame,
  snapTargets,
  type Guides,
  type Size,
} from "./figureGeometry";

const SNAP_PX = 6;
const COMMIT_DELAY_MS = 500;
const ZOOM_STEP = 1.25;

export function panelTitle(document: FigureDocument, panel: FigurePanel) {
  if (panel.content.type === "plot") {
    const figure = document.figures[panel.content.version_id];
    return figure?.title ?? figure?.preview.description ?? "Saved plot";
  }
  return document.images[panel.content.image_id]?.name ?? "Image";
}

export function panelSource(document: FigureDocument, panel: FigurePanel) {
  const href =
    panel.content.type === "plot"
      ? document.figures[panel.content.version_id]?.preview.href
      : document.images[panel.content.image_id]?.links.content;
  return href ? resolveArtifactUrl(href) : undefined;
}

export function naturalSize(document: FigureDocument, panelId: string): Size {
  const resolved = document.panels[panelId];
  return {
    width: resolved?.natural_width_mm ?? 50,
    height: resolved?.natural_height_mm ?? 50,
  };
}

export function FigurePageCanvas({
  document,
  selected,
  busy,
  onSelect,
  onCommit,
  onRemove,
  onMenu,
  onOpen,
}: {
  document: FigureDocument;
  selected: string[];
  busy: boolean;
  onSelect: (ids: string[]) => void;
  onCommit: (
    changes: Record<string, PanelGeometry>,
    summary: string,
  ) => Promise<boolean>;
  onRemove: (ids: string[]) => void;
  onMenu: (event: React.MouseEvent<HTMLElement>, panelId: string) => void;
  onOpen: (panelId: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState({ width: 900, height: 700 });
  const [zoom, setZoom] = useState<number | "fit">("fit");
  const [draft, setDraft] = useState<Record<string, PanelGeometry>>({});
  const [guides, setGuides] = useState<Guides | null>(null);
  const pending = useRef<Record<string, PanelGeometry>>({});
  const timer = useRef<number | undefined>(undefined);
  const { page, labels } = document.content;
  const panels = document.content.panels;

  useEffect(() => {
    const element = container.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry)
        setViewport({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const geometry = (panel: FigurePanel): PanelGeometry =>
    draft[panel.id] ?? panel;
  const frames: Record<string, PanelFrame> = Object.fromEntries(
    panels.map((panel) => [
      panel.id,
      frameAt(geometry(panel), naturalSize(document, panel.id)),
    ]),
  );
  const contentBottom = Math.max(
    0,
    ...Object.values(frames).map((f) => f.y_mm + f.height_mm),
  );
  const pageHeight =
    page.height_mode === "fixed"
      ? page.height_mm
      : Math.min(
          page.height_mm,
          Math.max(document.page_height_mm, contentBottom + page.margin_mm),
        );
  const fit = Math.max(
    0.5,
    Math.min(
      (viewport.width - 64) / page.width_mm,
      (viewport.height - 64) / pageHeight,
    ),
  );
  const px = zoom === "fit" ? fit : zoom;
  const toPx = (mm: number) => `${mm * px}px`;

  function commit(changes: Record<string, PanelGeometry>, summary: string) {
    void onCommit(changes, summary).finally(() =>
      setDraft((current) => {
        const next = { ...current };
        for (const id of Object.keys(changes)) delete next[id];
        return next;
      }),
    );
  }
  function schedule(changes: Record<string, PanelGeometry>, summary: string) {
    pending.current = { ...pending.current, ...changes };
    setDraft((current) => ({ ...current, ...changes }));
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const batch = pending.current;
      pending.current = {};
      commit(batch, summary);
    }, COMMIT_DELAY_MS);
  }
  const movable = (ids: string[]) =>
    panels.filter((panel) => ids.includes(panel.id) && !panel.locked);

  function startMove(
    event: React.PointerEvent<HTMLDivElement>,
    panel: FigurePanel,
  ) {
    if (event.button !== 0 || busy) return;
    if (event.shiftKey || event.metaKey || event.ctrlKey) {
      onSelect(
        selected.includes(panel.id)
          ? selected.filter((id) => id !== panel.id)
          : [...selected, panel.id],
      );
      return;
    }
    const ids = selected.includes(panel.id) ? selected : [panel.id];
    if (!selected.includes(panel.id)) onSelect([panel.id]);
    const moving = movable(ids);
    if (!moving.length) return;
    event.preventDefault();
    const target = event.currentTarget;
    target.setPointerCapture?.(event.pointerId);
    const origin = { x: event.clientX, y: event.clientY };
    const start = Object.fromEntries(moving.map((p) => [p.id, frames[p.id]!]));
    const primary = start[panel.id] ?? Object.values(start)[0]!;
    const targets = snapTargets(
      page,
      pageHeight,
      panels.filter((p) => !(p.id in start)).map((p) => frames[p.id]!),
    );
    let latest: Record<string, PanelGeometry> | null = null;
    const move = (e: PointerEvent) => {
      let dx = (e.clientX - origin.x) / px;
      let dy = (e.clientY - origin.y) / px;
      const snap = e.altKey
        ? { dx: 0, dy: 0, guides: { x: null, y: null } }
        : snapFrame(
            { ...primary, x_mm: primary.x_mm + dx, y_mm: primary.y_mm + dy },
            targets,
            SNAP_PX / px,
          );
      ({ dx, dy } = clampMove(
        Object.values(start),
        dx + snap.dx,
        dy + snap.dy,
        page,
      ));
      latest = Object.fromEntries(
        moving.map((p) => [
          p.id,
          {
            x_mm: round(start[p.id]!.x_mm + dx),
            y_mm: round(start[p.id]!.y_mm + dy),
            scale: p.scale,
          },
        ]),
      );
      setDraft(latest);
      setGuides(snap.guides);
    };
    const finish = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", finish);
      target.removeEventListener("pointercancel", finish);
      setGuides(null);
      const changed =
        latest &&
        moving.some(
          (p) =>
            Math.abs(latest![p.id]!.x_mm - p.x_mm) >= 0.1 ||
            Math.abs(latest![p.id]!.y_mm - p.y_mm) >= 0.1,
        );
      if (latest && changed)
        commit(latest, moving.length > 1 ? "Moved panels" : "Moved panel");
      else setDraft({});
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", finish);
    target.addEventListener("pointercancel", finish);
  }

  function startResize(
    event: React.PointerEvent<HTMLSpanElement>,
    panel: FigurePanel,
  ) {
    if (event.button !== 0 || busy || panel.locked) return;
    event.preventDefault();
    event.stopPropagation();
    const target = event.currentTarget;
    target.setPointerCapture?.(event.pointerId);
    const natural = naturalSize(document, panel.id);
    const start = frames[panel.id]!;
    const targets = snapTargets(
      page,
      pageHeight,
      panels.filter((p) => p.id !== panel.id).map((p) => frames[p.id]!),
    );
    const origin = event.clientX;
    let latest: PanelGeometry | null = null;
    const move = (e: PointerEvent) => {
      let right = start.x_mm + start.width_mm + (e.clientX - origin) / px;
      const snap = e.altKey
        ? null
        : snapFrame(
            { ...start, x_mm: right, width_mm: 0 },
            { x: targets.x, y: [] },
            SNAP_PX / px,
          );
      if (snap?.guides.x != null) right = snap.guides.x;
      latest = {
        x_mm: panel.x_mm,
        y_mm: panel.y_mm,
        scale: clampScale(
          panel,
          natural,
          page,
          (right - start.x_mm) / natural.width,
        ),
      };
      setDraft({ [panel.id]: latest });
      setGuides(snap ? { x: snap.guides.x, y: null } : null);
    };
    const finish = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", finish);
      target.removeEventListener("pointercancel", finish);
      setGuides(null);
      if (latest && latest.scale !== panel.scale)
        commit({ [panel.id]: latest }, "Resized panel");
      else setDraft({});
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", finish);
    target.addEventListener("pointercancel", finish);
  }

  function keyOnPanel(
    event: React.KeyboardEvent<HTMLDivElement>,
    panel: FigurePanel,
  ) {
    const ids = selected.includes(panel.id) ? selected : [panel.id];
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      onRemove(ids);
      return;
    }
    if (event.key === "Escape") {
      onSelect([]);
      return;
    }
    const step = event.shiftKey ? 5 : 0.5;
    const delta = {
      ArrowLeft: [-step, 0],
      ArrowRight: [step, 0],
      ArrowUp: [0, -step],
      ArrowDown: [0, step],
    }[event.key];
    if (!delta || busy) return;
    event.preventDefault();
    const moving = movable(ids);
    if (!moving.length) return;
    const current = moving.map((p) => frames[p.id]!);
    const { dx, dy } = clampMove(current, delta[0]!, delta[1]!, page);
    schedule(
      Object.fromEntries(
        moving.map((p) => [
          p.id,
          {
            x_mm: round(frames[p.id]!.x_mm + dx),
            y_mm: round(frames[p.id]!.y_mm + dy),
            scale: geometry(p).scale,
          },
        ]),
      ),
      moving.length > 1 ? "Moved panels" : "Moved panel",
    );
  }

  function keyOnHandle(
    event: React.KeyboardEvent<HTMLSpanElement>,
    panel: FigurePanel,
  ) {
    const direction = {
      ArrowRight: 1,
      ArrowUp: 1,
      ArrowLeft: -1,
      ArrowDown: -1,
    }[event.key];
    if (!direction || busy || panel.locked) return;
    event.preventDefault();
    event.stopPropagation();
    const current = geometry(panel);
    schedule(
      {
        [panel.id]: {
          ...current,
          scale: clampScale(
            current,
            naturalSize(document, panel.id),
            page,
            current.scale * (1 + direction * (event.shiftKey ? 0.05 : 0.01)),
          ),
        },
      },
      "Resized panel",
    );
  }

  const labelSize = labels.size_pt * MM_PER_POINT * px;
  const rendering = new Set(
    document.jobs
      .filter((job) => job.status === "running")
      .map((job) => job.panel_id),
  );
  const flagged = new Set(
    document.checks
      .filter((check) => check.severity === "warning")
      .flatMap((check) => check.panel_ids),
  );
  const rulerStep = px * 10 >= 32 ? 10 : 50;
  const ticks = (length: number) =>
    Array.from(
      { length: Math.floor(length / rulerStep) + 1 },
      (_, i) => i * rulerStep,
    );
  return (
    <div className="composition-canvas">
      <div className="composition-zoom" role="group" aria-label="Zoom">
        <button
          type="button"
          aria-label="Zoom out"
          onClick={() => setZoom(Math.max(0.5, px / ZOOM_STEP))}
        >
          −
        </button>
        <button
          type="button"
          aria-label="Fit page"
          aria-pressed={zoom === "fit"}
          onClick={() => setZoom("fit")}
        >
          {Math.round((px / PX_PER_MM) * 100)}%
        </button>
        <button
          type="button"
          aria-label="Zoom in"
          onClick={() => setZoom(Math.min(20, px * ZOOM_STEP))}
        >
          +
        </button>
      </div>
      <div className="composition-stage" ref={container}>
        <div
          className="composition-sheet"
          style={{ width: toPx(page.width_mm), height: toPx(pageHeight) }}
        >
          <div
            className="composition-ruler composition-ruler-x"
            aria-hidden="true"
          >
            {ticks(page.width_mm).map((mm) => (
              <span key={mm} style={{ left: toPx(mm) }}>
                {mm}
              </span>
            ))}
          </div>
          <div
            className="composition-ruler composition-ruler-y"
            aria-hidden="true"
          >
            {ticks(pageHeight).map((mm) => (
              <span key={mm} style={{ top: toPx(mm) }}>
                {mm}
              </span>
            ))}
          </div>
          <div
            className="composition-page"
            role="region"
            aria-label="Figure page"
            data-height-mode={page.height_mode}
            style={{ width: toPx(page.width_mm), height: toPx(pageHeight) }}
            onPointerDown={(event) => {
              if (event.target === event.currentTarget) onSelect([]);
            }}
          >
            <div
              className="composition-margin"
              aria-hidden="true"
              style={{ inset: toPx(page.margin_mm) }}
            />
            {panels.map((panel) => {
              const frame = frames[panel.id]!;
              const resolved = document.panels[panel.id];
              const label = resolved?.label;
              const isSelected = selected.includes(panel.id);
              const title = panelTitle(document, panel);
              const source = panelSource(document, panel);
              return (
                <div
                  key={panel.id}
                  className="composition-panel"
                  role="button"
                  tabIndex={0}
                  aria-pressed={isSelected}
                  aria-label={`Panel ${label ?? "without label"}: ${title}`}
                  data-locked={panel.locked}
                  data-warning={flagged.has(panel.id)}
                  style={{
                    left: toPx(frame.x_mm),
                    top: toPx(frame.y_mm),
                    width: toPx(frame.width_mm),
                    height: toPx(frame.height_mm),
                  }}
                  onPointerDown={(event) => startMove(event, panel)}
                  onKeyDown={(event) => keyOnPanel(event, panel)}
                  onDoubleClick={() => onOpen(panel.id)}
                  onContextMenu={(event) => {
                    event.preventDefault();
                    if (!isSelected) onSelect([panel.id]);
                    onMenu(event, panel.id);
                  }}
                >
                  {source ? (
                    <img src={source} alt={title} draggable={false} />
                  ) : (
                    <span className="composition-panel-missing">{title}</span>
                  )}
                  {label ? (
                    <span
                      className="composition-panel-label"
                      style={{
                        fontSize: `${labelSize}px`,
                        fontWeight: labels.bold ? 700 : 400,
                        fontFamily: `${labels.font_family}, Helvetica, sans-serif`,
                      }}
                    >
                      {label}
                    </span>
                  ) : null}
                  {document.updates[panel.id] ? (
                    <span className="composition-panel-badge">
                      Update available
                    </span>
                  ) : null}
                  {rendering.has(panel.id) ? (
                    <span className="composition-panel-rendering" role="status">
                      Rendering at panel size…
                    </span>
                  ) : null}
                  {panel.locked ? (
                    <span className="composition-panel-lock" aria-hidden="true">
                      Locked
                    </span>
                  ) : null}
                  {isSelected && selected.length === 1 && !panel.locked ? (
                    <span
                      className="composition-resize-handle"
                      role="slider"
                      tabIndex={0}
                      aria-label={`Resize panel ${label ?? title}`}
                      aria-valuemin={5}
                      aria-valuemax={1000}
                      aria-valuenow={Math.round(geometry(panel).scale * 100)}
                      aria-valuetext={`${Math.round(geometry(panel).scale * 100)}% scale`}
                      onPointerDown={(event) => startResize(event, panel)}
                      onKeyDown={(event) => keyOnHandle(event, panel)}
                    />
                  ) : null}
                </div>
              );
            })}
            {guides?.x != null ? (
              <div
                className="composition-guide composition-guide-x"
                style={{ left: toPx(guides.x) }}
              />
            ) : null}
            {guides?.y != null ? (
              <div
                className="composition-guide composition-guide-y"
                style={{ top: toPx(guides.y) }}
              />
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
