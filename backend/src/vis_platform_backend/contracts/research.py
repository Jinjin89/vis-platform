from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue, model_validator

from .common import StrictModel
from .datasets import ObjectReference, ObjectRelationship
from .figures import FigureSize
from .parameters import ControlGroup, NumberControl
from .questions import ClarificationQuestion
from .render_controls import RenderControl


class ResearchInput(StrictModel):
    alias: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    reference: ObjectReference


class ResearchOutput(StrictModel):
    key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(max_length=2000)


class ResearchPlan(StrictModel):
    figure_size: FigureSize | None = Field(
        default=None,
        description=(
            "Explicit output width and height in inches, chosen for this figure's layout and "
            "the user's output requirements. Required when render_code is present; "
            "null for analysis without a figure. No default canvas size is assumed."
        ),
    )
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(max_length=4000)
    inputs: list[ResearchInput] = Field(default_factory=list, max_length=20)
    relationships: list[ObjectRelationship] = Field(default_factory=list, max_length=20)
    analysis_code: str | None = Field(default=None, max_length=40_000)
    analysis_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    outputs: list[ResearchOutput] = Field(default_factory=list, max_length=20)
    reuse_result_id: str | None = None
    render_code: str | None = Field(default=None, max_length=40_000)
    controls: list[RenderControl] = Field(default_factory=list, max_length=42)
    control_groups: list[ControlGroup] = Field(default_factory=list)
    random_seed: int = Field(default=1, ge=0, le=2_147_483_647)

    @model_validator(mode="after")
    def executable(self) -> ResearchPlan:
        if self.render_code is not None and self.figure_size is None:
            raise ValueError("Rendering requires explicit figure_size width and height in inches.")
        if self.reuse_result_id is None and (
            not self.inputs or not self.analysis_code or not self.outputs
        ):
            raise ValueError("New analysis requires inputs, code, and named outputs.")
        if self.reuse_result_id is not None and (self.analysis_code is not None or self.outputs):
            raise ValueError("Result reuse cannot also execute new analysis.")
        if len({item.alias for item in self.inputs}) != len(self.inputs):
            raise ValueError("Input aliases must be unique.")
        if len({item.key for item in self.outputs}) != len(self.outputs):
            raise ValueError("Output keys must be unique.")
        if len({item.id for item in self.controls}) != len(self.controls):
            raise ValueError("Control identifiers must be unique.")
        if self.controls and self.render_code is None:
            raise ValueError("Figure controls require rendering code.")
        return self


class ResearchDecision(StrictModel):
    action: Literal["execute", "ask_user"]
    summary: str
    plan: ResearchPlan | None = None
    questions: list[ClarificationQuestion] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_action(self) -> ResearchDecision:
        if self.action == "execute" and (self.plan is None or self.questions):
            raise ValueError("Execution requires a plan and no unresolved questions.")
        if self.action == "ask_user" and (not self.questions or self.plan is not None):
            raise ValueError("Clarification requires questions and no executable plan.")
        # Checked on new plans only: versions saved earlier stay readable and editable.
        for control in self.plan.controls if self.plan else []:
            if isinstance(control, NumberControl) and not control.on_scale(control.value):
                raise ValueError(
                    f"Control “{control.id}” starts at {control.value}, which it cannot "
                    f"select: its values are {control.minimum} plus whole steps of "
                    f"{control.step}. Choose an initial value, minimum and step that agree."
                )
        return self


class ObjectMeaning(StrictModel):
    object_id: str
    name: str
    description: str
    observation_unit: str | None = None


class DatasetInterpretation(StrictModel):
    description: str
    objects: list[ObjectMeaning] = Field(default_factory=list)
    relationships: list[ObjectRelationship] = Field(default_factory=list)


class DataAnswer(StrictModel):
    message: str = Field(min_length=1, max_length=6000)
    questions: list[ClarificationQuestion] = Field(default_factory=list, max_length=4)
