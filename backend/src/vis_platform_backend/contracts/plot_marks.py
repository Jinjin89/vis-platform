from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import StrictModel

MAX_PLOT_MARKS = 9
# Fractions are measured on the displayed image; allow rounding at the far edges.
_EDGE = 1e-6


class ImageMark(StrictModel):
    """A place the user marked on a plot image, so a request can refer to it by number."""

    number: int = Field(ge=1, le=MAX_PLOT_MARKS)
    kind: Literal["point", "area"]
    x: float = Field(
        ge=0, le=1, description="The point, or the area's left edge, as a fraction of the width."
    )
    y: float = Field(
        ge=0,
        le=1,
        description="The point, or the area's top edge, as a fraction of the height from the top.",
    )
    width: float = Field(default=0, ge=0, le=1, description="An area's width; 0 for a point.")
    height: float = Field(default=0, ge=0, le=1, description="An area's height; 0 for a point.")

    @model_validator(mode="after")
    def shape(self) -> ImageMark:
        if self.kind == "point" and (self.width or self.height):
            raise ValueError("A point mark has no width or height.")
        if self.kind == "area":
            if not self.width or not self.height:
                raise ValueError("An area mark needs a width and a height.")
            if self.x + self.width > 1 + _EDGE or self.y + self.height > 1 + _EDGE:
                raise ValueError("Keep marked areas inside the plot image.")
        return self


class ElementMark(StrictModel):
    """A point the user clicked in a version's interactive point view."""

    number: int = Field(ge=1, le=MAX_PLOT_MARKS)
    kind: Literal["element"]
    index: int = Field(ge=0, description="The point's position in the point view's columns.")


class SelectionMark(StrictModel):
    """An area the user dragged in a version's interactive point view, in data units."""

    number: int = Field(ge=1, le=MAX_PLOT_MARKS)
    kind: Literal["selection"]
    x_from: float = Field(allow_inf_nan=False)
    x_to: float = Field(allow_inf_nan=False)
    y_from: float = Field(allow_inf_nan=False)
    y_to: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self) -> SelectionMark:
        if not (self.x_from < self.x_to and self.y_from < self.y_to):
            raise ValueError("A selection runs from its lower to its higher x and y.")
        return self


PlotMark = Annotated[ImageMark | ElementMark | SelectionMark, Field(discriminator="kind")]
