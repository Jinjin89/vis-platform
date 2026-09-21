from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import StrictModel
from .report_content import Identifier, ReportBlock, ReportDataset, ReportSection
from .slide_layout import PresentationSettings, SlideSettings


class Placement(StrictModel):
    before_id: Identifier | None = None
    after_id: Identifier | None = None

    @model_validator(mode="after")
    def one_anchor(self) -> Placement:
        if self.before_id and self.after_id:
            raise ValueError("Choose one insertion anchor.")
        return self


class RenameReport(StrictModel):
    op: Literal["rename_report"]
    title: str = Field(min_length=1, max_length=200)


class SetReportDatasets(StrictModel):
    op: Literal["set_datasets"]
    datasets: list[ReportDataset] = Field(max_length=50)


class InsertSection(Placement):
    op: Literal["insert_section"]
    section: ReportSection


class RenameSection(StrictModel):
    op: Literal["rename_section"]
    section_id: Identifier
    title: str = Field(min_length=1, max_length=200)


class MoveSection(Placement):
    op: Literal["move_section"]
    section_id: Identifier
    parent_id: Identifier | None = None


class RemoveSection(StrictModel):
    op: Literal["remove_section"]
    section_id: Identifier


class InsertBlock(Placement):
    op: Literal["insert_block"]
    section_id: Identifier
    block: ReportBlock


class ReplaceBlock(StrictModel):
    op: Literal["replace_block"]
    section_id: Identifier
    block: ReportBlock


class MoveBlock(Placement):
    op: Literal["move_block"]
    block_id: Identifier
    section_id: Identifier


class RemoveBlock(StrictModel):
    op: Literal["remove_block"]
    block_id: Identifier


class SetSlideSettings(StrictModel):
    op: Literal["set_slide_settings"]
    section_id: Identifier
    settings: SlideSettings


class SetPresentationSettings(StrictModel):
    op: Literal["set_presentation_settings"]
    settings: PresentationSettings


ReportOperation = Annotated[
    SetSlideSettings
    | SetPresentationSettings
    | RenameReport
    | SetReportDatasets
    | InsertSection
    | RenameSection
    | MoveSection
    | RemoveSection
    | InsertBlock
    | ReplaceBlock
    | MoveBlock
    | RemoveBlock,
    Field(discriminator="op"),
]


class ReportOperationsRequest(StrictModel):
    request_id: Identifier
    base_revision: int = Field(ge=1)
    operations: list[ReportOperation] = Field(min_length=1, max_length=30)
    summary: str = Field(default="Edited report structure", min_length=1, max_length=200)
