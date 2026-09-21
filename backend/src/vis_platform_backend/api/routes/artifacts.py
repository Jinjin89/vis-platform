from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from vis_platform_backend.api.dependencies import CoordinatorDependency
from vis_platform_backend.api.errors import NOT_FOUND_RESPONSE

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get(
    "/{artifact_id}",
    response_class=FileResponse,
    responses=NOT_FOUND_RESPONSE,
)
def get_artifact(
    artifact_id: str,
    coordinator: CoordinatorDependency,
) -> FileResponse:
    artifact = coordinator.get_artifact(artifact_id)
    return FileResponse(
        Path(artifact["storage_path"]),
        media_type=artifact["media_type"],
        filename=artifact["filename"],
        content_disposition_type="inline",
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )
