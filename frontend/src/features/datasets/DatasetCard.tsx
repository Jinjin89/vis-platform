import { useState } from "react";
import type { Dataset } from "../../api/schemas/datasets";
import { finalizeDataset, updateDatasetDescription } from "../../api/datasets";

export function DatasetCard({
  dataset,
  selected,
  onToggle,
  onRefresh,
}: {
  dataset: Dataset;
  selected: boolean;
  onToggle: () => void;
  onRefresh: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(dataset.name);
  const [description, setDescription] = useState(dataset.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const objects = dataset.objects ?? [];
  const ready =
    dataset.state === "ready" &&
    objects.some((object) => object.readiness === "ready");
  const state =
    dataset.state === "processing"
      ? "Inspecting…"
      : dataset.state === "ready"
        ? ready
          ? "Ready"
          : "Needs a parser"
        : dataset.state === "failed"
          ? "Import interrupted"
          : "Awaiting files";
  return (
    <article className="dataset-card" data-selected={selected}>
      <div className="dataset-card-heading">
        <label>
          <input
            type="checkbox"
            checked={selected}
            disabled={!ready}
            onChange={onToggle}
          />
          <strong>{dataset.name}</strong>
        </label>
        <span className="dataset-state" data-ready={ready}>
          {state}
        </span>
      </div>
      {dataset.contains_demo_data ? (
        <span className="data-demo-badge">Synthetic demonstration data</span>
      ) : null}
      <p>{dataset.description}</p>
      <small>
        {dataset.source_kind === "upload"
          ? "Uploaded collection"
          : "Analysis platform"}{" "}
        · {objects.length} objects
      </small>
      {(dataset.notices ?? []).map((notice) => (
        <p className="data-help" key={notice}>
          {notice}
        </p>
      ))}
      {error ? (
        <p role="alert" className="data-error">
          {error}
        </p>
      ) : null}
      {objects.length ? (
        <details>
          <summary>Objects & relationships</summary>
          {objects.map((object) => (
            <section key={object.object_id} className="dataset-object">
              <strong>{object.name}</strong>
              <small>
                {object.kind} ·{" "}
                {object.dimensions?.length
                  ? object.dimensions.join(" × ")
                  : object.readiness}
              </small>
              <p>{object.description}</p>
              {object.columns?.length ? (
                <div className="data-columns">
                  {object.columns.slice(0, 20).map((column) => (
                    <span key={column.name}>
                      {column.name}
                      <small>
                        {column.data_type}
                        {column.unit ? ` · ${column.unit}` : ""}
                      </small>
                    </span>
                  ))}
                  {object.columns.length > 20 ? (
                    <small>{object.columns.length - 20} more columns</small>
                  ) : null}
                </div>
              ) : null}
              {(object.limitations ?? []).map((limitation) => (
                <p className="data-help" key={limitation}>
                  {limitation}
                </p>
              ))}
            </section>
          ))}
          {(dataset.relationships ?? []).map((relationship) => (
            <p
              className="dataset-relationship"
              key={relationship.relationship_id}
            >
              {
                objects.find(
                  (object) => object.object_id === relationship.left_object_id,
                )?.name
              }{" "}
              →{" "}
              {
                objects.find(
                  (object) => object.object_id === relationship.right_object_id,
                )?.name
              }
              <br />
              <small>
                {relationship.description ||
                  `${relationship.left_key ?? ""} · ${relationship.right_key ?? ""}`}{" "}
                ·{" "}
                {relationship.validation === "verified"
                  ? "Checked against data"
                  : relationship.validation === "invalid"
                    ? "Needs a corrected mapping"
                    : "Declared relationship"}
              </small>
            </p>
          ))}
        </details>
      ) : null}
      {dataset.state === "ready" ? (
        <button type="button" onClick={() => setEditing(!editing)}>
          Edit description
        </button>
      ) : null}
      {dataset.state === "failed" ||
      (dataset.source_kind === "analysis_platform" &&
        dataset.state === "ready") ? (
        <button
          type="button"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              await finalizeDataset(
                dataset.project_id,
                dataset.dataset_id,
                dataset.state === "ready",
              );
              await onRefresh();
            } catch (reason) {
              setError(
                reason instanceof Error ? reason.message : "Import failed.",
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          {dataset.state === "ready" ? "Check for updates" : "Retry inspection"}
        </button>
      ) : null}
      {editing ? (
        <form
          className="data-description-form"
          onSubmit={async (event) => {
            event.preventDefault();
            event.stopPropagation();
            setBusy(true);
            setError(null);
            try {
              await updateDatasetDescription(
                dataset.project_id,
                dataset.dataset_id,
                dataset.revision_id!,
                name,
                description,
              );
              await onRefresh();
              setEditing(false);
            } catch (reason) {
              setError(
                reason instanceof Error
                  ? reason.message
                  : "The description could not be saved.",
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          <label>
            Name
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </label>
          <label>
            Description
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <button type="submit" disabled={busy}>
            Save description
          </button>
        </form>
      ) : null}
    </article>
  );
}
