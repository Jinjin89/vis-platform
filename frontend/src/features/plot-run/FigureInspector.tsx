import type { AnalysisResult } from "../../api/schemas/datasets";
import { AnalysisResultCard } from "../datasets/AnalysisResultCard";
import { useId, useRef, useState } from "react";
import type { ParameterValues, PlotResult } from "../../api/schemas/plotRun";
import { FigureExportMenu } from "./FigureExportMenu";
import { ParameterForm } from "./ParameterForm";
import "./figureInspector.css";

type FigureInspectorProps = {
  projectId: string;
  onUseResult?: (result: AnalysisResult) => void;
  result: PlotResult;
  disabled: boolean;
  onCollapseChange?: (collapsed: boolean) => void;
  onApply: (changes: ParameterValues, requestId: string) => Promise<boolean>;
  parameterDraft?: ParameterValues;
  onParameterDraftChange?: (changes: ParameterValues) => void;
  parameterApplyLabel?: string;
};
const tabs = ["Parameters", "Data", "Results"] as const;

export function FigureInspector({
  projectId,
  onUseResult,
  result,
  disabled,
  onApply,
  onCollapseChange,
  parameterDraft,
  onParameterDraftChange,
  parameterApplyLabel,
}: FigureInspectorProps) {
  const [tab, setTab] = useState<(typeof tabs)[number]>("Parameters");
  const [collapsed, setCollapsed] = useState(false);
  function changeCollapsed(value: boolean) {
    setCollapsed(value);
    onCollapseChange?.(value);
  }
  const id = useId();
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  return (
    <section
      className="figure-inspector"
      aria-label="Figure details"
      data-collapsed={collapsed}
    >
      <div className="inspector-top">
        <div
          className="inspector-tabs"
          role="tablist"
          aria-label="Figure details"
        >
          {tabs.map((name, index) => (
            <button
              key={name}
              ref={(node) => {
                tabRefs.current[index] = node;
              }}
              id={`${id}-${name}-tab`}
              type="button"
              role="tab"
              aria-selected={tab === name}
              aria-controls={`${id}-${name}`}
              tabIndex={tab === name ? 0 : -1}
              onClick={() => {
                setTab(name);
                changeCollapsed(false);
              }}
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
                          (event.key === "ArrowRight" ? 1 : tabs.length - 1)) %
                        tabs.length;
                setTab(tabs[next]!);
                changeCollapsed(false);
                tabRefs.current[next]?.focus();
              }}
            >
              {name}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="inspector-collapse"
          aria-label={
            collapsed ? "Expand figure controls" : "Collapse figure controls"
          }
          aria-expanded={!collapsed}
          onClick={() => changeCollapsed(!collapsed)}
        >
          {collapsed ? "⌃" : "⌄"}
        </button>
      </div>
      <div
        role="tabpanel"
        id={`${id}-Parameters`}
        aria-labelledby={`${id}-Parameters-tab`}
        hidden={collapsed || tab !== "Parameters"}
        className="inspector-content inspector-parameters"
      >
        <ParameterForm
          key={result.version_id}
          result={result}
          disabled={disabled}
          onApply={onApply}
          draft={parameterDraft}
          onDraftChange={onParameterDraftChange}
          applyLabel={parameterApplyLabel}
        />
      </div>
      <div
        role="tabpanel"
        id={`${id}-Data`}
        aria-labelledby={`${id}-Data-tab`}
        hidden={collapsed || tab !== "Data"}
        className="inspector-content"
      >
        <div className="inspector-heading">
          <strong>Data used by this figure</strong>
        </div>
        {result.contains_demo_data ? (
          <p className="data-demo-badge">
            Contains synthetic demonstration data
          </p>
        ) : null}
        <p className="inspector-description">
          {result.data_summary ??
            "Data provenance was not recorded for this version."}
        </p>
        {(result.data_used ?? []).map((object) => (
          <section key={object.object_id} className="inspector-data-object">
            <strong>{object.name}</strong>
            <p>{object.summary}</p>
            <dl className="inspector-metadata">
              <div>
                <dt>Source</dt>
                <dd>{object.source}</dd>
              </div>
              {Object.entries(object.variable_mappings ?? {}).map(
                ([role, variable]) => (
                  <div key={role}>
                    <dt>{role}</dt>
                    <dd>{variable}</dd>
                  </div>
                ),
              )}
            </dl>
          </section>
        ))}
      </div>
      <div
        role="tabpanel"
        id={`${id}-Results`}
        aria-labelledby={`${id}-Results-tab`}
        hidden={collapsed || tab !== "Results"}
        className="inspector-content"
      >
        <div className="inspector-heading">
          <strong>Saved result</strong>
        </div>
        <p className="inspector-description">
          {result.caption ?? result.preview.description}
        </p>
        {(result.analysis_results ?? []).map((analysis) => (
          <AnalysisResultCard
            key={analysis.result_id}
            result={analysis}
            onUse={onUseResult}
            disabled={disabled}
          />
        ))}
        <dl className="inspector-metadata">
          <div>
            <dt>Execution</dt>
            <dd>
              {result.execution_mode === "demo"
                ? "Demonstration · no research dataset"
                : "R execution"}
            </dd>
          </div>
          <div>
            <dt>Validation</dt>
            <dd>
              {result.validation.status === "demo_only"
                ? "Illustrative preview"
                : result.validation.status === "passed"
                  ? "Passed"
                  : "Passed with warnings"}
            </dd>
          </div>
          <div>
            <dt>Parameters</dt>
            <dd>{result.controls?.length ?? 0} recorded values</dd>
          </div>
          <div>
            <dt>Figure</dt>
            <dd>
              <FigureExportMenu
                projectId={projectId}
                result={result}
                label="Export figure"
              />
            </dd>
          </div>
        </dl>
        {(result.validation.warnings ?? []).length ? (
          <ul className="inspector-warnings">
            {result.validation.warnings!.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        ) : null}
      </div>
    </section>
  );
}
