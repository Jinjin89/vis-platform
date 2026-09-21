from datetime import datetime
from typing import Literal

from .common import SCHEMA_VERSION, StrictModel
from .plot_runs import PlotResultSummary


class PlotVersion(StrictModel):
    version_id: str
    run_id: str
    parent_version_id: str | None
    created_at: datetime
    change_summary: str
    result: PlotResultSummary


class PlotVersionList(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    project_id: str
    plot_id: str
    current_version_id: str
    versions: list[PlotVersion]
