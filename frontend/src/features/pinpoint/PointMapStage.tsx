import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import type {
  Deck,
  OrthographicView,
  OrthographicViewState,
} from "@deck.gl/core";
import { resolveArtifactUrl } from "../../api/client";
import {
  getPointColumns,
  getPointView,
  type PlotMark,
  type PointView,
} from "../../api/pinpoint";
import { MAX_MARKS, nextMarkNumber } from "./marks";
import {
  boxBetween,
  buildIndex,
  countInBox,
  fitView,
  interleave,
  nearest,
  niceTicks,
  pointColors,
  project,
  tickLabel,
  unproject,
  type Box,
  type MapCamera,
  type PointColumns,
  type Size,
} from "./pointMapModel";

/** Space around the map for the axes, in CSS pixels. */
const GUTTER = { left: 56, bottom: 38, top: 8, right: 12 };
const DRAG_THRESHOLD = 6;
/** How near the pointer, in pixels, a point must be to be hovered or clicked. */
const PICK_RADIUS = 6;
type Tool = "point" | "area";

/**
 * A point map drawn on the GPU, with the image under it. Click a point to mark it, or switch
 * to area and drag. Marks are the data itself: a point's index, or a box in data units.
 */
export function PointMapStage({
  projectId,
  plotId,
  versionId,
  marks,
  disabled,
  onMark,
  onRemove,
  onUnavailable,
}: {
  projectId: string;
  plotId: string;
  versionId: string;
  marks: PlotMark[];
  disabled: boolean;
  onMark: (mark: PlotMark) => void;
  onRemove: (number: number) => void;
  /** The browser cannot draw the interactive view; the saved image is used instead. */
  onUnavailable: (reason: string) => void;
}) {
  const view = useQuery({
    queryKey: ["point-view", projectId, plotId, versionId],
    queryFn: () => getPointView(projectId, plotId, versionId),
    staleTime: Infinity,
  });
  const columns = useQuery({
    queryKey: ["point-columns", view.data?.links.columns],
    queryFn: () => getPointColumns(view.data!),
    enabled: Boolean(view.data),
    staleTime: Infinity,
  });
  if (view.error || columns.error)
    return (
      <p role="alert" className="pinpoint-error">
        {(view.error ?? columns.error) instanceof Error
          ? (view.error ?? columns.error)!.message
          : "The interactive view could not be loaded."}
      </p>
    );
  if (!view.data || !columns.data)
    return (
      <p className="pinpoint-map-loading" role="status">
        {view.data
          ? `Loading ${view.data.count.toLocaleString()} points…`
          : "Loading the interactive view…"}
      </p>
    );
  return (
    <PointMap
      view={view.data}
      columns={columns.data}
      marks={marks}
      disabled={disabled}
      onMark={onMark}
      onRemove={onRemove}
      onUnavailable={onUnavailable}
    />
  );
}

