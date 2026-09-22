from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator

from .common import SCHEMA_VERSION, StrictModel

ParameterValue = (
    StrictBool | StrictInt | Annotated[float, Field(strict=True, allow_inf_nan=False)] | StrictStr
)


class ControlGroup(StrictModel):
    id: str
    label: str
    description: str | None = None


class ControlVisibility(StrictModel):
    control_id: str
    equals: ParameterValue


class ControlBase(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=150)
    group: str = "essential"
    description: str | None = None
    visible_when: ControlVisibility | None = None
    update_strategy: Literal["rerun", "regenerate", "confirm"] = "rerun"


class NumberControl(ControlBase):
    type: Literal["number"] = "number"
    value: float = Field(allow_inf_nan=False)
    minimum: float = Field(allow_inf_nan=False)
    maximum: float = Field(allow_inf_nan=False)
    step: float = Field(gt=0, allow_inf_nan=False)
    unit: str | None = None
    input_mode: Literal["slider", "number"] | None = None

    @model_validator(mode="after")
    def validate_range(self) -> NumberControl:
        if not self.minimum <= self.value <= self.maximum:
            raise ValueError("control value must lie within its bounds")
        return self

    def on_scale(self, value: float) -> bool:
        """Whether the control can select this value: its minimum plus whole steps."""
        steps = (value - self.minimum) / self.step
        return math.isclose(steps, round(steps), abs_tol=1e-7)


class ChoiceOption(StrictModel):
    value: str
    label: str


class ChoiceControl(ControlBase):
    type: Literal["choice"] = "choice"
    value: str
    options: list[ChoiceOption] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_options(self) -> ChoiceControl:
        values = [option.value for option in self.options]
        if len(values) != len(set(values)) or self.value not in values:
            raise ValueError("choice options must be unique and include the current value")
        return self


class TextControl(ControlBase):
    type: Literal["text"] = "text"
    value: str
    min_length: int = Field(default=0, ge=0)
    max_length: int = Field(default=200, ge=1, le=2000)

    @model_validator(mode="after")
    def validate_length(self) -> TextControl:
        if not self.min_length <= len(self.value) <= self.max_length:
            raise ValueError("text control value must satisfy its length limits")
        return self


class BooleanControl(ControlBase):
    type: Literal["boolean"] = "boolean"
    value: bool


ControlDefinition = Annotated[
    NumberControl | ChoiceControl | TextControl | BooleanControl, Field(discriminator="type")
]


class ParameterUpdateRequest(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    project_id: str
    base_version_id: str
    changes: dict[str, ParameterValue] = Field(min_length=1, max_length=100)


class RestoreVersionRequest(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    project_id: str
    source_version_id: str
