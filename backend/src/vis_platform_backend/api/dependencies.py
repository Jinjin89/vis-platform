from typing import Annotated, cast

from fastapi import Depends, Request

from vis_platform_backend.config import Settings
from vis_platform_backend.services.assistant_turns import AssistantTurnService
from vis_platform_backend.services.figure_exports import FigureExporter
from vis_platform_backend.services.plot_runs import PlotRunCoordinator


def get_coordinator(request: Request) -> PlotRunCoordinator:
    return cast(PlotRunCoordinator, request.app.state.coordinator)


CoordinatorDependency = Annotated[PlotRunCoordinator, Depends(get_coordinator)]


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


SettingsDependency = Annotated[Settings, Depends(get_settings)]


def get_assistant_turn_service(request: Request) -> AssistantTurnService:
    return cast(AssistantTurnService, request.app.state.assistant_turn_service)


AssistantTurnServiceDependency = Annotated[
    AssistantTurnService,
    Depends(get_assistant_turn_service),
]


def get_figure_exporter(request: Request) -> FigureExporter:
    return cast(FigureExporter, request.app.state.figure_exporter)


FigureExporterDependency = Annotated[FigureExporter, Depends(get_figure_exporter)]
