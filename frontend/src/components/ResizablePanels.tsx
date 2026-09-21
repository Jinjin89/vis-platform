import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import "./resizablePanels.css";

type ResizablePanelsProps = {
  children: [ReactNode, ReactNode];
  className: string;
  direction: "horizontal" | "vertical";
  label: string;
  storageKey: string;
  firstMinimum: number;
  secondMinimum: number;
  secondMaximum?: number;
  fixedSize?: number;
};

export function ResizablePanels({
  children,
  className,
  direction,
  label,
  storageKey,
  firstMinimum,
  secondMinimum,
  secondMaximum = Infinity,
  fixedSize,
}: ResizablePanelsProps) {
  const root = useRef<HTMLDivElement>(null);
  const handle = useRef<HTMLDivElement>(null);
  const drag = useRef<{ pointer: number; start: number; size: number } | null>(
    null,
  );
  const [dragging, setDragging] = useState(false);
  const [preferredSize, setPreferredSize] = useState<number | null>(() => {
    try {
      const value = Number(window.sessionStorage.getItem(storageKey));
      return Number.isFinite(value) && value > 0 ? value : null;
    } catch {
      return null;
    }
  });
  const [measurements, setMeasurements] = useState({ available: 0, second: 0 });
  const horizontal = direction === "horizontal";
  const available = measurements.available;
  const maximum =
    available > 0
      ? Math.min(
          secondMaximum,
          Math.max(available - firstMinimum, available / 2),
        )
      : secondMaximum;
  const minimum = Math.min(secondMinimum, maximum);
  const clamp = (size: number) => Math.max(minimum, Math.min(maximum, size));
  const readSize = () => {
    const rect = root.current?.lastElementChild?.getBoundingClientRect();
    return (horizontal ? rect?.width : rect?.height) ?? 0;
  };

  useEffect(() => {
    const element = root.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const rect = element.getBoundingClientRect();
      const divider = handle.current?.getBoundingClientRect();
      const second = element.lastElementChild?.getBoundingClientRect();
      const next = {
        available: horizontal
          ? rect.width - (divider?.width ?? 0)
          : rect.height - (divider?.height ?? 0),
        second: (horizontal ? second?.width : second?.height) ?? 0,
      };
      setMeasurements((current) =>
        current.available === next.available && current.second === next.second
          ? current
          : next,
      );
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    if (element.lastElementChild) observer.observe(element.lastElementChild);
    measure();
    return () => observer.disconnect();
  }, [horizontal, fixedSize]);

  useEffect(() => {
    try {
      if (preferredSize === null) window.sessionStorage.removeItem(storageKey);
      else window.sessionStorage.setItem(storageKey, String(preferredSize));
    } catch {
      // Resizing still works when browser storage is unavailable.
    }
  }, [preferredSize, storageKey]);

  useEffect(() => {
    if (!dragging) return;
    const style = document.documentElement.style;
    const { cursor, userSelect } = style;
    style.cursor = horizontal ? "col-resize" : "row-resize";
    style.userSelect = "none";
    return () => {
      style.cursor = cursor;
      style.userSelect = userSelect;
    };
  }, [dragging, horizontal]);

  function finishDrag() {
    drag.current = null;
    setDragging(false);
  }

  return (
    <div
      ref={root}
      className={`resizable-panels ${className}`}
      data-direction={direction}
      data-resizing={dragging}
      style={
        {
          "--resized-panel-size":
            fixedSize !== undefined
              ? `${fixedSize}px`
              : preferredSize === null
                ? undefined
                : `${clamp(preferredSize)}px`,
          "--panel-min-size":
            fixedSize !== undefined ? `${fixedSize}px` : `${minimum}px`,
          "--panel-max-size":
            fixedSize !== undefined
              ? `${fixedSize}px`
              : Number.isFinite(maximum)
                ? `${maximum}px`
                : undefined,
        } as CSSProperties
      }
    >
      {children[0]}
      <div
        ref={handle}
        className="panel-resize-handle"
        role="separator"
        aria-label={label}
        aria-orientation={horizontal ? "vertical" : "horizontal"}
        aria-valuemin={Math.round(minimum)}
        aria-valuemax={
          Number.isFinite(maximum) ? Math.round(maximum) : undefined
        }
        aria-valuenow={Math.round(clamp(measurements.second || minimum))}
        aria-valuetext={`${Math.round(measurements.second)} pixels`}
        aria-hidden={fixedSize !== undefined}
        tabIndex={fixedSize === undefined ? 0 : -1}
        title="Drag to resize · Arrow keys to adjust · Double-click to reset"
        data-dragging={dragging}
        onDoubleClick={() => setPreferredSize(null)}
        onPointerDown={(event) => {
          if (fixedSize !== undefined || !event.isPrimary || event.button !== 0)
            return;
          event.preventDefault();
          event.currentTarget.focus();
          event.currentTarget.setPointerCapture(event.pointerId);
          drag.current = {
            pointer: event.pointerId,
            start: horizontal ? event.clientX : event.clientY,
            size: readSize(),
          };
          setDragging(true);
        }}
        onPointerMove={(event) => {
          const current = drag.current;
          if (!current || current.pointer !== event.pointerId) return;
          const position = horizontal ? event.clientX : event.clientY;
          setPreferredSize(clamp(current.size + current.start - position));
        }}
        onPointerUp={finishDrag}
        onPointerCancel={finishDrag}
        onLostPointerCapture={finishDrag}
        onKeyDown={(event) => {
          if (fixedSize !== undefined) return;
          const increase = horizontal ? "ArrowLeft" : "ArrowUp";
          const decrease = horizontal ? "ArrowRight" : "ArrowDown";
          if (![increase, decrease, "Home", "End", "Enter"].includes(event.key))
            return;
          event.preventDefault();
          if (event.key === "Enter") setPreferredSize(null);
          else if (event.key === "Home") setPreferredSize(minimum);
          else if (event.key === "End" && Number.isFinite(maximum))
            setPreferredSize(maximum);
          else
            setPreferredSize(
              clamp(readSize() + (event.key === increase ? 16 : -16)),
            );
        }}
      >
        <span aria-hidden="true" />
      </div>
      {children[1]}
    </div>
  );
}
