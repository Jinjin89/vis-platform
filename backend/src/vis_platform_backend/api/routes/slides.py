from fastapi import APIRouter, Query

from vis_platform_backend.contracts.reports import CreateReportRequest, ReportDocument, ReportList
from vis_platform_backend.contracts.slides import CreateSlideDeck, SlideDeckContent
from vis_platform_backend.data.errors import DataError

from .reports import Reports

router = APIRouter(prefix="/projects/{project_id}/slides", tags=["slides"])


@router.get("")
def list_decks(
    project_id: str, service: Reports, offset: int = Query(default=0, ge=0)
) -> ReportList:
    service.check_project(project_id)
    items, total = service.store.list_reports(project_id, offset, "slides")
    return ReportList.model_validate({"reports": items, "total": total, "offset": offset})


@router.post("", status_code=201)
def create_deck(project_id: str, request: CreateSlideDeck, service: Reports) -> ReportDocument:
    return service.create(
        project_id,
        CreateReportRequest(request_id=request.request_id, content=request.content.to_document()),
    )


@router.get("/{deck_id}/content")
def export_deck(
    project_id: str, deck_id: str, service: Reports, freeze: bool = True
) -> SlideDeckContent:
    document = service.get(project_id, deck_id)
    if document.content.kind != "slides":
        raise DataError("Slide deck was not found.", "NOT_FOUND", 404)
    content = document.content.model_copy(deep=True)
    if freeze:
        for section in content.sections:
            for block in section.blocks:
                if block.type == "figure" and block.version_id:
                    block.version_id = document.figure_bindings.get(block.id, block.version_id)
                    block.follow_plot_id = None
    return SlideDeckContent.from_document(content)
