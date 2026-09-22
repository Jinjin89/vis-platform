from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from .activity import AgentActivity
from .common import SCHEMA_VERSION, StrictModel
from .intent import IntentDecision
from .parameters import ParameterValue
from .plot_runs import DataScope, PlotRequest, PlotRunAccepted
from .questions import PlannerQuestions
from .reference_images import ReferenceImage


class AssistantTurnOutcome(StrEnum):
    MESSAGE = "message"
    PLOT_RUN = "plot_run"
    QUESTION = "question"


class AssistantTurnRequest(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    project_id: str
    request: PlotRequest
    data_scope: DataScope
    result_ids: list[str] = Field(default_factory=list, max_length=20)
    base_version_id: str | None = None
    parameter_changes: dict[str, ParameterValue] = Field(default_factory=dict, max_length=100)
    session_id: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "The workspace conversation this turn belongs to. The assistant's conversation "
            "context is limited to earlier turns of the same conversation."
        ),
    )

    @model_validator(mode="after")
    def require_parameter_base(self) -> AssistantTurnRequest:
        if self.parameter_changes and self.base_version_id is None:
            raise ValueError("Parameter drafts require a base plot version.")
        return self


class AssistantTurnLinks(StrictModel):
    trace: str
    status: str | None = None
    events: str | None = None
    cancel: str | None = None


class AssistantTurnResponse(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    turn_id: str
    outcome: AssistantTurnOutcome
    intent: IntentDecision
    message: str | None = None
    plot_run: PlotRunAccepted | None = None
    links: AssistantTurnLinks
    created_at: datetime
    question: PlannerQuestions | None = None
    activity: list[AgentActivity] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_outcome(self) -> AssistantTurnResponse:
        if self.outcome is AssistantTurnOutcome.MESSAGE:
            if self.message is None or self.plot_run is not None:
                raise ValueError("message outcome requires only message")
        elif self.outcome is AssistantTurnOutcome.QUESTION:
            if self.question is None or self.plot_run is not None:
                raise ValueError("question outcome requires a pending question")
        elif self.plot_run is None or self.message is not None:
            raise ValueError("plot_run outcome requires only plot_run")
        return self


class AssistantTurnAccepted(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    turn_id: str
    status: Literal["running"] = "running"
    links: AssistantTurnLinks


class AssistantFailure(StrictModel):
    code: str
    message: str


class AssistantTurnSnapshot(StrictModel):
    reference_images: list[ReferenceImage] = Field(default_factory=list)
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    turn_id: str
    project_id: str
    request_text: str
    revision: int
    status: Literal["running", "awaiting_input", "completed", "failed", "cancelled"]
    activity: list[AgentActivity] = Field(default_factory=list)
    question: PlannerQuestions | None = None
    response: AssistantTurnResponse | None = None
    error: AssistantFailure | None = None
    run_status: str | None = None
