import asyncio
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import FileResponse

from vis_platform_backend.contracts.common import ApiErrorEnvelope
from vis_platform_backend.contracts.reference_images import ReferenceImage
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.services.reference_images import UPLOAD_LIMIT, ReferenceImageService

router = APIRouter(prefix="/projects/{project_id}/plot-reference-images", tags=["plot references"])


def get_service(request: Request) -> ReferenceImageService:
    return cast(ReferenceImageService, request.app.state.reference_images)


Images = Annotated[ReferenceImageService, Depends(get_service)]


@router.post(
    "",
    response_model=ReferenceImage,
    status_code=201,
    responses={code: {"model": ApiErrorEnvelope} for code in (404, 409, 413, 415, 422)},
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload_reference_image(
    project_id: str,
    request: Request,
    service: Images,
    name: str = Query(min_length=1, max_length=200),
    idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
) -> ReferenceImage:
    service.check_project(project_id)
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > UPLOAD_LIMIT:
            raise DataError("Reference images must be smaller than 10 MB.", "IMAGE_TOO_LARGE", 413)
        chunks.extend(chunk)
    async with request.app.state.reference_image_slots:
        image = await asyncio.to_thread(
            service.create, project_id, name, bytes(chunks), idempotency_key
        )
        await asyncio.to_thread(service.cleanup)
        return image


@router.get("/{image_id}", response_model=ReferenceImage)
def get_reference_image(project_id: str, image_id: str, service: Images) -> ReferenceImage:
    return service.get(project_id, image_id)


@router.get("/{image_id}/content", response_class=FileResponse)
def get_content(project_id: str, image_id: str, service: Images) -> FileResponse:
    return FileResponse(
        service.content_path(project_id, image_id),
        media_type="image/png",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=86400"},
    )


@router.get("/{image_id}/thumbnail", response_class=FileResponse)
def get_thumbnail(project_id: str, image_id: str, service: Images) -> FileResponse:
    return FileResponse(
        service.content_path(project_id, image_id, thumbnail=True),
        media_type="image/png",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=86400"},
    )


@router.delete("/{image_id}", status_code=204)
def delete_reference_image(project_id: str, image_id: str, service: Images) -> Response:
    service.delete(project_id, image_id)
    return Response(status_code=204)
