from pydantic import Field

from .common import StrictModel


class SharedFigureSelection(StrictModel):
    version_id: str = Field(min_length=1, max_length=160)
    expected_version_id: str | None = None
