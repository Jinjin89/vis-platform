import type {
  ControlDefinition,
  ParameterValues,
} from "../../api/schemas/plotRun";

type ParameterFieldProps = {
  control: ControlDefinition;
  fieldId: string;
  value: ParameterValues[string];
  onChange: (controlId: string, value: ParameterValues[string]) => void;
};

export function ParameterField({
  control,
  fieldId,
  value,
  onChange,
}: ParameterFieldProps) {
  const requiresPlan =
    control.update_strategy != null && control.update_strategy !== "rerun";
  const descriptionId = control.description
    ? `${fieldId}-description`
    : undefined;
  const planId = requiresPlan ? `${fieldId}-plan` : undefined;
  const describedBy =
    [descriptionId, planId].filter(Boolean).join(" ") || undefined;

  return (
    <div
      className={`parameter-field parameter-field-${control.type}`}
      data-changed={value !== control.value}
    >
      {control.type === "boolean" ? (
        <label className="parameter-checkbox" htmlFor={fieldId}>
          <input
            id={fieldId}
            type="checkbox"
            checked={Boolean(value)}
            disabled={requiresPlan}
            aria-describedby={describedBy}
            onChange={(event) => onChange(control.id, event.target.checked)}
          />
          <span>{control.label}</span>
        </label>
      ) : (
        <>
          <label className="parameter-label" htmlFor={fieldId}>
            <span>{control.label}</span>
            {control.type === "number" && control.input_mode !== "number" ? (
              <output htmlFor={fieldId}>
                {String(value)}
                {control.unit ? ` ${control.unit}` : ""}
              </output>
            ) : null}
          </label>
          {control.type === "number" && control.input_mode === "number" ? (
            <div className="parameter-number-input">
              <input
                id={fieldId}
                type="number"
                min={control.minimum}
                max={control.maximum}
                step={control.step}
                value={typeof value === "number" ? value : ""}
                disabled={requiresPlan}
                aria-describedby={describedBy}
                onChange={(event) =>
                  onChange(
                    control.id,
                    event.target.value === "" ? "" : Number(event.target.value),
                  )
                }
              />
              {control.unit ? <span>{control.unit}</span> : null}
            </div>
          ) : control.type === "number" ? (
            <input
              id={fieldId}
              type="range"
              min={control.minimum}
              max={control.maximum}
              step={control.step}
              value={Number(value)}
              disabled={requiresPlan}
              aria-describedby={describedBy}
              onChange={(event) =>
                onChange(control.id, Number(event.target.value))
              }
            />
          ) : control.type === "choice" ? (
            <select
              id={fieldId}
              value={String(value)}
              disabled={requiresPlan}
              aria-describedby={describedBy}
              onChange={(event) => onChange(control.id, event.target.value)}
            >
              {control.options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          ) : (
            <input
              id={fieldId}
              type="text"
              value={String(value)}
              minLength={control.min_length ?? 0}
              maxLength={control.max_length ?? 200}
              required={(control.min_length ?? 0) > 0}
              disabled={requiresPlan}
              aria-describedby={describedBy}
              onChange={(event) => onChange(control.id, event.target.value)}
            />
          )}
        </>
      )}
      {control.description ? (
        <small id={descriptionId}>{control.description}</small>
      ) : null}
      {requiresPlan ? (
        <small id={planId}>Requires a plot plan or scientific decision.</small>
      ) : null}
    </div>
  );
}
