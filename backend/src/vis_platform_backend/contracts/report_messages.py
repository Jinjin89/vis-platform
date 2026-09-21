from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import StrictModel
from .questions import ClarificationAnswer, ClarificationQuestion, PlannerQuestions
from .report_content import Identifier
from .report_operations import Placement, ReportOperation


class ReportSelection(StrictModel):
    section_id: Identifier | None = None
    block_id: Identifier | None = None


class ReportMessageRequest(StrictModel):
    request_id: Identifier
    message: str = Field(min_length=1, max_length=8000)
    selection: ReportSelection | None = None

    @model_validator(mode="after")
    def nonempty_message(self) -> ReportMessageRequest:
        if not self.message.strip():
            raise ValueError("Enter a report request.")
        return self


class DocumentStep(StrictModel):
    kind: Literal["document"]
    operations: list[ReportOperation] = Field(min_length=1, max_length=20)
    summary: str = Field(min_length=1, max_length=200)


class ContentStep(Placement):
    kind: Literal["write", "plot"]
    section_id: Identifier
    block_id: Identifier | None = None
    output_id: Identifier
    insert_new: bool = False
    instructions: str = Field(min_length=1, max_length=8000)

    @model_validator(mode="after")
    def preserve_target_identity(self) -> ContentStep:
        if self.block_id and not self.insert_new:
            if self.output_id != self.block_id:
                raise ValueError("Replacing content must preserve its block ID.")
            if self.before_id or self.after_id:
                raise ValueError("Use a move operation to reposition existing content.")
        return self


ReportPlanStep = Annotated[DocumentStep | ContentStep, Field(discriminator="kind")]


class ReportPlan(StrictModel):
    action: Literal["execute", "reply", "ask_user", "inspect"]
    message: str = Field(min_length=1, max_length=6000)
    steps: list[ReportPlanStep] = Field(default_factory=list, max_length=8)
    inspect_section_ids: list[Identifier] = Field(default_factory=list, max_length=5)
    questions: list[ClarificationQuestion] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def valid_action(self) -> ReportPlan:
        if self.action == "inspect" and (
            not self.inspect_section_ids or self.steps or self.questions
        ):
            raise ValueError("Inspection needs section IDs and cannot edit the report.")
        if self.action == "execute" and (not self.steps or self.questions):
            raise ValueError("Execution needs steps and no unanswered questions.")
        if self.action == "ask_user" and (not self.questions or self.steps):
            raise ValueError("Ask only the unresolved questions; do not edit before the answer.")
        if self.action == "reply" and (self.steps or self.questions):
            raise ValueError("A conversational reply must not contain editing steps.")
        return self


class ReportMessageAnswer(StrictModel):
    interaction_id: str
    answers: list[ClarificationAnswer] = Field(min_length=1, max_length=3)


class ReportMessage(StrictModel):
    message_id: str
    prompt: str
    selection: ReportSelection | None = None
    status: Literal[
        "running", "awaiting_input", "awaiting_approval", "completed", "failed", "cancelled"
    ]
    phase: Literal["planning", "applying", "generating", "finished"] = "planning"
    response_text: str | None = None
    error: str | None = None
    question: PlannerQuestions | None = None
    active_edit_id: str | None = None
    completed_actions: list[str] = Field(default_factory=list)
    created_at: datetime
