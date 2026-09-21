import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { getFigureExport, type FigureExportFormat } from "../../api/client";
import type { PlotResult } from "../../api/schemas/plotRun";
import { DownloadIcon } from "../../components/Icons";
import "./figureExport.css";

const formats: { id: FigureExportFormat; label: string; detail: string }[] = [
  { id: "png", label: "PNG", detail: "High resolution · 300 dpi" },
  { id: "pdf", label: "PDF", detail: "Vector document" },
  { id: "svg", label: "SVG", detail: "Vector image" },
];

export function FigureExportMenu({
  projectId,
  result,
  label = "Export",
}: {
  projectId: string;
  result: PlotResult;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const [pending, setPending] = useState<FigureExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const options = useRef<(HTMLButtonElement | null)[]>([]);
  const inFlight = useRef(false);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    options.current[0]?.focus();
    function dismiss(event: PointerEvent) {
      const target = event.target as Node;
      if (!button.current?.contains(target) && !menu.current?.contains(target))
        setOpen(false);
    }
    function resize() {
      setOpen(false);
    }
    document.addEventListener("pointerdown", dismiss);
    window.addEventListener("resize", resize);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      window.removeEventListener("resize", resize);
    };
  }, [open]);

  async function download(format: FigureExportFormat) {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(format);
    setError(null);
    try {
      const exported = await getFigureExport(
        projectId,
        result.plot_id,
        result.version_id,
        format,
      );
      const href = URL.createObjectURL(exported.blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = exported.filename;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(href), 1000);
      setOpen(false);
      button.current?.focus();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The figure could not be exported. Please retry.",
      );
    } finally {
      inFlight.current = false;
      setPending(null);
    }
  }

  return (
    <>
      <button
        ref={button}
        type="button"
        className="export-action"
        aria-label={label}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-controls={open ? id : undefined}
        disabled={pending != null}
        onClick={() => {
          const bounds = button.current!.getBoundingClientRect();
          setPosition({
            top: Math.max(
              8,
              Math.min(bounds.bottom + 8, window.innerHeight - 288),
            ),
            left: Math.max(
              8,
              Math.min(bounds.right - 232, window.innerWidth - 240),
            ),
          });
          setError(null);
          setOpen((current) => !current);
        }}
      >
        <DownloadIcon />
        {pending ? `Preparing ${pending.toUpperCase()}…` : label}
        <span className="export-chevron" aria-hidden="true">
          ⌄
        </span>
      </button>
      {open
        ? createPortal(
            <div
              ref={menu}
              id={id}
              className="figure-export-menu"
              role="menu"
              aria-label="Export format"
              style={{
                ...position,
                maxHeight: `calc(100dvh - ${position.top + 8}px)`,
              }}
              onKeyDown={(event) => {
                if (event.key === "Escape" || event.key === "Tab") {
                  if (event.key === "Escape") event.preventDefault();
                  setOpen(false);
                  button.current?.focus();
                  return;
                }
                if (
                  !["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)
                )
                  return;
                event.preventDefault();
                const current = options.current.indexOf(
                  document.activeElement as HTMLButtonElement,
                );
                const next =
                  event.key === "Home"
                    ? 0
                    : event.key === "End"
                      ? formats.length - 1
                      : (current +
                          (event.key === "ArrowDown"
                            ? 1
                            : formats.length - 1)) %
                        formats.length;
                options.current[next]?.focus();
              }}
            >
              <div className="figure-export-heading" role="presentation">
                <strong>Download figure</strong>
                <span>
                  {result.figure_size
                    ? `${result.figure_size.width} × ${result.figure_size.height} in`
                    : "Saved figure size"}
                </span>
              </div>
              {formats.map((format, index) => (
                <button
                  key={format.id}
                  ref={(node) => {
                    options.current[index] = node;
                  }}
                  type="button"
                  role="menuitem"
                  aria-label={`Download ${format.label}`}
                  disabled={pending != null}
                  onClick={() => void download(format.id)}
                >
                  <span className="export-format-mark" aria-hidden="true">
                    {format.label}
                  </span>
                  <span>
                    <strong>
                      {pending === format.id ? "Preparing…" : format.label}
                    </strong>
                    <small>{format.detail}</small>
                  </span>
                </button>
              ))}
              {error ? (
                <p className="figure-export-error" role="alert">
                  {error}
                </p>
              ) : null}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
