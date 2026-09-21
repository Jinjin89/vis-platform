from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import Identifier, StrictModel
from .figure_composition_content import FigureCompositionContent
from .plot_runs import PlotResultSummary
from .reference_images import ReferenceImage


class CreateFigureComposition(StrictModel):
    request_id: Identifier
    content: FigureCompositionContent


class SaveFigureComposition(StrictModel):
    base_revision: int = Field(ge=1)
    content: FigureCompositionContent
    summary: str = Field(default="Edited figure", min_length=1, max_length=200)


class PanelFrame(StrictModel):
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float


class ResolvedPanel(StrictModel):
    label: str | None = Field(description="The displayed label; null when the label is hidden.")
    frame: PanelFrame
    natural_width_mm: float
    natural_height_mm: float


class FigureCompositionSummary(StrictModel):
    composition_id: str
    project_id: str
    title: str
    revision: int
    updated_at: datetime


class FigureCompositionDocument(FigureCompositionSummary):
    schema_version: Literal["1.0"] = "1.0"
    created_at: datetime
    content: FigureCompositionContent
    page_height_mm: float = Field(description="The resolved page height.")
    panels: dict[str, ResolvedPanel] = Field(description="Resolved geometry keyed by panel ID.")
    figures: dict[str, PlotResultSummary] = Field(
        description="Plot versions used by panels or offered as updates, keyed by version ID."
    )
    images: dict[str, ReferenceImage]
    updates: dict[str, str] = Field(
        default_factory=dict, description="Newer plot versions available, keyed by panel ID."
    )


class FigureCompositionList(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    compositions: list[FigureCompositionSummary]
    total: int
    offset: int


class FigureCompositionRevision(StrictModel):
    revision: int
    summary: str
    created_at: datetime


class FigureCompositionHistory(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    revisions: list[FigureCompositionRevision]
    total: int
