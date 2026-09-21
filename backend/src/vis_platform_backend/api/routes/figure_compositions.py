from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from vis_platform_backend.contracts.common import ApiErrorEnvelope
from vis_platform_backend.contracts.figure_arrangement import ArrangeRequest, RenderRequest
from vis_platform_backend.contracts.figure_composition_content import FigureCompositionContent
from vis_platform_backend.contracts.figure_composition_operations import FigureOperationsRequest
from vis_platform_backend.contracts.figure_compositions import (
    CreateFigureComposition,
    FigureCompositionDocument,
    FigureCompositionHistory,
    FigureCompositionList,
    SaveFigureComposition,
)
from vis_platform_backend.contracts.figures import FigureExportFormat
from vis_platform_backend.services.figure_arrangement import FigureArrangementService
from vis_platform_backend.services.figure_compositions import FigureCompositionService

router = APIRouter(
    prefix="/projects/{project_id}/figure-compositions",
    tags=["figure compositions"],
    responses={code: {"model": ApiErrorEnvelope} for code in (404, 409, 422)},
)


def get_service(request: Request) -> FigureCompositionService:
    return cast(FigureCompositionService, request.app.state.figure_compositions)


Compositions = Annotated[FigureCompositionService, Depends(get_service)]


def get_arrangement(request: Request) -> FigureArrangementService:
    return cast(FigureArrangementService, request.app.state.figure_arrangement)


Arrangement = Annotated[FigureArrangementService, Depends(get_arrangement)]


@router.get("")
def list_compositions(
    project_id: str, service: Compositions, offset: int = Query(default=0, ge=0)
) -> FigureCompositionList:
    return service.list_compositions(project_id, offset)


@router.post("", status_code=201)
def create_composition(
    project_id: str, request: CreateFigureComposition, service: Compositions
) -> FigureCompositionDocument:
    return service.create(project_id, request)


@router.get("/{composition_id}")
def get_composition(
    project_id: str, composition_id: str, service: Compositions
) -> FigureCompositionDocument:
    return service.get(project_id, composition_id)


@router.put("/{composition_id}")
def save_composition(
    project_id: str, composition_id: str, request: SaveFigureComposition, service: Compositions
) -> FigureCompositionDocument:
    return service.save(project_id, composition_id, request)


@router.post("/{composition_id}/operations")
def apply_composition_operations(
    project_id: str, composition_id: str, request: FigureOperationsRequest, service: Compositions
) -> FigureCompositionDocument:
    return service.operations(project_id, composition_id, request)


@router.post("/{composition_id}/arrange")
async def arrange_composition(
    project_id: str, composition_id: str, request: ArrangeRequest, service: Arrangement
) -> FigureCompositionDocument:
    return service.arrange(project_id, composition_id, request)


@router.post("/{composition_id}/renders", status_code=202)
async def render_composition_panels(
    project_id: str, composition_id: str, request: RenderRequest, service: Arrangement
) -> FigureCompositionDocument:
    return service.render(project_id, composition_id, request)


@router.get("/{composition_id}/history")
def composition_history(
    project_id: str,
    composition_id: str,
    service: Compositions,
    offset: int = Query(default=0, ge=0),
) -> FigureCompositionHistory:
    return service.history(project_id, composition_id, offset)


@router.get("/{composition_id}/revisions/{revision}")
def composition_revision(
    project_id: str, composition_id: str, revision: int, service: Compositions
) -> FigureCompositionContent:
    return service.revision(project_id, composition_id, revision)


@router.get("/{composition_id}/content")
def export_composition_content(
    project_id: str, composition_id: str, service: Compositions
) -> FigureCompositionContent:
    return service.content(project_id, composition_id)


@router.get(
    "/{composition_id}/exports/{format}",
    response_class=FileResponse,
    responses={
        200: {
            "description": (
                "The composed page at its physical size. PNG and TIFF use 300 dpi; "
                "PDF and SVG retain vectors."
            ),
            "content": {
                media: {"schema": {"type": "string", "format": "binary"}}
                for media in ("image/png", "application/pdf", "image/svg+xml", "image/tiff")
            },
        },
    },
)
def export_composition(
    project_id: str, composition_id: str, format: FigureExportFormat, service: Compositions
) -> FileResponse:
    download = service.export(project_id, composition_id, format)
    return FileResponse(
        download.path,
        media_type=download.media_type,
        filename=download.filename,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )
