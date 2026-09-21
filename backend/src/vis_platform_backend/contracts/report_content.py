"""Versioned report content; figures reference shared plot versions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, model_validator

from .common import Identifier, StrictModel
from .parameters import ParameterValue
from .slide_layout import PresentationSettings, SlideSettings

MAX_SECTION_BLOCKS = 200


class ReportDataset(StrictModel):
    dataset_id: Identifier
    revision_id: str | None = None


class ReportTextBlock(StrictModel):
    id: Identifier
    type: Literal["text"] = "text"
    body: str = Field(default="", max_length=30_000)
    evidence_version_ids: list[str] = Field(default_factory=list, max_length=100)


class ReportFigureBlock(StrictModel):
    id: Identifier
    type: Literal["figure"] = "figure"
    version_id: str | None = None
    follow_plot_id: Identifier | None = None
    image_id: str | None = None
    caption: str = Field(
        default="",
        max_length=4000,
        description=(
            "Caption for a standalone image only. Plot captions come from the shared version."
        ),
    )

    @model_validator(mode="after")
    def validate_reference(self) -> ReportFigureBlock:
        if (self.version_id is None) == (self.image_id is None):
            raise ValueError("A figure needs one shared plot version or uploaded image.")
        if self.follow_plot_id and not self.version_id:
            raise ValueError("Only a shared plot can have a linked placement.")
        if self.version_id is not None and self.caption:
            raise ValueError(
                "A plot's description belongs to its shared plot version, not the report."
            )
        return self


class ReportTableBlock(StrictModel):
    id: Identifier
    type: Literal["table"] = "table"
    title: str = Field(default="", max_length=200)
    columns: list[str] = Field(min_length=1, max_length=30)
    rows: list[list[ParameterValue | None]] = Field(default_factory=list, max_length=200)
    source_description: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def rectangular(self) -> ReportTableBlock:
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Every table row must match its columns.")
        return self


ReportBlock = Annotated[
    ReportTextBlock | ReportFigureBlock | ReportTableBlock, Field(discriminator="type")
]


class ReportSection(StrictModel):
    id: Identifier
    title: str = Field(min_length=1, max_length=200)
    level: Literal[1, 2] = 1
    parent_id: Identifier | None = None
    slide: SlideSettings | None = None
    blocks: list[ReportBlock] = Field(default_factory=list, max_length=MAX_SECTION_BLOCKS)


class ReportContent(StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    kind: Literal["report", "slides"] = "report"
    presentation: PresentationSettings | None = None
    title: str = Field(min_length=1, max_length=200)
    datasets: list[ReportDataset] = Field(default_factory=list, max_length=50)
    sections: list[ReportSection] = Field(
        default_factory=list,
        max_length=100,
        description=(
            "Document order: a level-1 section is followed by its ordered level-2 subsections."
        ),
    )

    @model_validator(mode="after")
    def validate_structure(self) -> ReportContent:
        if self.kind == "slides" and any(s.level != 1 or s.parent_id for s in self.sections):
            raise ValueError("Slides form a flat ordered sequence.")
        if self.kind == "report" and (self.presentation or any(s.slide for s in self.sections)):
            raise ValueError("Presentation settings belong to slide documents.")
        ids = [section.id for section in self.sections]
        ids.extend(block.id for section in self.sections for block in section.blocks)
        if len(ids) != len(set(ids)):
            raise ValueError("Section and block IDs must be unique within a report.")
        current_parent = None
        for section in self.sections:
            if section.level == 1:
                if section.parent_id is not None:
                    raise ValueError("First-level sections cannot have a parent.")
                current_parent = section.id
            elif section.parent_id is None or section.parent_id != current_parent:
                raise ValueError("A subsection must follow and reference its first-level parent.")
        if len({ref.dataset_id for ref in self.datasets}) != len(self.datasets):
            raise ValueError("Dataset references must be unique.")
        return self


class LegacyFigureBlock(StrictModel):
    id: Identifier
    type: Literal["figure"] = "figure"
    version_id: str | None = None
    image_id: str | None = None
    caption: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def one_source(self) -> LegacyFigureBlock:
        if (self.version_id is None) == (self.image_id is None):
            raise ValueError("A figure needs one saved plot version or imported image.")
        return self


class LegacyReportTopic(StrictModel):
    id: Identifier
    title: str = Field(min_length=1, max_length=200)
    blocks: list[
        Annotated[
            ReportTextBlock | LegacyFigureBlock | ReportTableBlock, Field(discriminator="type")
        ]
    ] = Field(default_factory=list, max_length=100)


class LegacyReportContent(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    title: str = Field(min_length=1, max_length=200)
    datasets: list[ReportDataset] = Field(default_factory=list, max_length=50)
    topics: list[LegacyReportTopic] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_ids(self) -> LegacyReportContent:
        ids = [topic.id for topic in self.topics]
        ids.extend(block.id for topic in self.topics for block in topic.blocks)
        if len(ids) != len(set(ids)):
            raise ValueError("Section and block IDs must be unique.")
        return self


ReportContentInput = ReportContent | LegacyReportContent


def upgrade_report(content: ReportContentInput, description: Callable[[str], str]) -> ReportContent:
    if isinstance(content, ReportContent):
        return content
    used = {item.id for item in content.topics}
    used.update(block.id for topic in content.topics for block in topic.blocks)
    sections = []
    for topic in content.topics:
        blocks: list[ReportBlock] = []
        for block in topic.blocks:
            if isinstance(block, LegacyFigureBlock):
                blocks.append(
                    ReportFigureBlock(
                        id=block.id,
                        version_id=block.version_id,
                        image_id=block.image_id,
                        caption=block.caption if block.image_id else "",
                    )
                )
                if (
                    block.version_id
                    and block.caption
                    and block.caption != description(block.version_id)
                ):
                    # Preserve an authored report caption as prose; never replace shared metadata.
                    note_id = "legacy_note_" + uuid5(NAMESPACE_URL, block.id).hex
                    while note_id in used:
                        note_id += "_"
                    used.add(note_id)
                    blocks.append(
                        ReportTextBlock(
                            id=note_id, body=block.caption, evidence_version_ids=[block.version_id]
                        )
                    )
            else:
                blocks.append(block)
        sections.append(ReportSection(id=topic.id, title=topic.title, blocks=blocks))
    return ReportContent(title=content.title, datasets=content.datasets, sections=sections)
