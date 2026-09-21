"""Versioned figure composition content; panels reference shared plot versions and images."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import Identifier, StrictModel

MAX_PANELS = 40

Millimetres = Annotated[float, Field(ge=0, le=1000, allow_inf_nan=False)]


class FigurePage(StrictModel):
    width_mm: float = Field(ge=20, le=500, allow_inf_nan=False)
    height_mm: float = Field(
        ge=20,
        le=1000,
        allow_inf_nan=False,
        description="The fixed page height, or the maximum height when height_mode is auto.",
    )
    height_mode: Literal["fixed", "auto"] = Field(
        default="auto",
        description="Auto ends the page one margin below the lowest panel.",
    )
    margin_mm: float = Field(default=5, ge=0, le=50, allow_inf_nan=False)

    @model_validator(mode="after")
    def room_inside_margins(self) -> FigurePage:
        if 2 * self.margin_mm >= min(self.width_mm, self.height_mm):
            raise ValueError("Page margins must leave room for panels.")
        return self


class PanelLabelStyle(StrictModel):
    case: Literal["upper", "lower"] = "upper"
    size_pt: float = Field(default=10, ge=5, le=24, allow_inf_nan=False)
    bold: bool = True
    font_family: str = Field(
        default="Arial", min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9 \-]*$"
    )


class PlotPanelContent(StrictModel):
    type: Literal["plot"] = "plot"
    version_id: Identifier
    source_version_id: Identifier | None = Field(
        default=None,
        description=(
            "The version this panel's rendering was sized from. Update checks compare against it."
        ),
    )
    ignored_version_id: Identifier | None = Field(
        default=None, description="A newer version of this plot that the user chose not to apply."
    )


class ImagePanelContent(StrictModel):
    type: Literal["image"] = "image"
    image_id: Identifier


class SlotPanelContent(StrictModel):
    """A planned panel: the size and description of a plot that does not exist yet."""

    type: Literal["slot"] = "slot"
    prompt: str = Field(
        default="",
        max_length=8000,
        description="What the plot should show; the request given to the plotting agent.",
    )
    width_mm: float = Field(ge=5, le=500, allow_inf_nan=False)
    height_mm: float = Field(ge=5, le=1000, allow_inf_nan=False)


PanelContent = Annotated[
    PlotPanelContent | ImagePanelContent | SlotPanelContent, Field(discriminator="type")
]


class FigurePanel(StrictModel):
    id: Identifier
    content: PanelContent
    x_mm: Millimetres
    y_mm: Millimetres
    scale: float = Field(
        default=1,
        ge=0.05,
        le=10,
        allow_inf_nan=False,
        description="Displayed size relative to the content's natural size; 1 keeps it unscaled.",
    )
    label: str | None = Field(
        default=None,
        min_length=1,
        max_length=8,
        pattern=r"^\S(.*\S)?$",
        description="A custom label. Null assigns the next letter in reading order.",
    )
    show_label: bool = True
    locked: bool = Field(default=False, description="Automatic arrangement keeps this panel fixed.")


class FigureLegend(StrictModel):
    title: str = Field(default="", max_length=1000)
    entries: dict[Identifier, Annotated[str, Field(max_length=4000)]] = Field(
        default_factory=dict, max_length=MAX_PANELS, description="Legend text keyed by panel ID."
    )


class FigureDataset(StrictModel):
    dataset_id: Identifier


class FigureCompositionContent(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    title: str = Field(min_length=1, max_length=200)
    page: FigurePage
    labels: PanelLabelStyle = Field(default_factory=PanelLabelStyle)
    panels: list[FigurePanel] = Field(
        default_factory=list,
        max_length=MAX_PANELS,
        description="Drawing order: later panels are drawn on top.",
    )
    legend: FigureLegend = Field(default_factory=FigureLegend)
    datasets: list[FigureDataset] = Field(
        default_factory=list,
        max_length=50,
        description="Plots created in this figure use these datasets; none means project data.",
    )
    min_font_pt: float = Field(
        default=5,
        ge=4,
        le=12,
        allow_inf_nan=False,
        description="Text smaller than this on the printed page is reported by the checks.",
    )

    @model_validator(mode="after")
    def consistent_references(self) -> FigureCompositionContent:
        ids = [panel.id for panel in self.panels]
        if len(ids) != len(set(ids)):
            raise ValueError("Panel IDs must be unique within a figure.")
        custom = [
            panel.label.casefold() for panel in self.panels if panel.label and panel.show_label
        ]
        if len(custom) != len(set(custom)):
            raise ValueError("Custom panel labels must be unique.")
        if not set(self.legend.entries).issubset(ids):
            raise ValueError("Legend entries must refer to panels in this figure.")
        datasets = [dataset.dataset_id for dataset in self.datasets]
        if len(datasets) != len(set(datasets)):
            raise ValueError("Each dataset can be added to a figure once.")
        return self
