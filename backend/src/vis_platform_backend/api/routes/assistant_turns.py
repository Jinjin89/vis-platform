from typing import Annotated

from fastapi import APIRouter, Header, Response, status
from fastapi.responses import StreamingResponse

from vis_platform_backend.api.dependencies import AssistantTurnServiceDependency
from vis_platform_backend.api.errors import (
    CONFLICT_RESPONSE,
    FORBIDDEN_RESPONSE,
    NOT_FOUND_RESPONSE,
    UPSTREAM_RESPONSE,
    VALIDATION_RESPONSE,
)
from vis_platform_backend.contracts.assistant_turns import (
    AssistantTurnAccepted,
    AssistantTurnRequest,
    AssistantTurnResponse,
    AssistantTurnSnapshot,
)
from vis_platform_backend.contracts.developer_trace import DeveloperTraceResponse
from vis_platform_backend.contracts.questions import PlannerAnswerRequest

router = APIRouter(prefix="/assistant-turns", tags=["assistant turns"])

DeveloperTraceToken = Annotated[
    str | None,
    Header(alias="X-Developer-Trace-Token"),
]


@router.post(
    "",
    response_model=AssistantTurnResponse | AssistantTurnAccepted,
    responses=NOT_FOUND_RESPONSE
    | CONFLICT_RESPONSE
    | VALIDATION_RESPONSE
    | UPSTREAM_RESPONSE
    | {202: {"model": AssistantTurnAccepted, "description": "Async planner request accepted."}},
)
async def create_assistant_turn(
    request: AssistantTurnRequest,
    service: AssistantTurnServiceDependency,
    response: Response,
    prefer: Annotated[str | None, Header()] = None,
    idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
) -> AssistantTurnResponse | AssistantTurnAccepted:
    if prefer == "respond-async":
        accepted = service.start_turn(request, idempotency_key)
        response.status_code = status.HTTP_202_ACCEPTED
        return accepted
    return await service.create_turn(request, idempotency_key)


@router.get(
    "/{turn_id}/trace",
    response_model=DeveloperTraceResponse,
    responses=NOT_FOUND_RESPONSE | FORBIDDEN_RESPONSE,
)
def get_assistant_turn_trace(
    turn_id: str,
    service: AssistantTurnServiceDependency,
    trace_token: DeveloperTraceToken = None,
) -> DeveloperTraceResponse:
    return service.get_trace(turn_id, access_token=trace_token)


@router.get("/{turn_id}", responses=NOT_FOUND_RESPONSE)
async def get_assistant_state(
    turn_id: str, project_id: str, service: AssistantTurnServiceDependency
) -> AssistantTurnSnapshot:
    return service.runtime.snapshot(turn_id, project_id)


@router.get("/{turn_id}/events", responses=NOT_FOUND_RESPONSE)
async def assistant_events(
    turn_id: str,
    project_id: str,
    service: AssistantTurnServiceDependency,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    service.runtime.snapshot(turn_id, project_id)
    after = int(last_event_id) if last_event_id and last_event_id.isdigit() else -1
    return StreamingResponse(
        service.runtime.events(turn_id, project_id, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/{turn_id}/answer",
    status_code=status.HTTP_202_ACCEPTED,
    responses=NOT_FOUND_RESPONSE | CONFLICT_RESPONSE | VALIDATION_RESPONSE,
)
async def answer_planner(
    turn_id: str, request: PlannerAnswerRequest, service: AssistantTurnServiceDependency
) -> AssistantTurnAccepted:
    return service.runtime.answer(turn_id, request)


@router.post("/{turn_id}/cancel", responses=NOT_FOUND_RESPONSE)
async def cancel_assistant(
    turn_id: str, project_id: str, service: AssistantTurnServiceDependency
) -> AssistantTurnSnapshot:
    return service.runtime.cancel(turn_id, project_id)
