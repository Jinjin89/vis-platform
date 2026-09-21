import { useState } from "react";
import type {
  FigureDocument,
  FigureOperation,
  FigurePage,
  FigurePanel,
  PanelLabelStyle,
} from "../../api/schemas/figureCompositions";
import {
  PAGE_PRESETS,
  align,
  clampScale,
  distribute,
  plotNaturalSize,
  presetId,
  round,
  type Alignment,
} from "./figureGeometry";
import { naturalSize, panelTitle } from "./FigurePageCanvas";

type Apply = (
  operations: FigureOperation[],
  summary: string,
) => Promise<boolean>;

function NumberField({
  label,
  value,
  unit,
  min,
  max,
  step = 0.1,
  disabled,
  onCommit,
}: {
  label: string;
  value: number;
  unit: string;
  min: number;
  max: number;
  step?: number;
  disabled?: boolean;
  onCommit: (value: number) => void;
}) {
  const shown = String(round(value, step));
  const [text, setText] = useState(shown);
  const [base, setBase] = useState(shown);
  if (base !== shown) {
    setBase(shown);
    setText(shown);
  }
  function commit() {
    const parsed = Number(text);
    if (text.trim() === "" || !Number.isFinite(parsed)) {
      setText(shown);
      return;
    }
    const next = Math.min(max, Math.max(min, parsed));
    if (Math.abs(next - value) >= step / 2) onCommit(next);
    else setText(shown);
  }
  return (
    <label className="figure-field">
      <span>{label}</span>
      <span className="figure-field-input">
        <input
          type="number"
          inputMode="decimal"
          value={text}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
          onChange={(event) => setText(event.target.value)}
          onBlur={commit}
          onKeyDown={(event) => {
            if (event.key === "Enter") commit();
          }}
        />
        <small>{unit}</small>
      </span>
    </label>
  );
}

export function FigureInspector({
  document,
  selected,
  busy,
  onApply,
  onSelect,
}: {
  document: FigureDocument;
  selected: string[];
  busy: boolean;
  onApply: Apply;
  onSelect: (ids: string[]) => void;
}) {
  const panels = document.content.panels.filter((panel) =>
    selected.includes(panel.id),
  );
  if (panels.length === 1)
    return (
      <PanelInspector
        key={panels[0]!.id}
        document={document}
        panel={panels[0]!}
        busy={busy}
        onApply={onApply}
        onSelect={onSelect}
      />
    );
  if (panels.length > 1)
    return (
      <GroupInspector
        document={document}
        panels={panels}
        busy={busy}
        onApply={onApply}
        onSelect={onSelect}
      />
    );
  return <PageInspector document={document} busy={busy} onApply={onApply} />;
}

