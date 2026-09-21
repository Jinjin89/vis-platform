from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import SCHEMA_VERSION, StrictModel


class CreateProjectRequest(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    name: str = Field(default="Untitled project", min_length=1, max_length=120)


class Project(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    project_id: str
    name: str
    created_at: datetime
