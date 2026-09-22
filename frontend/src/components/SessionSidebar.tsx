import { useState, type ReactNode } from "react";
import { SidebarIcon } from "./Icons";
import "./sessionSidebar.css";

export type SessionItem = { id: string; title: string; detail: string };

/**
 * The fixed list of an interface's saved work: conversations, canvases, reports, slides, or
 * figures. It stays beside the open item so earlier work is always one click away.
 */
export function SessionSidebar({
  label,
  newLabel,
  items,
  activeId,
  loading = false,
  error,
  emptyText,
  onSelect,
  onNew,
  onRetry,
  footer,
  openFrom = 960,
}: {
  label: string;
  newLabel: string;
  items: SessionItem[];
  activeId: string | null;
  loading?: boolean;
  error?: string | null;
  emptyText: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRetry?: () => void;
  footer?: ReactNode;
  /** The narrowest window, in pixels, where the list starts open. */
  openFrom?: number;
}) {
  const openKey = `vis-platform.sessions-open.${label.toLowerCase()}`;
  const [open, setOpen] = useState(() => initiallyOpen(openKey, openFrom));
  // On a narrow screen the open list covers the work, so a choice closes it.
  function chose(action: () => void) {
    action();
    if (!(window.matchMedia?.("(min-width: 960px)").matches ?? true))
      setOpen(false);
  }
  function toggle() {
    setOpen(!open);
    try {
      window.localStorage.setItem(openKey, String(!open));
    } catch {
      /* The list still opens and closes without storage. */
    }
  }
  return (
    <nav className="session-sidebar" aria-label={label} data-open={open}>
      <div className="session-sidebar-head">
        <button
          type="button"
          className="session-sidebar-toggle"
          aria-expanded={open}
          aria-label={`${open ? "Hide" : "Show"} ${label.toLowerCase()}`}
          title={`${open ? "Hide" : "Show"} ${label.toLowerCase()}`}
          onClick={toggle}
        >
          <SidebarIcon />
        </button>
        {open ? <strong>{label}</strong> : null}
      </div>
      <button
        type="button"
        className="session-sidebar-new"
        aria-label={newLabel}
        title={newLabel}
        onClick={() => chose(onNew)}
      >
        <span aria-hidden="true">+</span>
        {open ? newLabel : null}
      </button>
      {open ? (
        <>
          {items.length ? (
            <ol className="session-sidebar-list">
              {items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    aria-current={item.id === activeId ? "page" : undefined}
                    onClick={() => chose(() => onSelect(item.id))}
                  >
                    <span>{item.title}</span>
                    <small>{item.detail}</small>
                  </button>
                </li>
              ))}
            </ol>
          ) : null}
          {error ? (
            <p className="session-sidebar-note" role="alert">
              {error}{" "}
              {onRetry ? (
                <button type="button" onClick={onRetry}>
                  Retry
                </button>
              ) : null}
            </p>
          ) : loading ? (
            <p className="session-sidebar-note">Loading…</p>
          ) : !items.length ? (
            <p className="session-sidebar-note">{emptyText}</p>
          ) : null}
          {footer}
        </>
      ) : null}
    </nav>
  );
}

/**
 * The list keeps the choice made in its interface. Otherwise it starts open where it leaves
 * the work enough room; on narrow screens it would cover the work.
 */
function initiallyOpen(openKey: string, openFrom: number): boolean {
  if (!(window.matchMedia?.("(min-width: 960px)").matches ?? true))
    return false;
  try {
    const chosen = window.localStorage.getItem(openKey);
    if (chosen !== null) return chosen === "true";
  } catch {
    /* Without storage the default applies. */
  }
  return window.matchMedia?.(`(min-width: ${openFrom}px)`).matches ?? true;
}

export function editedOn(timestamp: string): string {
  return `Edited ${new Date(timestamp).toLocaleDateString()}`;
}
