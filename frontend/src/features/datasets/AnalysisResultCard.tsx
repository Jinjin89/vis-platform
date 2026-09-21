import type { AnalysisResult } from "../../api/schemas/datasets";
import { resolveArtifactUrl } from "../../api/client";
import "./datasets.css";

export function AnalysisResultCard({
  result,
  onUse,
  disabled = false,
}: {
  result: AnalysisResult;
  onUse?: (result: AnalysisResult) => void;
  disabled?: boolean;
}) {
  const preferredDownloads = (result.artifacts ?? []).filter(
    (artifact) =>
      artifact.media_type === "text/csv" || artifact.role === "model",
  );
  const downloads = preferredDownloads.length
    ? preferredDownloads
    : (result.artifacts ?? []).filter((artifact) => artifact.role === "data");
  return (
    <article className="analysis-result-card" aria-label={result.name}>
      <span className="data-eyebrow">
        Saved analysis{result.contains_demo_data ? " · Demo data" : ""}
      </span>
      <strong>{result.name}</strong>
      <p>{result.description}</p>
      {result.objects
        .filter((object) => object.scalar != null)
        .map((object) => (
          <div className="analysis-statistic" key={object.object_id}>
            <span>{object.name}</span>
            <output>
              {typeof object.scalar === "number"
                ? new Intl.NumberFormat(undefined, {
                    maximumSignificantDigits: 6,
                  }).format(object.scalar)
                : String(object.scalar)}
            </output>
          </div>
        ))}
      <div className="analysis-result-actions">
        {onUse ? (
          <button
            type="button"
            disabled={disabled}
            onClick={() => onUse(result)}
          >
            Use in a figure
          </button>
        ) : null}
        {downloads.map((artifact, index) => (
          <a
            key={artifact.artifact_id}
            href={resolveArtifactUrl(artifact.href)}
            download
          >
            {artifact.media_type === "text/csv"
              ? `Download table${downloads.length > 1 ? ` ${index + 1}` : ""}`
              : artifact.role === "model"
                ? "Download model"
                : "Download result"}
          </a>
        ))}
      </div>
      <details>
        <summary>Objects and method</summary>
        {result.objects.map((object) => (
          <p key={object.object_id}>
            <strong>{object.name}</strong> · {object.kind}
            {object.dimensions?.length
              ? ` · ${object.dimensions.join(" × ")}`
              : ""}
            <br />
            {object.description}
          </p>
        ))}
        <small>
          {result.inputs.length} pinned input{" "}
          {result.inputs.length === 1 ? "object" : "objects"} ·{" "}
          {new Date(result.created_at).toLocaleDateString()}
        </small>
        {(result.artifacts ?? [])
          .filter((artifact) => artifact.role === "script")
          .map((artifact) => (
            <a
              key={artifact.artifact_id}
              href={resolveArtifactUrl(artifact.href)}
              download
            >
              Download analysis code
            </a>
          ))}
      </details>
    </article>
  );
}
