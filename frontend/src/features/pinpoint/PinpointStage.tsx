import { useRef, useState, type PointerEvent } from "react";
import type { ImageMark } from "../../api/pinpoint";
import { MAX_MARKS, nextMarkNumber } from "./marks";

type Point = { x: number; y: number };
/** Pointer travel, in pixels, that turns a click into an area. */
const DRAG_THRESHOLD = 6;

/**
 * The plot with its marks. Click to mark a point; drag to mark an area. Positions are
 * fractions of the image, so they hold at any zoom.
 */
export function PinpointStage({
  src,
  alt,
  marks,
  disabled,
  onMark,
  onRemove,
}: {
  src: string;
  alt: string;
  marks: ImageMark[];
  disabled: boolean;
  onMark: (mark: ImageMark) => void;
  onRemove: (number: number) => void;
}) {
  const surface = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ start: Point; end: Point } | null>(null);
  // Width over height; the plot is enlarged to fill the stage at its own proportions.
  const [ratio, setRatio] = useState<number | null>(null);
  const full = marks.length >= MAX_MARKS;

  function locate(event: PointerEvent): Point {
    const box = surface.current!.getBoundingClientRect();
    return {
      x: clamp((event.clientX - box.left) / box.width),
      y: clamp((event.clientY - box.top) / box.height),
    };
  }
  function finish(event: PointerEvent) {
    if (!drag) return;
    const end = locate(event);
    const box = surface.current!.getBoundingClientRect();
    const moved = Math.hypot(
      (end.x - drag.start.x) * box.width,
      (end.y - drag.start.y) * box.height,
    );
    setDrag(null);
    const number = nextMarkNumber(marks);
    if (number === null) return;
    if (moved < DRAG_THRESHOLD)
      onMark({ number, kind: "point", ...drag.start, width: 0, height: 0 });
    else onMark({ number, kind: "area", ...area(drag.start, end) });
  }

  return (
    <figure className="pinpoint-stage">
      <div
        ref={surface}
        className="pinpoint-surface"
        data-disabled={disabled || full}
        data-sized={Boolean(ratio)}
        style={
          ratio
            ? {
                aspectRatio: String(ratio),
                width: `min(100%, calc(var(--pinpoint-stage-height) * ${ratio}))`,
              }
            : undefined
        }
        onPointerDown={(event) => {
          if (disabled || full || event.button !== 0) return;
          event.currentTarget.setPointerCapture?.(event.pointerId);
          const start = locate(event);
          setDrag({ start, end: start });
        }}
        onPointerMove={(event) => {
          if (drag) setDrag({ ...drag, end: locate(event) });
        }}
        onPointerUp={finish}
        onPointerCancel={() => setDrag(null)}
      >
        <img
          src={src}
          alt={alt}
          draggable={false}
          onLoad={(event) => {
            const { naturalWidth, naturalHeight } = event.currentTarget;
            if (naturalWidth && naturalHeight)
              setRatio(naturalWidth / naturalHeight);
          }}
        />
        {marks.map((mark) => (
          <span
            key={mark.number}
            className="pinpoint-mark"
            data-kind={mark.kind}
            style={placement(mark)}
          >
            {/* A mouse shortcut; the request box lists the marks for keyboards. */}
            <span
              className="pinpoint-mark-number"
              aria-hidden="true"
              title="Remove this mark"
              onPointerDown={(event) => event.stopPropagation()}
              onClick={() => onRemove(mark.number)}
            >
              {mark.number}
            </span>
          </span>
        ))}
        {drag ? (
          <span
            className="pinpoint-mark pinpoint-mark-draft"
            data-kind="area"
            style={placement({
              number: 0,
              kind: "area",
              ...area(drag.start, drag.end),
            })}
          />
        ) : null}
      </div>
      <figcaption>
        {full
          ? `Up to ${MAX_MARKS} marks. Remove one to add another.`
          : "Click to mark a point, or drag to mark an area. Then say what you want."}
      </figcaption>
    </figure>
  );
}

function clamp(value: number) {
  return Math.min(1, Math.max(0, value));
}

function area(start: Point, end: Point) {
  return {
    x: Math.min(start.x, end.x),
    y: Math.min(start.y, end.y),
    width: Math.abs(end.x - start.x),
    height: Math.abs(end.y - start.y),
  };
}

function placement(mark: ImageMark) {
  return {
    left: `${mark.x * 100}%`,
    top: `${mark.y * 100}%`,
    ...(mark.kind === "area"
      ? { width: `${mark.width * 100}%`, height: `${mark.height * 100}%` }
      : {}),
  };
}