function PointMap({
  view,
  columns,
  marks,
  disabled,
  onMark,
  onRemove,
  onUnavailable,
}: {
  view: PointView;
  columns: PointColumns;
  marks: PlotMark[];
  disabled: boolean;
  onMark: (mark: PlotMark) => void;
  onRemove: (number: number) => void;
  onUnavailable: (reason: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const deck = useRef<Deck<OrthographicView> | null>(null);
  // The deck is created asynchronously; layers are given to it once it exists.
  const [ready, setReady] = useState(false);
  const [drawn, setDrawn] = useState(false);
  const [size, setSize] = useState<Size | null>(null);
  const [camera, setCamera] = useState<MapCamera | null>(null);
  const [tool, setTool] = useState<Tool>("point");
  const [showImage, setShowImage] = useState(view.image?.visible ?? false);
  const [drag, setDrag] = useState<{
    start: [number, number];
    end: [number, number];
  } | null>(null);
  const down = view.y.direction === "down";
  const full = marks.length >= MAX_MARKS;
  const fitted = useMemo(
    () => (size ? fitView(view, size.width, size.height) : null),
    [view, size],
  );
  // Positions and colours are uploaded to the GPU once per version.
  const data = useMemo(
    () => ({
      length: view.count,
      attributes: {
        getPosition: { value: interleave(columns.x, columns.y), size: 2 },
        getFillColor: {
          value: pointColors(view, columns),
          size: 4,
          normalized: true,
        },
      },
    }),
    [view, columns],
  );

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const box = entry!.contentRect;
      setSize({ width: Math.round(box.width), height: Math.round(box.height) });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (fitted && !camera) setCamera(fitted);
  }, [fitted, camera]);

  // The deck is created once and then only receives new props.
  useEffect(() => {
    if (!host.current || !size || !camera || deck.current) return;
    // deck.gl reports a missing GPU context only after it has started, so check first.
    if (!document.createElement("canvas").getContext("webgl2")) {
      onUnavailable("WebGL2 is unavailable");
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const { Deck, OrthographicView } = await import("@deck.gl/core");
        if (cancelled || !host.current) return;
        deck.current = new Deck({
          parent: host.current,
          width: "100%",
          height: "100%",
          views: new OrthographicView({ id: "map", flipY: down }),
          viewState: deckView(camera),
          controller: { doubleClickZoom: false, dragPan: tool === "point" },
          layers: [],
          onViewStateChange: ({ viewState }) => {
            setCamera(fromDeck(viewState as Record<string, unknown>));
            return viewState;
          },
          onError: (error) => onUnavailable(error.message),
          // The first frame with layers means the points are on screen.
          onAfterRender: () => {
            if (deck.current?.props.layers.length) setDrawn(true);
          },
        });
        setReady(true);
      } catch (reason) {
        onUnavailable(
          reason instanceof Error
            ? reason.message
            : "WebGL is unavailable in this browser.",
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [size, camera === null]);

  useEffect(
    () => () => {
      deck.current?.finalize();
      deck.current = null;
    },
    [],
  );

  // Layers follow the camera (points grow a little as you zoom in) and the image switch.
  useEffect(() => {
    const current = deck.current;
    if (!current || !camera || !fitted) return;
    let cancelled = false;
    void import("@deck.gl/layers").then(({ BitmapLayer, ScatterplotLayer }) => {
      if (cancelled) return;
      const zoomed = Math.max(
        0,
        Math.min(camera.zoomX, camera.zoomY) -
          Math.min(fitted.zoomX, fitted.zoomY),
      );
      current.setProps({
        viewState: deckView(camera),
        controller: { doubleClickZoom: false, dragPan: tool === "point" },
        layers: [
          ...(view.image && view.links.image
            ? [
                new BitmapLayer({
                  id: "image",
                  image: resolveArtifactUrl(view.links.image),
                  // [left, bottom, right, top]: the image's first row lies at extent[2].
                  bounds: [
                    view.image.extent[0],
                    view.image.extent[3],
                    view.image.extent[1],
                    view.image.extent[2],
                  ],
                  visible: showImage,
                }),
              ]
            : []),
          new ScatterplotLayer({
            id: "points",
            data,
            radiusUnits: "pixels",
            getRadius: Math.min(8, Math.max(1, view.point_size * 1.5)),
            radiusScale: 2 ** (zoomed * 0.6),
            radiusMaxPixels: 24,
            opacity: view.opacity,
          }),
        ],
      });
    });
    return () => {
      cancelled = true;
    };
  }, [ready, camera, fitted, showImage, tool, data, view]);

  // Finding the point under the pointer uses the grid index, not a GPU read.
  const index = useMemo(() => buildIndex(view, columns), [view, columns]);
  const [hovered, setHovered] = useState<{
    point: number;
    at: [number, number];
  } | null>(null);
  const hoverFrame = useRef(0);
  function under(at: [number, number]): number {
    if (!camera || !size) return -1;
    return nearest(
      index,
      unproject(camera, size, down, at),
      PICK_RADIUS / 2 ** camera.zoomX,
      PICK_RADIUS / 2 ** camera.zoomY,
    );
  }
  // A click is a press and release without dragging.
  const press = useRef<[number, number] | null>(null);
  function pick(event: PointerEvent) {
    const start = press.current;
    press.current = null;
    const at = local(event);
    if (
      !start ||
      Math.hypot(at[0] - start[0], at[1] - start[1]) >= DRAG_THRESHOLD ||
      disabled ||
      full
    )
      return;
    const point = under(at);
    const number = nextMarkNumber(marks);
    if (point >= 0 && number !== null)
      onMark({ number, kind: "element", index: point });
  }
  function hover(event: PointerEvent) {
    const at = local(event);
    cancelAnimationFrame(hoverFrame.current);
    hoverFrame.current = requestAnimationFrame(() => {
      const point = under(at);
      setHovered(point >= 0 ? { point, at } : null);
    });
  }

  function screen(point: [number, number]): [number, number] {
    return camera && size ? project(camera, size, down, point) : [0, 0];
  }
  function local(event: PointerEvent): [number, number] {
    const box = event.currentTarget.getBoundingClientRect();
    return [event.clientX - box.left, event.clientY - box.top];
  }
  function finish(event: PointerEvent) {
    if (!drag || !camera || !size) return;
    const end = local(event);
    setDrag(null);
    if (
      Math.hypot(end[0] - drag.start[0], end[1] - drag.start[1]) <
      DRAG_THRESHOLD
    )
      return;
    const number = nextMarkNumber(marks);
    if (number === null) return;
    const box = boxBetween(
      unproject(camera, size, down, drag.start),
      unproject(camera, size, down, end),
    );
    onMark({ number, kind: "selection", ...box });
  }

  const areaCounts = useMemo(
    () =>
      new Map(
        marks.flatMap((mark) =>
          mark.kind === "selection"
            ? [[mark.number, countInBox(columns, mark)] as const]
            : [],
        ),
      ),
    [marks, columns],
  );

  return (
    <figure className="pinpoint-map" data-drawn={drawn}>
      <div className="pinpoint-map-toolbar">
        <div
          role="radiogroup"
          aria-label="Marking tool"
          className="pinpoint-map-tools"
        >
          {(
            [
              ["point", "Click a point"],
              ["area", "Drag an area"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={tool === value}
              onClick={() => setTool(value)}
            >
              {label}
            </button>
          ))}
        </div>
        {view.image ? (
          <label className="pinpoint-map-switch">
            <input
              type="checkbox"
              checked={showImage}
              onChange={(event) => setShowImage(event.target.checked)}
            />
            Image
          </label>
        ) : null}
        <button
          type="button"
          className="pinpoint-link"
          onClick={() => fitted && setCamera(fitted)}
        >
          Fit
        </button>
        <span className="pinpoint-note" role="status">
          {drawn ? "" : "Drawing points… "}
          {view.count.toLocaleString()} points
          {view.dropped
            ? ` · ${view.dropped.toLocaleString()} without positions`
            : ""}
        </span>
      </div>
      <div className="pinpoint-map-frame">
        <div
          className="pinpoint-map-area"
          style={{
            left: GUTTER.left,
            right: GUTTER.right,
            top: GUTTER.top,
            bottom: GUTTER.bottom,
          }}
        >
          <div
            ref={host}
            className="pinpoint-map-canvas"
            aria-label={view.title}
            role="img"
            onPointerDown={(event) => {
              if (tool === "point" && event.button === 0)
                press.current = local(event);
            }}
            onPointerUp={pick}
            onPointerMove={(event) => {
              if (tool === "point" && !event.buttons) hover(event);
            }}
            onPointerLeave={() => {
              cancelAnimationFrame(hoverFrame.current);
              setHovered(null);
            }}
          />
          {tool === "area" ? (
            <div
              className="pinpoint-map-drag"
              data-disabled={disabled || full}
              aria-label="Drag to mark an area"
              onPointerDown={(event) => {
                if (disabled || full || event.button !== 0) return;
                event.currentTarget.setPointerCapture?.(event.pointerId);
                const start = local(event);
                setDrag({ start, end: start });
              }}
              onPointerMove={(event) => {
                if (drag) setDrag({ ...drag, end: local(event) });
              }}
              onPointerUp={finish}
              onPointerCancel={() => setDrag(null)}
            />
          ) : null}
          <svg className="pinpoint-map-overlay" aria-hidden="true">
            {marks.map((mark) =>
              mark.kind === "element" ? (
                <Ring
                  key={mark.number}
                  at={screen([columns.x[mark.index]!, columns.y[mark.index]!])}
                  number={mark.number}
                  onRemove={onRemove}
                />
              ) : mark.kind === "selection" ? (
                <Area
                  key={mark.number}
                  corners={[
                    screen([mark.x_from, mark.y_from]),
                    screen([mark.x_to, mark.y_to]),
                  ]}
                  number={mark.number}
                  count={areaCounts.get(mark.number) ?? 0}
                  onRemove={onRemove}
                />
              ) : null,
            )}
            {hovered && tool === "point" ? (
              <circle
                className="pinpoint-map-hover"
                r={6}
                cx={
                  screen([
                    columns.x[hovered.point]!,
                    columns.y[hovered.point]!,
                  ])[0]
                }
                cy={
                  screen([
                    columns.x[hovered.point]!,
                    columns.y[hovered.point]!,
                  ])[1]
                }
              />
            ) : null}
            {drag ? (
              <rect
                className="pinpoint-map-draft"
                x={Math.min(drag.start[0], drag.end[0])}
                y={Math.min(drag.start[1], drag.end[1])}
                width={Math.abs(drag.end[0] - drag.start[0])}
                height={Math.abs(drag.end[1] - drag.start[1])}
              />
            ) : null}
          </svg>
          {hovered && tool === "point" ? (
            <div
              className="pinpoint-map-tooltip"
              role="tooltip"
              style={{ left: hovered.at[0] + 12, top: hovered.at[1] + 12 }}
            >
              {describePoint(view, columns, hovered.point)}
            </div>
          ) : null}
        </div>
        {camera && size ? (
          <Axes view={view} camera={camera} size={size} />
        ) : null}
      </div>
      <Legend view={view} />
      <figcaption>
        {full
          ? `Up to ${MAX_MARKS} marks. Remove one to add another.`
          : tool === "point"
            ? "Click a point to mark it; drag to pan and scroll to zoom. Then say what you want."
            : "Drag across the points to mark an area. Then say what you want."}
      </figcaption>
    </figure>
  );
}

function Ring({
  at,
  number,
  onRemove,
}: {
  at: [number, number];
  number: number;
  onRemove: (number: number) => void;
}) {
  return (
    <g className="pinpoint-map-mark" transform={`translate(${at[0]} ${at[1]})`}>
      <circle r={9} className="pinpoint-map-ring" />
      <g transform="translate(11 -11)" onClick={() => onRemove(number)}>
        <circle r={9} className="pinpoint-map-badge" />
        <text textAnchor="middle" dy="0.35em">
          {number}
        </text>
      </g>
    </g>
  );
}

function Area({
  corners,
  number,
  count,
  onRemove,
}: {
  corners: [[number, number], [number, number]];
  number: number;
  count: number;
  onRemove: (number: number) => void;
}) {
  const [[ax, ay], [bx, by]] = corners;
  const left = Math.min(ax, bx);
  const top = Math.min(ay, by);
  return (
    <g className="pinpoint-map-mark">
      <rect
        className="pinpoint-map-box"
        x={left}
        y={top}
        width={Math.abs(bx - ax)}
        height={Math.abs(by - ay)}
      />
      <g
        transform={`translate(${left} ${top})`}
        onClick={() => onRemove(number)}
      >
        <circle r={9} className="pinpoint-map-badge" />
        <text textAnchor="middle" dy="0.35em">
          {number}
        </text>
      </g>
      <text className="pinpoint-map-count" x={left + 12} y={top - 4}>
        {count.toLocaleString()} points
      </text>
    </g>
  );
}

function Axes({
  view,
  camera,
  size,
}: {
  view: PointView;
  camera: MapCamera;
  size: Size;
}) {
  const down = view.y.direction === "down";
  const [x0, yTop] = unproject(camera, size, down, [0, 0]);
  const [x1, yBottom] = unproject(camera, size, down, [
    size.width,
    size.height,
  ]);
  const xTicks = niceTicks(Math.min(x0, x1), Math.max(x0, x1));
  const yTicks = niceTicks(Math.min(yTop, yBottom), Math.max(yTop, yBottom));
  return (
    <svg className="pinpoint-map-axes" aria-hidden="true">
      <g transform={`translate(${GUTTER.left} ${GUTTER.top + size.height})`}>
        <line x1={0} x2={size.width} className="pinpoint-map-axis" />
        {xTicks.map((tick) => {
          const [x] = project(camera, size, down, [tick, 0]);
          return (
            <g key={tick} transform={`translate(${x} 0)`}>
              <line y2={4} className="pinpoint-map-axis" />
              <text y={15} textAnchor="middle">
                {tickLabel(tick, xTicks)}
              </text>
            </g>
          );
        })}
        <text
          x={size.width / 2}
          y={32}
          textAnchor="middle"
          className="pinpoint-map-title"
        >
          {view.x.title}
        </text>
      </g>
      <g transform={`translate(${GUTTER.left} ${GUTTER.top})`}>
        <line y1={0} y2={size.height} className="pinpoint-map-axis" />
        {yTicks.map((tick) => {
          const [, y] = project(camera, size, down, [0, tick]);
          return (
            <g key={tick} transform={`translate(0 ${y})`}>
              <line x2={-4} className="pinpoint-map-axis" />
              <text x={-7} dy="0.32em" textAnchor="end">
                {tickLabel(tick, yTicks)}
              </text>
            </g>
          );
        })}
        <text
          transform={`translate(-44 ${size.height / 2}) rotate(-90)`}
          textAnchor="middle"
          className="pinpoint-map-title"
        >
          {view.y.title}
        </text>
      </g>
    </svg>
  );
}

function Legend({ view }: { view: PointView }) {
  const color = view.color;
  if (!color) return null;
  return (
    <section
      className="pinpoint-map-legend"
      aria-label={`Colour: ${color.title}`}
    >
      <strong>{color.title}</strong>
      {color.type === "categorical" ? (
        <ul>
          {color.categories.map((item) => (
            <li key={item.value}>
              <span style={{ background: item.color }} />
              {item.value}
            </li>
          ))}
        </ul>
      ) : (
        <div className="pinpoint-map-scale">
          <span>{tickLabel(color.domain[0], color.domain)}</span>
          <span
            className="pinpoint-map-ramp"
            style={{
              background: `linear-gradient(to right, ${color.stops.join(", ")})`,
            }}
          />
          <span>{tickLabel(color.domain[1], color.domain)}</span>
        </div>
      )}
    </section>
  );
}

function describePoint(
  view: PointView,
  columns: PointColumns,
  index: number,
): string {
  const lines = [
    `${view.x.title}: ${columns.x[index]!.toPrecision(5)}`,
    `${view.y.title}: ${columns.y[index]!.toPrecision(5)}`,
  ];
  const value = columns.color?.[index];
  if (view.color && value !== undefined && !Number.isNaN(value))
    lines.unshift(
      `${view.color.title}: ${
        view.color.type === "categorical"
          ? (view.color.categories[value]?.value ?? "")
          : value.toPrecision(4)
      }`,
    );
  return lines.join("\n");
}

function deckView(camera: MapCamera): OrthographicViewState {
  return {
    target: camera.target,
    zoomX: camera.zoomX,
    zoomY: camera.zoomY,
  };
}

function fromDeck(state: Record<string, unknown>): MapCamera {
  const zoom = state.zoom;
  const both =
    typeof zoom === "number" ? zoom : Array.isArray(zoom) ? Number(zoom[0]) : 0;
  const target = (state.target as number[] | undefined) ?? [0, 0];
  return {
    target: [target[0] ?? 0, target[1] ?? 0],
    zoomX: typeof state.zoomX === "number" ? state.zoomX : both,
    zoomY: typeof state.zoomY === "number" ? state.zoomY : both,
  };
}

export type { Box };
