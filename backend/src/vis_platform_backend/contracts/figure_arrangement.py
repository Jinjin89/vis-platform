"""A composition plan: nested rows and columns that the layout solver turns into geometry."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .common import Identifier, StrictModel
from .figure_composition_content import MAX_PANELS


class ArrangedPanel(StrictModel):
    type: Literal["panel"] = "panel"
    panel_id: Identifier
    aspect: float | None = Field(
        default=None,
        gt=0.1,
        lt=10,
        allow_inf_nan=False,
        description=(
            "Preferred width / height when the plot is rendered at its panel size. "
            "Scaled content always keeps its natural proportions."
        ),
    )


class ArrangedGroup(StrictModel):
    type: Literal["row", "column"] = Field(
        description="A row shares one height across its children; a column shares one width."
    )
    children: list[ArrangementNode] = Field(min_length=1, max_length=MAX_PANELS)


ArrangementNode = Annotated[ArrangedPanel | ArrangedGroup, Field(discriminator="type")]
ArrangedGroup.model_rebuild()


class ArrangeRequest(StrictModel):
    request_id: Identifier
    base_revision: int = Field(ge=1)
    arrangement: ArrangementNode | None = Field(
        default=None,
        description=(
            "Omit to tidy the current rows: panels keep their reading-order rows and fill "
            "the printable width."
        ),
    )
    gutter_mm: float = Field(default=4, ge=0, le=30, allow_inf_nan=False)
    render: bool = Field(
        default=False,
        description="Render arranged plots at their assigned sizes, so text prints at true size.",
    )
    summary: str = Field(default="Arranged panels", min_length=1, max_length=200)


class PanelRenderSize(StrictModel):
    width_mm: float = Field(ge=25.4, le=762, allow_inf_nan=False)
    height_mm: float = Field(ge=25.4, le=762, allow_inf_nan=False)


class RenderRequest(StrictModel):
    request_id: Identifier
    panels: dict[Identifier, PanelRenderSize] = Field(min_length=1, max_length=MAX_PANELS)
