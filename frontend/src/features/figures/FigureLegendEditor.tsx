import { useState } from "react";
import type {
  FigureDocument,
  FigureLegend,
  FigureOperation,
} from "../../api/schemas/figureCompositions";
import { panelTitle } from "./FigurePageCanvas";

/** Panels in label order (A … Z, AA …); unlabelled panels follow in drawing order. */
function orderedPanels(document: FigureDocument) {
  const label = (id: string) => document.panels[id]?.label ?? "";
  const labelled = document.content.panels
    .filter((panel) => label(panel.id))
    .sort(
      (a, b) =>
        label(a.id).length - label(b.id).length ||
        label(a.id).localeCompare(label(b.id), undefined, { numeric: true }),
    );
  return [
    ...labelled,
    ...document.content.panels.filter((panel) => !label(panel.id)),
  ];
}

export function legendText(document: FigureDocument): string {
  const legend = document.content.legend;
  const entries = orderedPanels(document)
    .map((panel) => {
      const text = legend.entries[panel.id]?.trim();
      if (!text) return null;
      const label = document.panels[panel.id]?.label;
      return label ? `(${label}) ${text}` : text;
    })
    .filter(Boolean);
  return [`${document.content.title}.`, legend.title.trim(), ...entries]
    .filter(Boolean)
    .join(" ");
}

export function FigureLegendEditor({
  document,
  busy,
  onApply,
}: {
  document: FigureDocument;
  busy: boolean;
  onApply: (operations: FigureOperation[], summary: string) => Promise<boolean>;
}) {
  const [copied, setCopied] = useState(false);
  const legend = document.content.legend;
  function save(next: FigureLegend) {
    const entries = Object.fromEntries(
      Object.entries(next.entries).filter(([, text]) => text.trim()),
    );
    const cleaned = { title: next.title.trim(), entries };
    if (JSON.stringify(cleaned) !== JSON.stringify(legend))
      void onApply([{ op: "set_legend", legend: cleaned }], "Edited legend");
  }
  const panels = orderedPanels(document);
  return (
    <div
      className="composition-inspector composition-legend"
      aria-label="Figure legend"
    >
      <header>
        <span className="composition-kicker">Legend</span>
        <h2>Manuscript text</h2>
        <small>
          The legend is exported as text. Entries follow their panels when
          labels change.
        </small>
      </header>
      <fieldset disabled={busy}>
        <label className="composition-field composition-field-stacked">
          <span>Figure summary</span>
          <textarea
            key={legend.title}
            defaultValue={legend.title}
            maxLength={1000}
            rows={2}
            placeholder="One sentence describing the whole figure."
            onBlur={(event) => save({ ...legend, title: event.target.value })}
          />
        </label>
        {panels.map((panel) => {
          const label = document.panels[panel.id]?.label;
          return (
            <label
              key={panel.id}
              className="composition-field composition-field-stacked"
            >
              <span>
                {label ? `(${label}) ` : ""}
                {panelTitle(document, panel)}
              </span>
              <textarea
                key={legend.entries[panel.id] ?? ""}
                defaultValue={legend.entries[panel.id] ?? ""}
                maxLength={4000}
                rows={3}
                aria-label={`Legend for panel ${label ?? panelTitle(document, panel)}`}
                onBlur={(event) =>
                  save({
                    ...legend,
                    entries: {
                      ...legend.entries,
                      [panel.id]: event.target.value,
                    },
                  })
                }
              />
            </label>
          );
        })}
        {!panels.length ? <p>Add panels to describe them here.</p> : null}
      </fieldset>
      <section
        className="composition-legend-preview"
        aria-label="Legend preview"
      >
        <p>{legendText(document)}</p>
        <button
          type="button"
          onClick={() =>
            void navigator.clipboard
              ?.writeText(legendText(document))
              .then(() => setCopied(true))
          }
        >
          {copied ? "Copied" : "Copy legend"}
        </button>
      </section>
    </div>
  );
}
