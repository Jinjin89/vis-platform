from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Header, status
from fastapi.responses import StreamingResponse

from vis_platform_backend.api.dependencies import CoordinatorDependency
from vis_platform_backend.api.errors import (
    CONFLICT_RESPONSE,
    NOT_FOUND_RESPONSE,
    VALIDATION_RESPONSE,
)
from vis_platform_backend.contracts.plot_runs import (
    ApprovalDecisionRequest,
    CreatePlotRunRequest,
    PlotRunAccepted,
    PlotRunSnapshot,
    QuestionAnswerRequest,
)

router = APIRouter(prefix="/plot-runs", tags=["plot runs"])


LastEventId = Annotated[str | None, Header(alias="Last-Event-ID")]


@router.post(
    "",
    response_model=PlotRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses=NOT_FOUND_RESPONSE | VALIDATION_RESPONSE,
)
async def create_plot_run(
    request: CreatePlotRunRequest,
    coordinator: CoordinatorDependency,
) -> PlotRunAccepted:
    return coordinator.create_run(request)


@router.get("/{run_id}", response_model=PlotRunSnapshot, responses=NOT_FOUND_RESPONSE)
def get_plot_run(
    run_id: str,
    coordinator: CoordinatorDependency,
) -> PlotRunSnapshot:
    return coordinator.get_run(run_id)


@router.post(
    "/{run_id}/cancel",
    response_model=PlotRunSnapshot,
    responses=NOT_FOUND_RESPONSE | CONFLICT_RESPONSE,
)
async def cancel_plot_run(
    run_id: str,
    coordinator: CoordinatorDependency,
) -> PlotRunSnapshot:
    return coordinator.cancel_run(run_id)


@router.post(
    "/{run_id}/questions/{question_id}/answer",
    response_model=PlotRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses=NOT_FOUND_RESPONSE | CONFLICT_RESPONSE | VALIDATION_RESPONSE,
)
async def answer_plot_run_question(
    run_id: str,
    question_id: str,
    answer: QuestionAnswerRequest,
    coordinator: CoordinatorDependency,
) -> PlotRunAccepted:
    return coordinator.answer_question(run_id, question_id, answer)


@router.post(
    "/{run_id}/approvals/{approval_id}",
    response_model=PlotRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses=NOT_FOUND_RESPONSE | CONFLICT_RESPONSE | VALIDATION_RESPONSE,
)
async def decide_plot_run_approval(
    run_id: str,
    approval_id: str,
    decision: ApprovalDecisionRequest,
    coordinator: CoordinatorDependency,
) -> PlotRunAccepted:
    return coordinator.decide_approval(run_id, approval_id, decision)


@router.get(
    "/{run_id}/events",
    response_class=StreamingResponse,
    responses={
        **NOT_FOUND_RESPONSE,
        200: {
            "description": (
                "Ordered Server-Sent Events. Each data field conforms to "
                "run-events-v1.schema.json. Last-Event-ID replays later events."
            ),
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                }
            },
        },
    },
)
def stream_plot_run_events(
    run_id: str,
    coordinator: CoordinatorDependency,
    last_event_id: LastEventId = None,
) -> StreamingResponse:
    coordinator.get_run(run_id)

    async def stream() -> AsyncIterator[str]:
        async for event in coordinator.events(run_id, last_event_id=last_event_id):
            yield (
                f"id: {event.event_id}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n"
            )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
