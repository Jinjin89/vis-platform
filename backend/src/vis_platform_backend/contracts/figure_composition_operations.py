from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .common import Identifier, StrictModel
from .figure_composition_content import (
    MAX_PANELS,
    FigureLegend,
    FigurePage,
    FigurePanel,
    Millimetres,
    PanelLabelStyle,
)


class SetFigureTitle(StrictModel):
    op: Literal["set_title"]
    title: str = Field(min_length=1, max_length=200)


class SetFigurePage(StrictModel):
    op: Literal["set_page"]
    page: FigurePage


class SetLabelStyle(StrictModel):
    op: Literal["set_label_style"]
    labels: PanelLabelStyle


class AddPanel(StrictModel):
    op: Literal["add_panel"]
    panel: FigurePanel
    before_id: Identifier | None = Field(
        default=None, description="Draw below this panel. Omit to draw on top of all panels."
    )


class ReplacePanel(StrictModel):
    op: Literal["replace_panel"]
    panel: FigurePanel


class RemovePanel(StrictModel):
    op: Literal["remove_panel"]
    panel_id: Identifier


class PanelGeometry(StrictModel):
    x_mm: Millimetres
    y_mm: Millimetres
    scale: float = Field(ge=0.05, le=10, allow_inf_nan=False)


class SetPanelGeometry(StrictModel):
    op: Literal["set_panel_geometry"]
    panels: dict[Identifier, PanelGeometry] = Field(min_length=1, max_length=MAX_PANELS)


class SetLegend(StrictModel):
    op: Literal["set_legend"]
    legend: FigureLegend


FigureOperation = Annotated[
    SetFigureTitle
    | SetFigurePage
    | SetLabelStyle
    | AddPanel
    | ReplacePanel
    | RemovePanel
    | SetPanelGeometry
    | SetLegend,
    Field(discriminator="op"),
]


class FigureOperationsRequest(StrictModel):
    request_id: Identifier
    base_revision: int = Field(ge=1)
    operations: list[FigureOperation] = Field(min_length=1, max_length=50)
    summary: str = Field(default="Edited figure", min_length=1, max_length=200)
