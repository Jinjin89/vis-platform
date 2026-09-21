from enum import StrEnum
from typing import Literal

from pydantic import Field

from .common import StrictModel


class FigureSize(StrictModel):
    width: float = Field(ge=1, le=30, multiple_of=0.01, allow_inf_nan=False)
    height: float = Field(ge=1, le=30, multiple_of=0.01, allow_inf_nan=False)
    unit: Literal["in"] = "in"


class FigureExportFormat(StrEnum):
    PNG = "png"
    PDF = "pdf"
    SVG = "svg"
    TIFF = "tiff"
