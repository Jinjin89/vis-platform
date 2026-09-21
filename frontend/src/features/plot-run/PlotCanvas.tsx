import type { AnalysisResult } from "../../api/schemas/datasets";
import { useEffect, useState } from "react";

import { resolveArtifactUrl } from "../../api/client";
import type {
  ArtifactReference,
  PlotRunSnapshot,
  ParameterValues,
} from "../../api/schemas/plotRun";
import { ResizablePanels } from "../../components/ResizablePanels";
import { FigureInspector } from "./FigureInspector";
import { FigureExportMenu } from "./FigureExportMenu";
import { FigureHistory } from "./FigureHistory";
import { FigureStage } from "./FigureStage";

type PlotCanvasProps = {
  onUseResult?: (result: AnalysisResult) => void;
  committedSnapshot: PlotRunSnapshot | null;
  provisionalPreview: ArtifactReference | null;
  currentBrief?: string;
  statusMessage: string;
  statusTone: "idle" | "working" | "attention" | "success" | "error";
  progressValue: number;
  isRunning: boolean;
  canCancel: boolean;
  isCancelling: boolean;
  onCancel: () => Promise<void>;
  onApplyParameters: (
    changes: ParameterValues,
    requestId: string,
  ) => Promise<boolean>;
  onSelectVersion: (runId: string) => Promise<void>;
  onRestoreVersion: (versionId: string, requestId: string) => Promise<boolean>;
};

export function PlotCanvas({
  onUseResult,
  committedSnapshot,
  provisionalPreview,
  currentBrief,
  statusMessage,
  statusTone,
  isRunning,
  canCancel,
  isCancelling,
  onCancel,
  onApplyParameters,
  onSelectVersion,
  onRestoreVersion,
}: PlotCanvasProps) {
  const result = committedSnapshot?.result;
  const preview = provisionalPreview ?? result?.preview;
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);
  const [retryNumber, setRetryNumber] = useState(0);

  useEffect(() => {
    setImageFailed(false);
    setRetryNumber(0);
  }, [preview?.artifact_id]);

  const previewUrl =
    preview == null
      ? null
      : `${resolveArtifactUrl(preview.href)}${retryNumber > 0 ? `?retry=${retryNumber}` : ""}`;
  return (
    <section
      className="plot-area"
      aria-label="Plot canvas"
      data-has-result={result != null}
    >
      <header className="plot-toolbar">
        <div className="plot-identity">
          <div className="plot-heading-meta">
            <span className="section-kicker">Figure workspace</span>
            <span
              className="run-status"
              data-tone={statusTone}
              aria-live="polite"
              title={statusMessage}
            >
              <span className="run-status-dot" aria-hidden="true" />
              <span className="run-status-text">{statusMessage}</span>
            </span>
          </div>
          <strong title={currentBrief}>
            {currentBrief == null ? "New figure" : shortenBrief(currentBrief)}
          </strong>
        </div>
        {canCancel ? (
          <button
            type="button"
            className="canvas-stop"
            disabled={isCancelling}
            onClick={() => void onCancel()}
          >
            {isCancelling ? "Stopping…" : "Stop"}
          </button>
        ) : null}
        {result != null && committedSnapshot != null ? (
          <FigureExportMenu
            projectId={committedSnapshot.project_id}
            result={result}
          />
        ) : null}
      </header>

      <ResizablePanels
        className="figure-panels"
        direction="vertical"
        label="Resize figure controls"
        storageKey="vis-platform.controls-height"
        firstMinimum={160}
        secondMinimum={160}
        fixedSize={result == null ? 25 : inspectorCollapsed ? 44 : undefined}
      >
        <div className="canvas-workbench" aria-busy={isRunning}>
          {result != null && committedSnapshot != null ? (
            <FigureHistory
              snapshot={committedSnapshot}
              disabled={isRunning || canCancel}
              onSelect={onSelectVersion}
              onRestore={onRestoreVersion}
            />
          ) : null}
          <div className="plot-canvas" data-empty={preview == null}>
            {preview == null ? (
              <EmptyFigure />
            ) : imageFailed ? (
              <div className="preview-error" role="alert">
                <span className="preview-error-mark" aria-hidden="true">
                  !
                </span>
                <strong>The preview could not be displayed</strong>
                <p>
                  The saved figure is still available. Try loading it again.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setImageFailed(false);
                    setRetryNumber((value) => value + 1);
                  }}
                >
                  Reload preview
                </button>
              </div>
            ) : (
              <FigureStage
                key={result?.plot_id ?? "preview"}
                src={previewUrl ?? ""}
                description={preview.description}
                size={result?.figure_size}
                containsDemoData={
                  result?.contains_demo_data === true ||
                  result?.execution_mode === "demo"
                }
                onError={() => setImageFailed(true)}
              />
            )}
          </div>
        </div>

        {result != null && committedSnapshot != null ? (
          <FigureInspector
            projectId={committedSnapshot.project_id}
            result={result}
            disabled={isRunning || canCancel}
            onApply={onApplyParameters}
            onCollapseChange={setInspectorCollapsed}
            onUseResult={onUseResult}
          />
        ) : (
          <div className="empty-footer">
            Your figure and its controls will appear here.
          </div>
        )}
      </ResizablePanels>
    </section>
  );
}

function EmptyFigure() {
  return (
    <div className="plot-empty">
      <div className="empty-chart" aria-hidden="true">
        <svg viewBox="0 0 560 260" fill="none">
          <path d="M62 34v175h454" className="chart-axis" />
          <path d="M62 68h454M62 112h454M62 156h454" className="chart-grid" />
          <path
            d="M78 181c35-4 48-62 83-59 38 4 49 47 84 36 42-12 50-103 99-98 35 4 44 68 79 63 32-5 45-50 82-58"
            className="chart-line chart-line-primary"
          />
          <path
            d="M78 194c38-3 53-24 87-23 41 1 52-38 89-31 42 8 53 36 93 22 37-13 45-56 80-55 28 0 47 21 78 12"
            className="chart-line chart-line-secondary"
          />
          <circle cx="161" cy="122" r="5" className="chart-point" />
          <circle cx="344" cy="60" r="5" className="chart-point" />
          <circle cx="423" cy="123" r="5" className="chart-point" />
        </svg>
        <span className="empty-data-label">
          Illustration · no research data
        </span>
      </div>
      <span className="empty-eyebrow">
        Scientific figures, thoughtfully made
      </span>
      <h1>Shape the figure your research question needs.</h1>
      <p>
        Describe your question in the conversation. You can discuss the analysis
        or try a clearly labeled illustrative figure.
      </p>
      <span className="empty-direction">Begin with the Studio assistant →</span>
    </div>
  );
}

function shortenBrief(value: string): string {
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length > 62 ? `${compact.slice(0, 59)}…` : compact;
}
