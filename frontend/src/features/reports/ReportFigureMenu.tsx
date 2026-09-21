import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

export type FigureAction =
  "refine" | "new" | "code" | "export" | "remove" | "link";
export function ReportFigureMenu({
  x,
  y,
  editable,
  linked,
  formatName = "report",
  busy,
  onAction,
  onClose,
  trigger,
}: {
  x: number;
  y: number;
  editable: boolean;
  linked?: boolean;
  formatName?: "report" | "slide";
  busy: boolean;
  onAction: (action: FigureAction) => void;
  onClose: () => void;
  trigger: HTMLElement | null;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current
      ?.querySelector<HTMLButtonElement>("button:not(:disabled)")
      ?.focus();
    const close = (event: PointerEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose();
    };
    const resize = () => onClose();
    document.addEventListener("pointerdown", close);
    window.addEventListener("resize", resize);
    return () => {
      document.removeEventListener("pointerdown", close);
      window.removeEventListener("resize", resize);
      trigger?.focus({ preventScroll: true });
    };
  }, [onClose, trigger]);
  const options: { action: FigureAction; label: string; disabled?: boolean }[] =
    [
      {
        action: "refine",
        label: editable ? "Refine this figure" : "Create an editable version",
        disabled: busy,
      },
      {
        action: "new",
        label: `New figure in this ${formatName === "slide" ? "slide" : "section"}`,
      },
      { action: "code", label: "View R code", disabled: !editable },
      { action: "export", label: "Export image" },
      ...(linked !== undefined && editable
        ? [
            {
              action: "link" as const,
              label: linked
                ? "Pin this version"
                : "Link updates across documents",
              disabled: busy,
            },
          ]
        : []),
      { action: "remove", label: `Remove from ${formatName}`, disabled: busy },
    ];
  return createPortal(
    <div
      ref={ref}
      className="report-figure-menu"
      role="menu"
      aria-label="Figure actions"
      style={{
        left: Math.max(8, Math.min(x, window.innerWidth - 238)),
        top: Math.max(8, Math.min(y, window.innerHeight - 270)),
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onClose();
          return;
        }
        const items = [
          ...ref.current!.querySelectorAll<HTMLButtonElement>(
            "button:not(:disabled)",
          ),
        ];
        const index = items.indexOf(
          document.activeElement as HTMLButtonElement,
        );
        if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
          event.preventDefault();
          items[
            event.key === "Home"
              ? 0
              : event.key === "End"
                ? items.length - 1
                : (index + (event.key === "ArrowDown" ? 1 : items.length - 1)) %
                  items.length
          ]?.focus();
        }
      }}
    >
      {options.map((option) => (
        <button
          type="button"
          role="menuitem"
          key={option.action}
          disabled={option.disabled}
          className={
            option.action === "remove" ? "report-menu-remove" : undefined
          }
          onClick={() => {
            onAction(option.action);
            onClose();
          }}
        >
          {option.label}
        </button>
      ))}
    </div>,
    document.body,
  );
}
