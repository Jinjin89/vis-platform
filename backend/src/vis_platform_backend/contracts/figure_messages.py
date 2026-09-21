"""The figure assistant: one message is planned into edits, plots, and arrangements."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .assistant_turns import AssistantTurnAccepted, AssistantTurnSnapshot
from .common import Identifier, StrictModel
from .figure_arrangement import ArrangementNode
from .figure_composition_content import MAX_PANELS
from .figure_composition_operations import FigureOperation
from .plot_runs import PlotRunAccepted, PlotRunSnapshot
from .questions import ClarificationAnswer, ClarificationQuestion, PlannerQuestions

MessageStatus = Literal[
    "running", "awaiting_input", "awaiting_approval", "completed", "failed", "cancelled"
]


class FigureSelection(StrictModel):
    panel_ids: list[Identifier] = Field(default_factory=list, max_length=MAX_PANELS)


class FigureMessageRequest(StrictModel):
    request_id: Identifier
    message: str = Field(min_length=1, max_length=8000)
    selection: FigureSelection | None = None

    @model_validator(mode="after")
    def nonempty_message(self) -> FigureMessageRequest:
        if not self.message.strip():
            raise ValueError("Enter a request for the figure.")
        return self


class FigureEditStep(StrictModel):
    kind: Literal["edit"]
    operations: list[FigureOperation] = Field(min_length=1, max_length=30)
    summary: str = Field(min_length=1, max_length=200)


class FigureAddStep(StrictModel):
    kind: Literal["add"]
    panel_id: Identifier = Field(description="A new, unique panel ID.")
    version_id: Identifier | None = Field(default=None, description="A saved plot version.")
    image_id: Identifier | None = Field(default=None, description="An uploaded image.")

    @model_validator(mode="after")
    def one_source(self) -> FigureAddStep:
        if (self.version_id is None) == (self.image_id is None):
            raise ValueError("Add one saved plot version or one image.")
        return self


class FigurePlotStep(StrictModel):
    kind: Literal["plot"]
    panel_id: Identifier = Field(
        description="An existing panel to refine, or a new panel ID for a new plot."
    )
    instructions: str = Field(min_length=1, max_length=8000)
    width_mm: float | None = Field(default=None, ge=25.4, le=500, allow_inf_nan=False)
    height_mm: float | None = Field(default=None, ge=25.4, le=500, allow_inf_nan=False)


class FigureArrangeStep(StrictModel):
    kind: Literal["arrange"]
    arrangement: ArrangementNode
    render: bool = Field(
        default=True, description="Render arranged plots at their sizes so text prints true."
    )
    gutter_mm: float = Field(default=4, ge=0, le=30, allow_inf_nan=False)
    summary: str = Field(min_length=1, max_length=200)


FigurePlanStep = Annotated[
    FigureEditStep | FigureAddStep | FigurePlotStep | FigureArrangeStep,
    Field(discriminator="kind"),
]


class FigurePlan(StrictModel):
    action: Literal["execute", "reply", "ask_user"]
    message: str = Field(min_length=1, max_length=6000)
    steps: list[FigurePlanStep] = Field(default_factory=list, max_length=12)
    questions: list[ClarificationQuestion] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def valid_action(self) -> FigurePlan:
        if self.action == "execute" and (not self.steps or self.questions):
            raise ValueError("Execution needs steps and no unanswered questions.")
        if self.action == "ask_user" and (not self.questions or self.steps):
            raise ValueError("Ask only the unresolved questions; do not edit before the answer.")
        if self.action == "reply" and (self.steps or self.questions):
            raise ValueError("A conversational reply must not contain editing steps.")
        return self


class FigureMessageAnswer(StrictModel):
    interaction_id: str
    answers: list[ClarificationAnswer] = Field(min_length=1, max_length=3)


class FigurePlotStatus(StrictModel):
    """The plot step in progress; questions and approvals come from the shared plot agent."""

    kind: Literal["figure"] = "figure"
    panel_id: str
    block_id: str | None = Field(default=None, description="The refined panel, if any.")
    prompt: str
    status: MessageStatus
    error: str | None = None
    assistant: AssistantTurnAccepted | None = None
    assistant_state: AssistantTurnSnapshot | None = None
    run: PlotRunAccepted | None = None
    run_state: PlotRunSnapshot | None = None


class FigureMessage(StrictModel):
    message_id: str
    prompt: str
    selection: FigureSelection | None = None
    status: MessageStatus
    phase: Literal["planning", "editing", "plotting", "arranging", "reviewing", "finished"] = (
        "planning"
    )
    response_text: str | None = None
    error: str | None = None
    question: PlannerQuestions | None = None
    active_step: FigurePlotStatus | None = None
    completed_actions: list[str] = Field(default_factory=list)
    created_at: datetime
