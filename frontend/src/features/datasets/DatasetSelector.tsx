import { DatasetCard } from "./DatasetCard";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createDataset,
  finalizeDataset,
  listAnalysisResults,
  listDatasets,
  listPlatformDatasets,
  uploadDataFile,
} from "../../api/datasets";
import type { AnalysisResult } from "../../api/schemas/datasets";
import { AnalysisResultCard } from "./AnalysisResultCard";
import "./datasets.css";

const allTabs = ["Datasets", "Upload", "Analysis platform", "Results"] as const;
export function DatasetSelector({
  projectId,
  ensureProject,
  selectedIds,
  resultIds,
  onSelect,
  onUseResult,
  disabled,
  datasetsOnly = false,
}: {
  projectId: string | null;
  ensureProject: () => Promise<string>;
  selectedIds: string[];
  resultIds: string[];
  onSelect: (ids: string[]) => void;
  onUseResult: (result: AnalysisResult) => void;
  disabled: boolean;
  datasetsOnly?: boolean;
}) {
  const tabs = datasetsOnly ? allTabs.slice(0, 3) : allTabs;
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<(typeof tabs)[number]>("Datasets");
  const [offset, setOffset] = useState(0);
  const [resultOffset, setResultOffset] = useState(0);
  const [platformCursor, setPlatformCursor] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const client = useQueryClient();
  const catalog = useQuery({
    queryKey: ["datasets", projectId, offset],
    queryFn: () => listDatasets(projectId!, offset),
    enabled: projectId !== null && (open || selectedIds.length > 0),
    refetchInterval: (query) =>
      query.state.data?.datasets.some(
        (dataset) => dataset.state === "processing",
      )
        ? 1000
        : false,
  });
  const results = useQuery({
    queryKey: ["analysis-results", projectId, resultOffset],
    queryFn: () => listAnalysisResults(projectId!, resultOffset),
    enabled:
      !datasetsOnly && projectId !== null && (open || resultIds.length > 0),
  });
  const platform = useQuery({
    queryKey: ["platform-datasets", projectId, platformCursor],
    queryFn: () => listPlatformDatasets(projectId!, platformCursor),
    enabled: open && tab === "Analysis platform" && projectId !== null,
  });
  async function refresh() {
    await client.invalidateQueries({ queryKey: ["datasets", projectId] });
    await client.invalidateQueries({
      queryKey: ["analysis-results", projectId],
    });
  }
  const upload = useMutation({
    mutationFn: async () => {
      const project = await ensureProject();
      const dataset = await createDataset(
        project,
        name.trim(),
        description.trim(),
      );
      for (const file of files)
        await uploadDataFile(project, dataset.dataset_id, file);
      await finalizeDataset(project, dataset.dataset_id);
      return dataset;
    },
    onSuccess: async (dataset) => {
      onSelect([dataset.dataset_id]);
      setOffset(0);
      setTab("Datasets");
      setName("");
      setDescription("");
      setFiles([]);
      if (fileInput.current) fileInput.current.value = "";
      await client.invalidateQueries({ queryKey: ["datasets"] });
    },
  });
  const importDataset = useMutation({
    mutationFn: async (item: {
      source_id: string;
      name: string;
      description?: string;
    }) => {
      const project = await ensureProject();
      const dataset = await createDataset(
        project,
        item.name,
        item.description,
        item.source_id,
      );
      await finalizeDataset(project, dataset.dataset_id);
      return dataset;
    },
    onSuccess: async (dataset) => {
      onSelect([dataset.dataset_id]);
      setTab("Datasets");
      setOffset(0);
      await refresh();
    },
  });
  useEffect(() => {
    if (open) dialog.current?.showModal?.();
    else dialog.current?.close?.();
  }, [open]);
  const chosen =
    catalog.data?.datasets.filter((dataset) =>
      selectedIds.includes(dataset.dataset_id),
    ) ?? [];
  const label = resultIds.length
    ? "Saved analysis selected"
    : chosen.length === 1
      ? chosen[0]!.name
      : selectedIds.length
        ? `${selectedIds.length} datasets selected`
        : "Choose data";
  const error = notice ?? upload.error?.message ?? importDataset.error?.message;
  return (
    <>
      <button
        type="button"
        className="dataset-selector-toggle"
        disabled={disabled}
        aria-label="Choose data"
        aria-haspopup="dialog"
        onClick={async () => {
          setNotice(null);
          setOpen(true);
          try {
            await ensureProject();
          } catch (reason) {
            setNotice(
              reason instanceof Error
                ? reason.message
                : "The data library could not be opened.",
            );
          }
        }}
      >
        <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
          <ellipse
            cx="10"
            cy="4.5"
            rx="6"
            ry="2.5"
            stroke="currentColor"
            strokeWidth="1.4"
          />
          <path
            d="M4 4.5v10c0 3.3 12 3.3 12 0v-10M4 9.5c0 3.3 12 3.3 12 0"
            stroke="currentColor"
            strokeWidth="1.4"
          />
        </svg>
        <span>Data</span>
        <span aria-hidden="true">⌄</span>
      </button>
      <span className="dataset-selection-label">
        {label === "Choose data" ? "No data selected" : label}
      </span>
      {createPortal(
        <dialog
          ref={dialog}
          className="data-library-dialog"
          aria-labelledby="data-library-title"
          onCancel={() => setOpen(false)}
          onClick={(event) => {
            if (event.target === event.currentTarget) setOpen(false);
          }}
        >
          <header>
            <div>
              <span className="data-eyebrow">Project library</span>
              <h2 id="data-library-title">Data & analysis</h2>
            </div>
            <button
              type="button"
              aria-label="Close data library"
              onClick={() => setOpen(false)}
            >
              ×
            </button>
          </header>
          <div
            className="data-library-tabs"
            role="tablist"
            aria-label="Data library sections"
          >
            {tabs.map((item, index) => (
              <button
                key={item}
                ref={(node) => {
                  tabRefs.current[index] = node;
                }}
                type="button"
                role="tab"
                id={`data-library-${index}-tab`}
                aria-controls={`data-library-${index}`}
                aria-selected={tab === item}
                tabIndex={tab === item ? 0 : -1}
                onClick={() => setTab(item)}
                onKeyDown={(event) => {
                  if (
                    !["ArrowLeft", "ArrowRight", "Home", "End"].includes(
                      event.key,
                    )
                  )
                    return;
                  event.preventDefault();
                  const next =
                    event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? tabs.length - 1
                        : (index +
                            (event.key === "ArrowRight"
                              ? 1
                              : tabs.length - 1)) %
                          tabs.length;
                  setTab(tabs[next]!);
                  tabRefs.current[next]?.focus();
                }}
              >
                {item}
              </button>
            ))}
          </div>
          <div className="data-library-content">
            {error ? (
              <p role="alert" className="data-error">
                {error}
              </p>
            ) : null}
            <section
              role="tabpanel"
              id="data-library-0"
              aria-labelledby="data-library-0-tab"
              hidden={tab !== "Datasets"}
            >
              <div className="data-library-intro">
                <p>
                  Choose related objects for your request. Each saved figure
                  keeps the exact inputs it used.
                </p>
                {!datasetsOnly ? (
                  <button type="button" onClick={() => onSelect([])}>
                    Let the assistant choose
                  </button>
                ) : null}
              </div>
              {catalog.isError ? (
                <p role="alert">
                  {catalog.error.message}{" "}
                  <button type="button" onClick={() => void catalog.refetch()}>
                    Retry
                  </button>
                </p>
              ) : catalog.isPending ? (
                <p>Loading datasets…</p>
              ) : !catalog.data.datasets.length ? (
                <div className="data-empty">
                  <strong>Your research starts here</strong>
                  <p>
                    Import an analysis or upload related files. Their objects
                    and relationships will be available to the assistant.
                  </p>
                  <button type="button" onClick={() => setTab("Upload")}>
                    Upload your data
                  </button>
                </div>
              ) : (
                catalog.data.datasets.map((dataset) => (
                  <DatasetCard
                    key={dataset.dataset_id}
                    dataset={dataset}
                    selected={selectedIds.includes(dataset.dataset_id)}
                    onToggle={() =>
                      onSelect(
                        selectedIds.includes(dataset.dataset_id)
                          ? selectedIds.filter(
                              (id) => id !== dataset.dataset_id,
                            )
                          : [...selectedIds, dataset.dataset_id],
                      )
                    }
                    onRefresh={refresh}
                  />
                ))
              )}
              <Pagination
                offset={offset}
                total={catalog.data?.total ?? 0}
                onChange={setOffset}
              />
            </section>
            <section
              role="tabpanel"
              id="data-library-1"
              aria-labelledby="data-library-1-tab"
              hidden={tab !== "Upload"}
            >
              <form
                className="data-upload-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  upload.mutate();
                }}
              >
                <label>
                  Dataset name
                  <input
                    required
                    maxLength={160}
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="e.g. Treatment study"
                  />
                </label>
                <label>
                  About these files
                  <textarea
                    value={description}
                    maxLength={4000}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="What do the measurements represent, and how are the files related?"
                  />
                </label>
                <label className="data-upload-target">
                  Data files
                  <input
                    ref={fileInput}
                    type="file"
                    multiple
                    onChange={(event) => {
                      const chosenFiles = Array.from(event.target.files ?? []);
                      setFiles(chosenFiles);
                      if (!name && chosenFiles[0])
                        setName(chosenFiles[0].name.replace(/\.[^.]+$/, ""));
                    }}
                  />
                  <span>
                    CSV, TSV, JSON and supported R objects · up to 32 MB per
                    file
                  </span>
                </label>
                {files.length ? (
                  <p>
                    {files.length} {files.length === 1 ? "file" : "files"} will
                    form one related collection.
                  </p>
                ) : null}
                <p className="data-help">
                  Files are inspected locally. The assistant uses their
                  structure and descriptions to understand the collection. Other
                  formats can be stored until a parser is available.
                </p>
                <button
                  className="data-primary"
                  type="submit"
                  disabled={upload.isPending || !files.length || !name.trim()}
                >
                  {upload.isPending ? "Uploading…" : "Upload & inspect"}
                </button>
              </form>
            </section>
            <section
              role="tabpanel"
              id="data-library-2"
              aria-labelledby="data-library-2-tab"
              hidden={tab !== "Analysis platform"}
            >
              <p className="data-help">
                Import a collection with its existing object descriptions and
                relationships.
              </p>
              {platform.isPending ? (
                <p>Checking connection…</p>
              ) : platform.isError ? (
                <p role="alert">
                  {platform.error.message}{" "}
                  <button type="button" onClick={() => void platform.refetch()}>
                    Retry
                  </button>
                </p>
              ) : !platform.data.connected &&
                !(platform.data.datasets ?? []).length ? (
                <div className="data-empty">
                  <strong>Analysis platform not connected</strong>
                  <p>{platform.data.message}</p>
                  <button type="button" onClick={() => setTab("Upload")}>
                    Upload files instead
                  </button>
                </div>
              ) : (
                <>
                  {platform.data.message ? (
                    <p className="data-help">{platform.data.message}</p>
                  ) : null}
                  {(platform.data.datasets ?? []).map((item) => (
                    <article
                      className="dataset-card"
                      key={item.source_id}
                      aria-label={item.name}
                    >
                      {item.contains_demo_data ? (
                        <span className="data-demo-badge">Demo collection</span>
                      ) : null}
                      <strong>{item.name}</strong>
                      <p>{item.description}</p>
                      <small>
                        {item.object_count} objects · {item.revision}
                      </small>
                      <button
                        type="button"
                        disabled={importDataset.isPending}
                        onClick={() => importDataset.mutate(item)}
                      >
                        {item.contains_demo_data
                          ? "Use demo collection"
                          : "Import collection"}
                      </button>
                    </article>
                  ))}
                  {platform.data.next_cursor ? (
                    <button
                      type="button"
                      onClick={() =>
                        setPlatformCursor(platform.data.next_cursor!)
                      }
                    >
                      Next collections
                    </button>
                  ) : null}
                </>
              )}
            </section>
            <section
              role="tabpanel"
              id="data-library-3"
              aria-labelledby="data-library-3-tab"
              hidden={tab !== "Results"}
            >
              <p className="data-help">
                Reusable tables, statistics, and models produced from your
                datasets.
              </p>
              {results.isError ? (
                <p role="alert">{results.error.message}</p>
              ) : results.isPending ? (
                <p>Loading saved results…</p>
              ) : results.data.results.length ? (
                results.data.results.map((result) => (
                  <AnalysisResultCard
                    key={result.result_id}
                    result={result}
                    disabled={disabled}
                    onUse={(chosenResult) => {
                      onUseResult(chosenResult);
                      setOpen(false);
                    }}
                  />
                ))
              ) : (
                <div className="data-empty">
                  <strong>No saved analyses yet</strong>
                  <p>
                    Ask the assistant to analyze your data. Its saved outputs
                    will appear here.
                  </p>
                </div>
              )}
              <Pagination
                offset={resultOffset}
                total={results.data?.total ?? 0}
                onChange={setResultOffset}
              />
            </section>
          </div>
          <footer>
            <span>
              {resultIds.length
                ? "Saved analysis selected"
                : selectedIds.length
                  ? `${selectedIds.length} selected`
                  : "Assistant selects from available data"}
            </span>
            <button
              type="button"
              className="data-primary"
              onClick={() => setOpen(false)}
            >
              Done
            </button>
          </footer>
        </dialog>,
        document.body,
      )}
    </>
  );
}

function Pagination({
  offset,
  total,
  onChange,
}: {
  offset: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  return total > 30 ? (
    <div className="data-pagination">
      <button
        type="button"
        disabled={!offset}
        onClick={() => onChange(Math.max(0, offset - 30))}
      >
        Previous
      </button>
      <span>
        {offset + 1}–{Math.min(total, offset + 30)} of {total}
      </span>
      <button
        type="button"
        disabled={offset + 30 >= total}
        onClick={() => onChange(offset + 30)}
      >
        Next
      </button>
    </div>
  ) : null;
}
