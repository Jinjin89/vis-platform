from fastapi import APIRouter
from fastapi.responses import FileResponse

from vis_platform_backend.api.dependencies import FigureExporterDependency
from vis_platform_backend.api.errors import NOT_FOUND_RESPONSE, VALIDATION_RESPONSE
from vis_platform_backend.contracts.figures import FigureExportFormat

router = APIRouter(tags=["figure exports"])


@router.get(
    "/projects/{project_id}/plots/{plot_id}/versions/{version_id}/exports/{format}",
    response_class=FileResponse,
    responses={
        **NOT_FOUND_RESPONSE,
        **VALIDATION_RESPONSE,
        200: {
            "description": (
                "The saved figure at its recorded size. PNG uses 300 dpi; "
                "PDF and SVG retain vectors."
            ),
            "content": {
                media: {"schema": {"type": "string", "format": "binary"}}
                for media in ("image/png", "application/pdf", "image/svg+xml")
            },
        },
    },
)
def export_figure(
    project_id: str,
    plot_id: str,
    version_id: str,
    format: FigureExportFormat,
    exporter: FigureExporterDependency,
) -> FileResponse:
    download = exporter.export(project_id, plot_id, version_id, format)
    return FileResponse(
        download.path,
        media_type=download.media_type,
        filename=download.filename,
        content_disposition_type="attachment",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=31536000, immutable",
        },
    )
