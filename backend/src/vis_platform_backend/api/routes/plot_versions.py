from typing import Annotated

from fastapi import APIRouter, Header, status

from vis_platform_backend.api.dependencies import CoordinatorDependency
from vis_platform_backend.api.errors import (
    CONFLICT_RESPONSE,
    NOT_FOUND_RESPONSE,
    VALIDATION_RESPONSE,
)
from vis_platform_backend.contracts.parameters import ParameterUpdateRequest, RestoreVersionRequest
from vis_platform_backend.contracts.plot_runs import PlotRunAccepted
from vis_platform_backend.contracts.plot_source import PlotSource
from vis_platform_backend.contracts.plot_versions import PlotVersionList

router = APIRouter(tags=["plot versions"])
IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", min_length=1, max_length=128)
]


@router.get("/projects/{project_id}/plots/{plot_id}/versions", responses=NOT_FOUND_RESPONSE)
async def list_plot_versions(
    project_id: str, plot_id: str, coordinator: CoordinatorDependency
) -> PlotVersionList:
    return coordinator.list_versions(project_id, plot_id)


@router.get(
    "/projects/{project_id}/plots/{plot_id}/versions/{version_id}/source",
    responses=NOT_FOUND_RESPONSE,
)
async def get_plot_source(
    project_id: str, plot_id: str, version_id: str, coordinator: CoordinatorDependency
) -> PlotSource:
    return coordinator.get_source(project_id, plot_id, version_id)


@router.post(
    "/plots/{plot_id}/parameters",
    status_code=status.HTTP_202_ACCEPTED,
    responses={**NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE, **VALIDATION_RESPONSE},
)
async def update_plot_parameters(
    plot_id: str,
    request: ParameterUpdateRequest,
    coordinator: CoordinatorDependency,
    idempotency_key: IdempotencyKey = None,
) -> PlotRunAccepted:
    return coordinator.update_parameters(plot_id, request, idempotency_key=idempotency_key)


@router.post(
    "/plots/{plot_id}/restore",
    status_code=status.HTTP_202_ACCEPTED,
    responses={**NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE, **VALIDATION_RESPONSE},
)
async def restore_plot_version(
    plot_id: str,
    request: RestoreVersionRequest,
    coordinator: CoordinatorDependency,
    idempotency_key: IdempotencyKey = None,
) -> PlotRunAccepted:
    return coordinator.restore_version(plot_id, request, idempotency_key=idempotency_key)
