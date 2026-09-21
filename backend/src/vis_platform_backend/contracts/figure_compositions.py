from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import Identifier, StrictModel
from .datasets import Dataset
from .figure_composition_content import FigureCompositionContent
from .figure_messages import FigureMessage
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


class FigureCheck(StrictModel):
    code: Literal[
        "outside_margin",
        "overlap",
        "small_text",
        "low_resolution",
        "label_order",
        "unused_space",
        "empty_slot",
    ]
    severity: Literal["warning", "info"]
    message: str
    panel_ids: list[str] = Field(default_factory=list)


class FigureRenderJob(StrictModel):
    job_id: str
    panel_id: str
    status: Literal["running", "completed", "failed", "discarded"]
    width_mm: float
    height_mm: float
    error: str | None = None
    created_at: datetime


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
    datasets: list[Dataset] = Field(
        default_factory=list, description="The figure's datasets, in content order."
    )
    updates: dict[str, str] = Field(
        default_factory=dict, description="Newer plot versions available, keyed by panel ID."
    )
    checks: list[FigureCheck] = Field(
        default_factory=list, description="Layout and print problems; none of them block saving."
    )
    jobs: list[FigureRenderJob] = Field(
        default_factory=list, description="Recent renders of plots at their panel sizes."
    )
    messages: list[FigureMessage] = Field(
        default_factory=list, description="The figure assistant conversation, oldest first."
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
