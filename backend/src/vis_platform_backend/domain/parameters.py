from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from vis_platform_backend.contracts.parameters import (
    BooleanControl,
    ChoiceControl,
    ControlDefinition,
    NumberControl,
    ParameterValue,
    TextControl,
)


class InvalidParameterError(ValueError):
    pass


def resolve_parameters(
    controls: Sequence[ControlDefinition],
    changes: Mapping[str, ParameterValue],
    *,
    require_change: bool = True,
) -> dict[str, ParameterValue]:
    """Validate values against the selected executable's contract, without coercing inputs."""
    definitions = {control.id: control for control in controls}
    values: dict[str, ParameterValue] = {control.id: control.value for control in controls}
    for key, value in changes.items():
        control = definitions.get(key)
        if control is None:
            raise InvalidParameterError(f"Unknown plot parameter: {key}.")
        if control.update_strategy != "rerun":
            raise InvalidParameterError(
                f"{control.label} requires a new plot plan or scientific approval."
            )
        if isinstance(control, BooleanControl):
            valid = isinstance(value, bool)
        elif isinstance(control, NumberControl):
            valid = (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and control.minimum <= value <= control.maximum
                and control.on_scale(value)
            )
        elif isinstance(control, ChoiceControl):
            valid = isinstance(value, str) and value in {option.value for option in control.options}
        elif isinstance(control, TextControl):
            valid = (
                isinstance(value, str)
                and control.min_length <= len(value) <= control.max_length
                and (control.min_length == 0 or bool(value.strip()))
            )
        else:
            valid = False
        if not valid:
            raise InvalidParameterError(
                f"The value for {control.label} does not match its allowed options or limits."
            )
        values[key] = value
    if require_change and all(values[control.id] == control.value for control in controls):
        raise InvalidParameterError("No parameter values have changed.")
    return values
