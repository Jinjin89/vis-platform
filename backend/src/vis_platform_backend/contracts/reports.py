from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, Field, model_validator

from .assistant_turns import AssistantTurnAccepted, AssistantTurnSnapshot
from .common import Identifier, StrictModel
from .datasets import Dataset
from .parameters import ParameterValue
from .plot_runs import PlotResultSummary, PlotRunAccepted, PlotRunSnapshot
from .reference_images import ReferenceImage
from .report_messages import ReportMessage

__all__ = [
    "Identifier",
    "ReportContent",
    "ReportContentInput",
    "ReportDataset",
    "ReportSection",
    "ReportFigureBlock",
    "ReportTextBlock",
    "ReportTableBlock",
    "ReportBlock",
]

from .report_content import (
    ReportBlock,
    ReportContent,
    ReportContentInput,
    ReportDataset,
    ReportFigureBlock,
    ReportSection,
    ReportTableBlock,
    ReportTextBlock,
)


class CreateReportRequest(StrictModel):
    content: ReportContentInput
    request_id: Identifier


class SaveReportRequest(StrictModel):
    base_revision: int = Field(ge=1)
    content: ReportContentInput
    summary: str = Field(default="Edited report", min_length=1, max_length=200)


class ReportGenerateRequest(StrictModel):
    request_id: Identifier
    base_revision: int = Field(ge=1)
    section_id: Identifier = Field(validation_alias=AliasChoices("section_id", "topic_id"))
    block_id: str | None = None
    kind: Literal["figure", "text", "discussion"]
    insert_new: bool = False
    before_block_id: str | None = None
    after_block_id: str | None = None
    prompt: str = Field(default="", max_length=8000)
    output_block_id: Identifier | None = None
    parameter_changes: dict[str, ParameterValue] = Field(default_factory=dict, max_length=100)

    @model_validator(mode="after")
    def valid_instruction(self) -> ReportGenerateRequest:
        if (
            self.block_id
            and not self.insert_new
            and self.output_block_id not in (None, self.block_id)
        ):
            raise ValueError("A refinement preserves its existing block ID.")
        if self.before_block_id and self.after_block_id:
            raise ValueError("Choose one block insertion anchor.")
        if self.kind == "discussion" and (self.insert_new or self.parameter_changes):
            raise ValueError("Discussion does not change report content.")
        if not self.prompt.strip() and not self.parameter_changes:
            raise ValueError("Provide instructions or parameter changes.")
        if self.parameter_changes and (self.kind != "figure" or self.block_id is None):
            raise ValueError("Parameter changes require an existing figure.")
        return self


class ReportEdit(StrictModel):
    edit_id: str
    section_id: str = Field(validation_alias=AliasChoices("section_id", "topic_id"))
    block_id: str | None = None
    output_block_id: str
    kind: Literal["figure", "text", "discussion"]
    prompt: str
    status: Literal[
        "running", "awaiting_input", "awaiting_approval", "completed", "failed", "cancelled"
    ]
    error: str | None = None
    response_text: str | None = None
    dismissed: bool = False
    message_id: str | None = None
    created_at: datetime
    assistant: AssistantTurnAccepted | None = None
    assistant_state: AssistantTurnSnapshot | None = None
    run: PlotRunAccepted | None = None
    run_state: PlotRunSnapshot | None = None


class ReportSummary(StrictModel):
    report_id: str
    project_id: str
    title: str
    revision: int
    updated_at: datetime


class ReportDocument(ReportSummary):
    schema_version: Literal["1.0"] = "1.0"
    created_at: datetime
    content: ReportContent
    datasets: list[Dataset]
    figure_bindings: dict[str, str] = Field(default_factory=dict)
    figures: dict[str, PlotResultSummary]
    images: dict[str, ReferenceImage]
    edits: list[ReportEdit]
    messages: list[ReportMessage] = Field(default_factory=list)
    stale_text_ids: list[str] = Field(default_factory=list)


class ReportList(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    reports: list[ReportSummary]
    total: int
    offset: int


class ReportRevision(StrictModel):
    revision: int
    summary: str
    created_at: datetime


class ReportHistory(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    revisions: list[ReportRevision]
    total: int


class ReportFigureList(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    figures: list[PlotResultSummary]
    total: int
    offset: int
