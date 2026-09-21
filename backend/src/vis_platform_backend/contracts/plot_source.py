from typing import Literal

from pydantic import Field

from .common import StrictModel
from .datasets import ObjectReference
from .parameters import ParameterValue


class PlotSource(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    plot_id: str
    version_id: str
    code: str | None = None
    render_code: str | None = None
    parameters: dict[str, ParameterValue] = Field(default_factory=dict)
    input_objects: list[ObjectReference] = Field(default_factory=list)
    result_bindings: dict[str, ObjectReference] = Field(default_factory=dict)
    message: str