function PanelInspector({
  document,
  panel,
  busy,
  onApply,
  onSelect,
}: {
  document: FigureDocument;
  panel: FigurePanel;
  busy: boolean;
  onApply: Apply;
  onSelect: (ids: string[]) => void;
}) {
  const resolved = document.panels[panel.id];
  const natural = naturalSize(document, panel.id);
  const page = document.content.page;
  const panels = document.content.panels;
  const index = panels.findIndex((item) => item.id === panel.id);
  const update = document.updates[panel.id];
  const geometry = (changes: Partial<FigurePanel>, summary: string) =>
    onApply(
      [
        {
          op: "set_panel_geometry",
          panels: {
            [panel.id]: {
              x_mm: changes.x_mm ?? panel.x_mm,
              y_mm: changes.y_mm ?? panel.y_mm,
              scale: changes.scale ?? panel.scale,
            },
          },
        },
      ],
      summary,
    );
  const replace = (changes: Partial<FigurePanel>, summary: string) =>
    onApply(
      [{ op: "replace_panel", panel: { ...panel, ...changes } }],
      summary,
    );
  function applyUpdate() {
    if (!update || panel.content.type !== "plot") return;
    const next = plotNaturalSize(document.figures[update]);
    const width = resolved?.frame.width_mm ?? natural.width * panel.scale;
    void replace(
      {
        content: { type: "plot", version_id: update, ignored_version_id: null },
        scale: next
          ? clampScale(panel, next, page, width / next.width)
          : panel.scale,
      },
      "Applied the newer plot version",
    );
  }
  return (
    <div className="figure-inspector" aria-label="Panel properties">
      <header>
        <span className="figure-kicker">
          Panel {resolved?.label ?? "(no label)"}
        </span>
        <h2>{panelTitle(document, panel)}</h2>
        <small>
          {panel.content.type === "plot" ? "Saved plot" : "Uploaded image"} ·
          natural size {round(natural.width, 1)} × {round(natural.height, 1)} mm
        </small>
      </header>
      {update ? (
        <div className="figure-update" role="status">
          <strong>A newer version of this plot is available.</strong>
          <p>Applying it keeps the panel’s width on the page.</p>
          <div>
            <button type="button" disabled={busy} onClick={applyUpdate}>
              Apply update
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                panel.content.type === "plot" &&
                void replace(
                  {
                    content: { ...panel.content, ignored_version_id: update },
                  },
                  "Kept the current plot version",
                )
              }
            >
              Keep current
            </button>
          </div>
        </div>
      ) : null}
      <fieldset disabled={busy}>
        <legend>Label</legend>
        <label className="figure-field">
          <span>Custom label</span>
          <input
            key={`${panel.label ?? ""}-${resolved?.label ?? ""}`}
            defaultValue={panel.label ?? ""}
            placeholder={resolved?.label ?? "Automatic"}
            maxLength={8}
            aria-describedby={`label-help-${panel.id}`}
            onBlur={(event) => {
              const value = event.target.value.trim() || null;
              if (value !== panel.label)
                void replace({ label: value }, "Changed panel label");
            }}
          />
        </label>
        <small id={`label-help-${panel.id}`}>
          Leave empty to label panels in reading order.
        </small>
        <label className="figure-check">
          <input
            type="checkbox"
            checked={panel.show_label}
            onChange={(event) =>
              void replace(
                { show_label: event.target.checked },
                event.target.checked ? "Showed panel label" : "Hid panel label",
              )
            }
          />
          Show label
        </label>
      </fieldset>
      <fieldset disabled={busy || panel.locked}>
        <legend>Position and size</legend>
        <div className="figure-field-grid">
          <NumberField
            label="X"
            unit="mm"
            value={panel.x_mm}
            min={0}
            max={page.width_mm - (resolved?.frame.width_mm ?? 0)}
            onCommit={(x_mm) => void geometry({ x_mm }, "Moved panel")}
          />
          <NumberField
            label="Y"
            unit="mm"
            value={panel.y_mm}
            min={0}
            max={page.height_mm - (resolved?.frame.height_mm ?? 0)}
            onCommit={(y_mm) => void geometry({ y_mm }, "Moved panel")}
          />
          <NumberField
            label="Width"
            unit="mm"
            value={natural.width * panel.scale}
            min={1}
            max={page.width_mm}
            onCommit={(width) =>
              void geometry(
                {
                  scale: clampScale(
                    panel,
                    natural,
                    page,
                    width / natural.width,
                  ),
                },
                "Resized panel",
              )
            }
          />
          <NumberField
            label="Scale"
            unit="%"
            step={1}
            value={panel.scale * 100}
            min={5}
            max={1000}
            onCommit={(percent) =>
              void geometry(
                { scale: clampScale(panel, natural, page, percent / 100) },
                "Resized panel",
              )
            }
          />
        </div>
        <small>
          Height {round(natural.height * panel.scale, 0.1)} mm follows the
          content’s proportions.
        </small>
      </fieldset>
      <fieldset disabled={busy}>
        <legend>Arrange</legend>
        <label className="figure-check">
          <input
            type="checkbox"
            checked={panel.locked}
            onChange={(event) =>
              void replace(
                { locked: event.target.checked },
                event.target.checked ? "Locked panel" : "Unlocked panel",
              )
            }
          />
          Lock position
        </label>
        <div className="figure-button-row">
          <button
            type="button"
            disabled={index === panels.length - 1}
            onClick={() =>
              void onApply(
                [{ op: "move_panel", panel_id: panel.id, before_id: null }],
                "Brought panel to front",
              )
            }
          >
            Bring to front
          </button>
          <button
            type="button"
            disabled={index === 0}
            onClick={() =>
              void onApply(
                [
                  {
                    op: "move_panel",
                    panel_id: panel.id,
                    before_id: panels[0]!.id,
                  },
                ],
                "Sent panel to back",
              )
            }
          >
            Send to back
          </button>
        </div>
        <button
          type="button"
          className="figure-danger"
          onClick={async () => {
            if (
              await onApply(
                [{ op: "remove_panel", panel_id: panel.id }],
                "Removed panel",
              )
            )
              onSelect([]);
          }}
        >
          Remove panel
        </button>
      </fieldset>
    </div>
  );
}

