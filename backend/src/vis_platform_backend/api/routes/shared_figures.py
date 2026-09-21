from fastapi import APIRouter

from vis_platform_backend.contracts.plot_runs import PlotResultSummary
from vis_platform_backend.contracts.shared_figures import SharedFigureSelection

from .reports import Reports

router = APIRouter(prefix="/projects/{project_id}/shared-figures", tags=["shared figures"])


@router.post("/{plot_id}")
def link_figure(
    project_id: str, plot_id: str, request: SharedFigureSelection, service: Reports
) -> PlotResultSummary:
    return service.link_figure(project_id, plot_id, request.version_id)


@router.put("/{plot_id}")
def publish_figure(
    project_id: str, plot_id: str, request: SharedFigureSelection, service: Reports
) -> PlotResultSummary:
    return service.link_figure(
        project_id, plot_id, request.version_id, request.expected_version_id, initialize=False
    )
