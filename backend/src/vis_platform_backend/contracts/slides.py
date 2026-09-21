from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import Identifier, StrictModel
from .report_content import ReportBlock, ReportContent, ReportDataset, ReportSection
from .slide_layout import PresentationSettings, SlideSettings


class Slide(StrictModel):
    id: Identifier
    title: str = Field(min_length=1, max_length=200)
    elements: list[ReportBlock] = Field(default_factory=list, max_length=200)
    settings: SlideSettings = Field(default_factory=SlideSettings)


class SlideDeckContent(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    title: str = Field(min_length=1, max_length=200)
    datasets: list[ReportDataset] = Field(default_factory=list, max_length=50)
    presentation: PresentationSettings = Field(default_factory=PresentationSettings)
    slides: list[Slide] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_ids(self) -> SlideDeckContent:
        self.to_document()
        return self

    def to_document(self) -> ReportContent:
        return ReportContent(
            title=self.title,
            kind="slides",
            datasets=self.datasets,
            presentation=self.presentation,
            sections=[
                ReportSection(id=s.id, title=s.title, blocks=s.elements, slide=s.settings)
                for s in self.slides
            ],
        )

    @classmethod
    def from_document(cls, content: ReportContent) -> SlideDeckContent:
        return cls(
            title=content.title,
            datasets=content.datasets,
            presentation=content.presentation or PresentationSettings(),
            slides=[
                Slide(
                    id=s.id, title=s.title, elements=s.blocks, settings=s.slide or SlideSettings()
                )
                for s in content.sections
            ],
        )


class CreateSlideDeck(StrictModel):
    request_id: Identifier
    content: SlideDeckContent
