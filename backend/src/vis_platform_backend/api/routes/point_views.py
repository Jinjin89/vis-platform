from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from vis_platform_backend.api.errors import NOT_FOUND_RESPONSE
from vis_platform_backend.contracts.point_maps import PointView
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.services.point_maps import POINT_COLUMNS, VIEW_IMAGE, PointMapService

router = APIRouter(tags=["point views"])
BASE = "/projects/{project_id}/plots/{plot_id}/versions/{version_id}/point-view"
# Versions never change, so their views can be kept by the browser.
IMMUTABLE = {"Cache-Control": "private, max-age=31536000, immutable"}


def get_point_maps(request: Request) -> PointMapService:
    return cast(PointMapService, request.app.state.point_maps)


PointMaps = Annotated[PointMapService, Depends(get_point_maps)]


def _directory(service: PointMapService, project_id: str, plot_id: str, version_id: str) -> Path:
    if service.repository.plot_id_for_version(version_id) != plot_id:
        raise DataError("This plot version was not found.", "NOT_FOUND", 404)
    return service.version_directory(project_id, version_id)


@router.get(BASE, responses=NOT_FOUND_RESPONSE)
def get_point_view(project_id: str, plot_id: str, version_id: str, service: PointMaps) -> PointView:
    _directory(service, project_id, plot_id, version_id)
    view = service.view(project_id, version_id)
    path = f"/api/v1{BASE}".format(project_id=project_id, plot_id=plot_id, version_id=version_id)
    return PointView.model_validate(
        {
            **view,
            "links": {
                "columns": path + "/columns",
                "image": path + "/image" if view["image"] else None,
            },
        }
    )


@router.get(
    BASE + "/columns",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}, **NOT_FOUND_RESPONSE},
)
def get_point_columns(
    project_id: str, plot_id: str, version_id: str, service: PointMaps
) -> FileResponse:
    directory = _directory(service, project_id, plot_id, version_id)
    return FileResponse(
        directory / POINT_COLUMNS, media_type="application/octet-stream", headers=IMMUTABLE
    )


@router.get(
    BASE + "/image",
    response_class=FileResponse,
    responses={200: {"content": {"image/png": {}}}, **NOT_FOUND_RESPONSE},
)
def get_point_image(
    project_id: str, plot_id: str, version_id: str, service: PointMaps
) -> FileResponse:
    directory = _directory(service, project_id, plot_id, version_id)
    if not (directory / VIEW_IMAGE).is_file():
        raise DataError("This point view has no image.", "NOT_FOUND", 404)
    return FileResponse(directory / VIEW_IMAGE, media_type="image/png", headers=IMMUTABLE)
