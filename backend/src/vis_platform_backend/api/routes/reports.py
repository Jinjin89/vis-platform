from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request

from vis_platform_backend.contracts.common import ApiErrorEnvelope
from vis_platform_backend.contracts.report_messages import ReportMessageAnswer, ReportMessageRequest
from vis_platform_backend.contracts.report_operations import ReportOperationsRequest
from vis_platform_backend.contracts.reports import (
    CreateReportRequest,
    ReportContent,
    ReportDocument,
    ReportFigureList,
    ReportGenerateRequest,
    ReportHistory,
    ReportList,
    SaveReportRequest,
)
from vis_platform_backend.services.report_messages import ReportMessageRuntime
from vis_platform_backend.services.reports import ReportService

router = APIRouter(
    prefix="/projects/{project_id}/reports",
    tags=["reports"],
    responses={code: {"model": ApiErrorEnvelope} for code in (404, 409, 422)},
)


def get_service(request: Request) -> ReportService:
    return cast(ReportService, request.app.state.report_service)


Reports = Annotated[ReportService, Depends(get_service)]


@router.get("")
def list_reports(
    project_id: str, service: Reports, offset: int = Query(default=0, ge=0)
) -> ReportList:
    service.check_project(project_id)
    reports, total = service.store.list_reports(project_id, offset)
    return ReportList.model_validate({"reports": reports, "total": total, "offset": offset})


@router.post("", status_code=201)
def create_report(
    project_id: str, request: CreateReportRequest, service: Reports
) -> ReportDocument:
    return service.create(project_id, request)


@router.get("/figures")
def list_report_figures(
    project_id: str, service: Reports, offset: int = Query(default=0, ge=0), linked: bool = False
) -> ReportFigureList:
    service.check_project(project_id)
    figures, total = service.repository.list_figure_results(project_id, offset)
    if linked:
        figures = [
            service.figure(
                project_id,
                service.linked_version(project_id, item["plot_id"]) or item["version_id"],
            ).model_dump(mode="json")
            for item in figures
        ]
    return ReportFigureList.model_validate({"figures": figures, "total": total, "offset": offset})


@router.get("/{report_id}")
def get_report(project_id: str, report_id: str, service: Reports) -> ReportDocument:
    return service.get(project_id, report_id)


@router.put("/{report_id}")
def save_report(
    project_id: str, report_id: str, request: SaveReportRequest, service: Reports
) -> ReportDocument:
    return service.save(project_id, report_id, request)


@router.post("/{report_id}/edits", status_code=202)
async def generate_report_content(
    project_id: str, report_id: str, request: ReportGenerateRequest, service: Reports
) -> ReportDocument:
    return service.generate(project_id, report_id, request)


@router.post("/{report_id}/edits/{edit_id}/cancel")
async def cancel_report_edit(
    project_id: str, report_id: str, edit_id: str, service: Reports
) -> ReportDocument:
    return await service.cancel(project_id, report_id, edit_id)


@router.get("/{report_id}/revisions")
def report_history(
    project_id: str, report_id: str, service: Reports, offset: int = Query(default=0, ge=0)
) -> ReportHistory:
    service.store.get(project_id, report_id)
    revisions, total = service.store.history(report_id, offset)
    return ReportHistory.model_validate({"revisions": revisions, "total": total})


@router.get("/{report_id}/revisions/{revision}")
def report_revision(
    project_id: str, report_id: str, revision: int, service: Reports
) -> ReportContent:
    service.store.get(project_id, report_id)
    return ReportContent.model_validate(service.store.revision(report_id, revision))


def get_messages(request: Request) -> ReportMessageRuntime:
    return cast(ReportMessageRuntime, request.app.state.report_messages)


Messages = Annotated[ReportMessageRuntime, Depends(get_messages)]


@router.post("/{report_id}/operations")
def apply_report_operations(
    project_id: str, report_id: str, request: ReportOperationsRequest, service: Reports
) -> ReportDocument:
    return service.operations(project_id, report_id, request)


@router.post("/{report_id}/messages", status_code=202)
async def send_report_message(
    project_id: str, report_id: str, request: ReportMessageRequest, service: Messages
) -> ReportDocument:
    return service.submit(project_id, report_id, request)


@router.post("/{report_id}/messages/{message_id}/answer", status_code=202)
async def answer_report_message(
    project_id: str,
    report_id: str,
    message_id: str,
    request: ReportMessageAnswer,
    service: Messages,
) -> ReportDocument:
    return service.answer(project_id, report_id, message_id, request)


@router.post("/{report_id}/messages/{message_id}/cancel")
async def cancel_report_message(
    project_id: str, report_id: str, message_id: str, service: Messages
) -> ReportDocument:
    return await service.cancel(project_id, report_id, message_id)
