import { useId, useRef, useState } from "react";
import { createMutationId } from "../../api/client";
import { ParameterField } from "./ParameterField";
import type {
  ControlDefinition,
  ParameterValues,
  PlotResult,
} from "../../api/schemas/plotRun";

type ParameterFormProps = {
  result: PlotResult;
  disabled: boolean;
  onApply: (changes: ParameterValues, requestId: string) => Promise<boolean>;
  draft?: ParameterValues;
  onDraftChange?: (changes: ParameterValues) => void;
  applyLabel?: string;
};

export function ParameterForm({
  result,
  disabled,
  onApply,
  draft,
  onDraftChange,
  applyLabel,
}: ParameterFormProps) {
  const controls = result.controls ?? [];
  const [values, setValues] = useState<ParameterValues>(() => ({
    ...Object.fromEntries(
      controls.map((control) => [control.id, control.value]),
    ),
    ...draft,
  }));
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const inFlight = useRef(false);
  const request = useRef({ fingerprint: "", id: "" });
  const id = useId();
  const changed = controls.filter(
    (control) => values[control.id] !== control.value,
  );
  const available = result.parameter_updates_available === true;
  const sizeControls = ["figure_width", "figure_height"].flatMap((controlId) =>
    controls.filter(
      (control) => control.id === controlId && control.type === "number",
    ),
  );
  const plotControls = controls.filter(
    (control) => !sizeControls.includes(control),
  );
  const groupIds = Array.from(
    new Set(plotControls.map((control) => control.group ?? "essential")),
  );
  const groups = [
    ...(result.control_groups ?? []),
    ...groupIds
      .filter(
        (group) => !result.control_groups?.some((item) => item.id === group),
      )
      .map((group) => ({
        id: group,
        label: group === "essential" ? "Appearance" : group,
        description: null,
      })),
  ].filter((group) => groupIds.includes(group.id));
  // Count the schema, not visible fields, so editing never changes navigation.
  const useSections = plotControls.length > 24 && groups.length > 1;
  const [selectedGroup, setSelectedGroup] = useState(
    groups[0]?.id ?? "essential",
  );
  const groupTabs = useRef<Array<HTMLButtonElement | null>>([]);
  const visibleGroups = useSections
    ? groups.filter((group) => group.id === selectedGroup)
    : groups;

  function change(controlId: string, value: ParameterValues[string]) {
    const next = { ...values, [controlId]: value };
    setValues(next);
    onDraftChange?.(
      Object.fromEntries(
        controls
          .filter((control) => next[control.id] !== control.value)
          .map((control) => [control.id, next[control.id]]),
      ),
    );
    setError(null);
  }

  async function apply(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !available ||
      disabled ||
      inFlight.current ||
      !changed.length ||
      !controls.every((control) => validValue(control, values[control.id]))
    )
      return;
    const changes = Object.fromEntries(
      changed.map((control) => [control.id, values[control.id]]),
    );
    const fingerprint = JSON.stringify({ version: result.version_id, changes });
    if (request.current.fingerprint !== fingerprint)
      request.current = { fingerprint, id: createMutationId() };
    inFlight.current = true;
    setSubmitting(true);
    setError(null);
    try {
      await onApply(changes, request.current.id);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The parameter changes could not be applied.",
      );
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  }

  if (!controls.length)
    return (
      <p className="inspector-empty">
        This version has no adjustable parameters.
      </p>
    );
  return (
    <form
      className="parameter-form"
      onSubmit={(event) => void apply(event)}
      aria-label="Plot parameters"
      // Values are checked by validValue and the backend. The browser's own check would also
      // reject an unchanged saved value that is off its step, and block every submission.
      noValidate
    >
      {!available ? (
        <p className="inspector-empty">
          Adjustments are unavailable for this saved version. Its recorded
          values are shown below.
        </p>
      ) : null}
      <div className="parameter-layout">
        {sizeControls.length ? (
          <div className="parameter-size-rail">
            <fieldset
              className="parameter-group parameter-size"
              disabled={!available || disabled || submitting}
            >
              <legend>
                <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                  <rect x="3" y="5" width="14" height="10" rx="1.5" />
                  <path d="M3 2h14M1 5v10" />
                </svg>
                Figure size
              </legend>
              <div className="parameter-size-grid">
                {sizeControls.map((control) => (
                  <ParameterField
                    key={control.id}
                    control={control}
                    fieldId={`${id}-control-${control.id}`}
                    value={values[control.id]}
                    onChange={change}
                  />
                ))}
              </div>
            </fieldset>
          </div>
        ) : null}
        <div className="parameter-settings">
          {useSections ? (
            <div
              className="parameter-section-tabs"
              role="tablist"
              aria-label="Parameter sections"
            >
              {groups.map((group, index) => (
                <button
                  type="button"
                  role="tab"
                  key={group.id}
                  id={`${id}-section-${group.id}`}
                  ref={(node) => {
                    groupTabs.current[index] = node;
                  }}
                  aria-selected={selectedGroup === group.id}
                  aria-controls={`${id}-group-${group.id}`}
                  tabIndex={selectedGroup === group.id ? 0 : -1}
                  onClick={() => setSelectedGroup(group.id)}
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
                          ? groups.length - 1
                          : (index +
                              (event.key === "ArrowRight"
                                ? 1
                                : groups.length - 1)) %
                            groups.length;
                    setSelectedGroup(groups[next]!.id);
                    groupTabs.current[next]?.focus();
                  }}
                >
                  {group.label}
                </button>
              ))}
            </div>
          ) : null}
          <div className="parameter-fields-scroll">
            <div className="parameter-groups">
              {visibleGroups.map((group) => {
                const groupControls = plotControls.filter(
                  (control) => (control.group ?? "essential") === group.id,
                );
                const fields = groupControls.filter(
                  (control) =>
                    control.visible_when == null ||
                    values[control.visible_when.control_id] ===
                      control.visible_when.equals,
                );
                return fields.length ? (
                  <fieldset
                    id={`${id}-group-${group.id}`}
                    className="parameter-group"
                    data-toggles-only={groupControls.every(
                      (control) => control.type === "boolean",
                    )}
                    role={useSections ? "tabpanel" : undefined}
                    aria-labelledby={
                      useSections ? `${id}-section-${group.id}` : undefined
                    }
                    key={group.id}
                    disabled={!available || disabled || submitting}
                  >
                    <legend>{group.label}</legend>
                    {group.description ? (
                      <p className="parameter-group-description">
                        {group.description}
                      </p>
                    ) : null}
                    <div className="parameter-grid">
                      {fields.map((control) => (
                        <ParameterField
                          key={control.id}
                          control={control}
                          fieldId={`${id}-control-${control.id}`}
                          value={values[control.id]}
                          onChange={change}
                        />
                      ))}
                    </div>
                  </fieldset>
                ) : null;
              })}
            </div>
          </div>
        </div>
      </div>
      {error ? (
        <p className="inspector-error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="parameter-actions">
        <span
          className="parameter-save-status"
          data-dirty={changed.length > 0}
          aria-live="polite"
        >
          {changed.length
            ? `${changed.length} unsaved ${changed.length === 1 ? "change" : "changes"}`
            : "Saved"}
        </span>
        <div>
          <button
            type="button"
            disabled={disabled || submitting || !changed.length}
            onClick={() => {
              setValues(
                Object.fromEntries(
                  controls.map((control) => [control.id, control.value]),
                ),
              );
              onDraftChange?.({});
              setError(null);
            }}
          >
            Reset
          </button>
          <button
            type="submit"
            className="parameter-apply"
            aria-label={applyLabel ?? "Apply as new version"}
            disabled={
              !available ||
              disabled ||
              submitting ||
              !changed.length ||
              !controls.every((control) =>
                validValue(control, values[control.id]),
              )
            }
          >
            {submitting
              ? applyLabel
                ? "Creating…"
                : "Applying…"
              : (applyLabel ?? "Apply changes")}
          </button>
        </div>
      </div>
    </form>
  );
}

export function validValue(
  control: ControlDefinition,
  value: ParameterValues[string],
): boolean {
  // The saved value is never sent back; only changed values are checked, as on the backend.
  if (value === control.value) return true;
  if (control.type === "boolean") return typeof value === "boolean";
  if (control.type === "choice")
    return (
      typeof value === "string" &&
      control.options.some((option) => option.value === value)
    );
  if (control.type === "text")
    return (
      typeof value === "string" &&
      value.length >= (control.min_length ?? 0) &&
      value.length <= (control.max_length ?? 200) &&
      (!(control.min_length ?? 0) || Boolean(value.trim()))
    );
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value < control.minimum ||
    value > control.maximum
  )
    return false;
  const steps = (value - control.minimum) / control.step;
  return Math.abs(steps - Math.round(steps)) < 1e-7;
}