const alignments: { value: Alignment; label: string }[] = [
  { value: "left", label: "Align left" },
  { value: "center", label: "Align centres" },
  { value: "right", label: "Align right" },
  { value: "top", label: "Align top" },
  { value: "middle", label: "Align middles" },
  { value: "bottom", label: "Align bottom" },
];

function GroupInspector({
  document,
  panels,
  busy,
  onApply,
  onSelect,
}: {
  document: FigureDocument;
  panels: FigurePanel[];
  busy: boolean;
  onApply: Apply;
  onSelect: (ids: string[]) => void;
}) {
  const movable = panels.filter((panel) => !panel.locked);
  const frames = Object.fromEntries(
    movable.map((panel) => [panel.id, document.panels[panel.id]!.frame]),
  );
  function place(
    positions: Record<string, { x_mm: number; y_mm: number }>,
    summary: string,
  ) {
    void onApply(
      [
        {
          op: "set_panel_geometry",
          panels: Object.fromEntries(
            movable.map((panel) => [
              panel.id,
              { ...positions[panel.id]!, scale: panel.scale },
            ]),
          ),
        },
      ],
      summary,
    );
  }
  return (
    <div className="figure-inspector" aria-label="Selected panels">
      <header>
        <span className="figure-kicker">{panels.length} panels selected</span>
        <h2>Arrange together</h2>
        {movable.length < panels.length ? (
          <small>Locked panels keep their positions.</small>
        ) : null}
      </header>
      <fieldset disabled={busy || movable.length < 2}>
        <legend>Align</legend>
        <div className="figure-button-grid">
          {alignments.map((item) => (
            <button
              type="button"
              key={item.value}
              onClick={() => place(align(frames, item.value), item.label)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </fieldset>
      <fieldset disabled={busy || movable.length < 3}>
        <legend>Distribute</legend>
        <div className="figure-button-row">
          <button
            type="button"
            onClick={() =>
              place(distribute(frames, "x"), "Distributed panels horizontally")
            }
          >
            Horizontally
          </button>
          <button
            type="button"
            onClick={() =>
              place(distribute(frames, "y"), "Distributed panels vertically")
            }
          >
            Vertically
          </button>
        </div>
      </fieldset>
      <fieldset disabled={busy}>
        <legend>Remove</legend>
        <button
          type="button"
          className="figure-danger"
          onClick={async () => {
            if (
              await onApply(
                panels.map((panel) => ({
                  op: "remove_panel" as const,
                  panel_id: panel.id,
                })),
                "Removed panels",
              )
            )
              onSelect([]);
          }}
        >
          Remove {panels.length} panels
        </button>
      </fieldset>
    </div>
  );
}

function PageInspector({
  document,
  busy,
  onApply,
}: {
  document: FigureDocument;
  busy: boolean;
  onApply: Apply;
}) {
  const { page, labels } = document.content;
  const preset = presetId(page);
  const setPage = (next: FigurePage, summary: string) =>
    onApply([{ op: "set_page", page: next }], summary);
  const setLabels = (next: Partial<PanelLabelStyle>) =>
    onApply(
      [{ op: "set_label_style", labels: { ...labels, ...next } }],
      "Changed label style",
    );
  return (
    <div className="figure-inspector" aria-label="Page settings">
      <header>
        <span className="figure-kicker">Page</span>
        <h2>
          {page.width_mm} × {round(document.page_height_mm, 1)} mm
        </h2>
        <small>
          {page.height_mode === "auto"
            ? `Height follows the content, up to ${page.height_mm} mm.`
            : "Fixed page height."}{" "}
          Select a panel to edit it.
        </small>
      </header>
      <fieldset disabled={busy}>
        <legend>Size</legend>
        <label className="figure-field">
          <span>Preset</span>
          <select
            aria-label="Page preset"
            value={preset}
            onChange={(event) => {
              const chosen = PAGE_PRESETS.find(
                (item) => item.id === event.target.value,
              );
              if (chosen)
                void setPage(chosen.page, `Changed page to ${chosen.label}`);
            }}
          >
            {PAGE_PRESETS.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
            <option value="custom" disabled>
              Custom
            </option>
          </select>
        </label>
        <div className="figure-field-grid">
          <NumberField
            label="Width"
            unit="mm"
            value={page.width_mm}
            min={20}
            max={500}
            onCommit={(width_mm) =>
              void setPage({ ...page, width_mm }, "Changed page width")
            }
          />
          <NumberField
            label={page.height_mode === "auto" ? "Max height" : "Height"}
            unit="mm"
            value={page.height_mm}
            min={20}
            max={1000}
            onCommit={(height_mm) =>
              void setPage({ ...page, height_mm }, "Changed page height")
            }
          />
          <NumberField
            label="Margin"
            unit="mm"
            value={page.margin_mm}
            min={0}
            max={50}
            onCommit={(margin_mm) =>
              void setPage({ ...page, margin_mm }, "Changed page margin")
            }
          />
        </div>
        <label className="figure-check">
          <input
            type="checkbox"
            checked={page.height_mode === "auto"}
            onChange={(event) =>
              void setPage(
                {
                  ...page,
                  height_mode: event.target.checked ? "auto" : "fixed",
                },
                event.target.checked
                  ? "Page height follows content"
                  : "Fixed page height",
              )
            }
          />
          Fit height to content
        </label>
      </fieldset>
      <fieldset disabled={busy}>
        <legend>Panel labels</legend>
        <div className="figure-field-grid">
          <label className="figure-field">
            <span>Letters</span>
            <select
              aria-label="Label letters"
              value={labels.case}
              onChange={(event) =>
                void setLabels({
                  case: event.target.value as PanelLabelStyle["case"],
                })
              }
            >
              <option value="upper">A, B, C</option>
              <option value="lower">a, b, c</option>
            </select>
          </label>
          <NumberField
            label="Size"
            unit="pt"
            step={0.5}
            value={labels.size_pt}
            min={5}
            max={24}
            onCommit={(size_pt) => void setLabels({ size_pt })}
          />
          <label className="figure-field">
            <span>Font</span>
            <select
              aria-label="Label font"
              value={labels.font_family}
              onChange={(event) =>
                void setLabels({ font_family: event.target.value })
              }
            >
              {["Arial", "Helvetica", "Times New Roman"].map((font) => (
                <option key={font}>{font}</option>
              ))}
              {["Arial", "Helvetica", "Times New Roman"].includes(
                labels.font_family,
              ) ? null : (
                <option>{labels.font_family}</option>
              )}
            </select>
          </label>
        </div>
        <label className="figure-check">
          <input
            type="checkbox"
            checked={labels.bold}
            onChange={(event) => void setLabels({ bold: event.target.checked })}
          />
          Bold labels
        </label>
      </fieldset>
    </div>
  );
}
