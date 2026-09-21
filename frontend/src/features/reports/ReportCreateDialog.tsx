import { useRef, useState } from "react";
import { createMutationId } from "../../api/client";
import {
  reportContentSchema,
  reportImportSchema,
  type ReportImportContent,
} from "../../api/schemas/reports";
import { DatasetSelector } from "../datasets/DatasetSelector";
import { ReportDialog, downloadReportFile } from "./ReportDialog";

export function ReportCreateDialog({
  projectId,
  mode,
  onClose,
  onCreate,
}: {
  projectId: string;
  mode: "new" | "import";
  onClose: () => void;
  onCreate: (content: ReportImportContent, key: string) => Promise<void>;
}) {
  const [title, setTitle] = useState("Untitled report");
  const [structure, setStructure] = useState<"results" | "article">("results");
  const [datasetIds, setDatasetIds] = useState<string[]>([]);
  const [imported, setImported] = useState<ReportImportContent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const key = useRef({ fingerprint: "", id: "" });
  const sectionIds = useRef(
    Array.from({ length: 4 }, () => createMutationId()),
  );
  return (
    <ReportDialog
      title={mode === "new" ? "New report" : "Import pre-report"}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form
        className="report-dialog-form"
        onSubmit={async (event) => {
          event.preventDefault();
          if (busy) return;
          const content =
            mode === "import"
              ? imported
              : reportContentSchema.parse({
                  title: title.trim(),
                  datasets: datasetIds.map((dataset_id) => ({ dataset_id })),
                  sections: (structure === "article"
                    ? ["Abstract", "Introduction", "Results", "Discussion"]
                    : ["Results"]
                  ).map((title, index) => ({
                    id: sectionIds.current[index]!,
                    title,
                    blocks: [],
                  })),
                });
          if (!content) return;
          setBusy(true);
          setError(null);
          const fingerprint = JSON.stringify(content);
          if (key.current.fingerprint !== fingerprint)
            key.current = { fingerprint, id: createMutationId() };
          try {
            await onCreate(content, key.current.id);
          } catch (reason) {
            setError(
              reason instanceof Error
                ? reason.message
                : "The report could not be created.",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        {mode === "new" ? (
          <>
            <p>
              Start with your data and develop your report section by section.
            </p>
            <label>
              Report title
              <input
                required
                value={title}
                maxLength={200}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
            <label>
              Structure
              <select
                aria-label="Report structure"
                value={structure}
                onChange={(event) =>
                  setStructure(event.target.value as "results" | "article")
                }
              >
                <option value="results">Results report</option>
                <option value="article">Research article</option>
              </select>
            </label>
            <div className="report-data-choice">
              <strong>Data for this report</strong>
              <DatasetSelector
                projectId={projectId}
                ensureProject={async () => projectId}
                selectedIds={datasetIds}
                onSelect={setDatasetIds}
                resultIds={[]}
                onUseResult={() => {}}
                datasetsOnly
                disabled={busy}
              />
            </div>
            <small>
              You can add data later. Sections can be renamed, added, or
              reordered as you write.
            </small>
          </>
        ) : (
          <>
            <p>
              Load a structured report with datasets, topics, figures, tables,
              and text.
            </p>
            <label className="report-import-drop">
              Pre-report file
              <input
                type="file"
                accept=".json,application/json"
                disabled={busy}
                onChange={async (event) => {
                  setImported(null);
                  setError(null);
                  const file = event.target.files?.[0];
                  if (!file) return;
                  try {
                    if (file.size > 2_000_000)
                      throw new Error(
                        "Choose a report file smaller than 2 MB.",
                      );
                    const content = reportImportSchema.parse(
                      JSON.parse(await file.text()),
                    );
                    setImported(content);
                  } catch (reason) {
                    setError(
                      reason instanceof Error
                        ? reason.message
                        : "The pre-report is invalid.",
                    );
                  }
                }}
              />
            </label>
            {imported ? (
              <div className="report-import-summary">
                <strong>{imported.title}</strong>
                <span>
                  {
                    ("sections" in imported
                      ? imported.sections
                      : imported.topics
                    ).length
                  }{" "}
                  topics ·{" "}
                  {("sections" in imported
                    ? imported.sections
                    : imported.topics
                  ).reduce((n, t) => n + t.blocks.length, 0)}{" "}
                  content blocks · {imported.datasets.length} datasets
                </span>
              </div>
            ) : null}
            <small>
              Dataset and saved figure references must belong to this project.
              Images can be uploaded and included by their saved image
              reference.
            </small>
            <button
              type="button"
              className="report-text-button"
              onClick={() =>
                downloadReportFile(
                  JSON.stringify(
                    {
                      schema_version: "2.0",
                      title: "Research report",
                      datasets: [],
                      sections: [
                        {
                          id: "overview",
                          title: "Study overview",
                          blocks: [
                            {
                              id: "intro",
                              type: "text",
                              body: "Describe the study and its scientific question.",
                            },
                          ],
                        },
                        { id: "results", title: "Results", blocks: [] },
                      ],
                    },
                    null,
                    2,
                  ),
                  "pre-report-template.json",
                )
              }
            >
              Download a starter template
            </button>
          </>
        )}
        {error ? (
          <p className="report-error" role="alert">
            {error}
          </p>
        ) : null}
        <footer>
          <button type="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="submit"
            className="report-primary"
            disabled={busy || (mode === "new" ? !title.trim() : !imported)}
          >
            {busy
              ? "Creating…"
              : mode === "new"
                ? "Create report"
                : "Import report"}
          </button>
        </footer>
      </form>
    </ReportDialog>
  );
}
