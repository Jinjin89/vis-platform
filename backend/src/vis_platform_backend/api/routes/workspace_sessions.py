from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request

from vis_platform_backend.contracts.common import ApiErrorEnvelope
from vis_platform_backend.contracts.workspace_sessions import (
    CreateWorkspaceSession,
    WorkspaceSession,
    WorkspaceSessionDocument,
    WorkspaceSessionList,
)
from vis_platform_backend.services.workspace_sessions import WorkspaceSessionService

router = APIRouter(
    prefix="/projects/{project_id}/workspace-sessions",
    tags=["workspace sessions"],
    responses={code: {"model": ApiErrorEnvelope} for code in (404, 409, 422)},
)


def get_service(request: Request) -> WorkspaceSessionService:
    return cast(WorkspaceSessionService, request.app.state.workspace_sessions)


Sessions = Annotated[WorkspaceSessionService, Depends(get_service)]


@router.get("")
def list_sessions(
    project_id: str, service: Sessions, offset: int = Query(default=0, ge=0)
) -> WorkspaceSessionList:
    return service.list_sessions(project_id, offset)


@router.post("", status_code=201)
def create_session(
    project_id: str, request: CreateWorkspaceSession, service: Sessions
) -> WorkspaceSession:
    return service.create(project_id, request)


@router.get("/{session_id}")
def get_session(project_id: str, session_id: str, service: Sessions) -> WorkspaceSessionDocument:
    return service.get(project_id, session_id)
