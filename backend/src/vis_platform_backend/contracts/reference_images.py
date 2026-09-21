from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import StrictModel


class ReferenceImageLinks(StrictModel):
    content: str
    thumbnail: str


class ReferenceImage(StrictModel):
    image_id: str
    project_id: str
    name: str
    media_type: Literal["image/png"] = "image/png"
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    byte_size: int = Field(gt=0)
    created_at: datetime
    links: ReferenceImageLinks
