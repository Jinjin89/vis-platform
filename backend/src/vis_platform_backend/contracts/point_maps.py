from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import StrictModel

ALIAS = r"^[A-Za-z][A-Za-z0-9_]{0,63}$"


class PointMapImage(StrictModel):
    """An image under the points, such as a tissue section, placed in data units."""

    input: str = Field(pattern=ALIAS, description="Alias of an image object in the plan inputs.")
    units_per_pixel: float = Field(
        default=1,
        gt=0,
        description=(
            "Data units spanned by one pixel of the uploaded image. 1 when point coordinates "
            "are pixels of this image; for a downsampled image, the original pixels per image "
            "pixel (for Visium full-resolution coordinates and the high-resolution image, "
            "1 / tissue_hires_scalef)."
        ),
    )
    origin: tuple[float, float] = Field(
        default=(0, 0),
        description="Data coordinates of the image's top-left corner.",
    )


class PointMapPlan(StrictModel):
    """Many observations drawn at two coordinates: an embedding or a spatial map.

    Pixel (column, row) of the image covers data x = origin_x + column × units_per_pixel and
    y = origin_y + row × units_per_pixel; y_axis only chooses which way y increases on screen.
    """

    table: str = Field(pattern=ALIAS, description="Alias of the table input to draw.")
    x: str = Field(min_length=1, max_length=200, description="Numeric column for x.")
    y: str = Field(min_length=1, max_length=200, description="Numeric column for y.")
    color: str | None = Field(default=None, max_length=200, description="Column that colors.")
    color_type: Literal["auto", "categorical", "continuous"] = Field(
        default="auto",
        description="auto treats numeric columns with more than 30 distinct values as continuous.",
    )
    y_axis: Literal["up", "down"] = Field(
        default="up",
        description="down for image and pixel coordinates, where y increases downward.",
    )
    equal_aspect: bool = Field(
        default=True, description="One data unit has the same length on both axes."
    )
    x_title: str | None = Field(default=None, max_length=120)
    y_title: str | None = Field(default=None, max_length=120)
    color_title: str | None = Field(default=None, max_length=120)
    image: PointMapImage | None = None

    @model_validator(mode="after")
    def distinct(self) -> PointMapPlan:
        if self.image and self.image.input == self.table:
            raise ValueError("The image and the table must be different inputs.")
        return self


class PointAxis(StrictModel):
    field: str
    title: str
    domain: tuple[float, float]


class PointYAxis(PointAxis):
    direction: Literal["up", "down"]


class PointCategory(StrictModel):
    value: str
    color: str


class PointColorCategories(StrictModel):
    type: Literal["categorical"]
    field: str
    title: str
    categories: list[PointCategory]
    missing_color: str


class PointColorScale(StrictModel):
    type: Literal["continuous"]
    field: str
    title: str
    domain: tuple[float, float]
    stops: list[str] = Field(description="Evenly spaced colours from the low to the high end.")


class PointViewImage(StrictModel):
    extent: tuple[float, float, float, float] = Field(
        description="Left, right, and the y of the image's first and last rows, in data units."
    )
    visible: bool


class PointViewLinks(StrictModel):
    columns: str = Field(
        description=(
            "Little-endian float32 columns, one after another, `count` values each, in the "
            "order `columns` lists: x, y, and colour (category index, or value; NaN when "
            "missing). A point's index is its position in these columns."
        )
    )
    image: str | None = None


class PointView(StrictModel):
    """An interactive view of a point map version."""

    title: str
    count: int
    dropped: int = Field(description="Source rows without numeric positions, not drawn.")
    x: PointAxis
    y: PointYAxis
    equal_aspect: bool
    color: PointColorCategories | PointColorScale | None = Field(discriminator="type")
    columns: list[Literal["x", "y", "color"]]
    point_size: float = Field(description="Point diameter in printed points.")
    opacity: float
    image: PointViewImage | None
    links: PointViewLinks
