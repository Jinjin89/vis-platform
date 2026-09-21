from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import StrictModel


class SlideFrame(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def within_slide(self) -> SlideFrame:
        if self.x + self.width > 1.001 or self.y + self.height > 1.001:
            raise ValueError("Slide elements must remain inside the slide.")
        return self


class SlideSettings(StrictModel):
    layout: Literal["title", "figure-summary", "two-column", "statement", "table"] = (
        "figure-summary"
    )
    notes: str = Field(default="", max_length=12000)
    frames: dict[str, SlideFrame] = Field(default_factory=dict, max_length=200)


class PresentationSettings(StrictModel):
    aspect_ratio: Literal["16:9"] = "16:9"
    theme: Literal["paper", "midnight"] = "paper"
