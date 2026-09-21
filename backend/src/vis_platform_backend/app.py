from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from vis_platform_backend.agents.data_agent import DataAgent, LlmDataAgent
from vis_platform_backend.agents.deepseek_intent import DeepSeekIntentAgent
from vis_platform_backend.agents.figure_size import FigureSizeAgent
from vis_platform_backend.agents.intent import IntentAgent
from vis_platform_backend.agents.r_repair import LlmRRepairAgent, RRepairAgent
from vis_platform_backend.agents.report_planner import LlmReportPlanner, ReportPlanner
from vis_platform_backend.api.router import api_router
from vis_platform_backend.config import Settings
from vis_platform_backend.contracts.common import ApiError, ApiErrorEnvelope
from vis_platform_backend.data.providers import PlatformConnectionError
from vis_platform_backend.data.repository import DatasetRepository
from vis_platform_backend.data.service import DataError, DatasetService
from vis_platform_backend.domain.parameters import InvalidParameterError
from vis_platform_backend.domain.questions import InvalidPlannerAnswer
from vis_platform_backend.execution.runner import RWorker
from vis_platform_backend.infrastructure.database import Repository
from vis_platform_backend.infrastructure.figure_compositions import FigureCompositionRepository
from vis_platform_backend.infrastructure.reference_images import ReferenceImageRepository
from vis_platform_backend.infrastructure.reports import ReportRepository
from vis_platform_backend.services.assistant_turns import (
    AssistantTurnError,
    AssistantTurnService,
    DeveloperTraceAccessError,
)
from vis_platform_backend.services.figure_compositions import FigureCompositionService
from vis_platform_backend.services.figure_exports import FigureExporter
from vis_platform_backend.services.plot_runs import (
    DeterministicPlotRunCoordinator,
    InvalidTransitionError,
    PlotCapabilityError,
    ResourceNotFoundError,
)
from vis_platform_backend.services.reference_images import ReferenceImageService
from vis_platform_backend.services.report_messages import ReportMessageRuntime
from vis_platform_backend.services.reports import ReportService
from vis_platform_backend.services.research_execution import ResearchExecutor


def create_app(
    settings: Settings | None = None,
    *,
    intent_agent: IntentAgent | None = None,
    data_agent: DataAgent | None = None,
    figure_size_agent: FigureSizeAgent | None = None,
    report_planner: ReportPlanner | None = None,
    r_repair_agent: RRepairAgent | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings.from_environment()
    resolved_intent_agent = intent_agent or DeepSeekIntentAgent(resolved_settings.llm)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        repository = Repository(resolved_settings.database_path)
        repository.initialize()
        image_store = ReferenceImageRepository(resolved_settings.database_path)
        reference_images = ReferenceImageService(
            repository, image_store, resolved_settings.artifact_root.parent / "reference-images"
        )
        reference_images.cleanup()
        app.state.reference_images = reference_images
        app.state.reference_image_slots = asyncio.Semaphore(2)
        data_store = DatasetRepository(resolved_settings.database_path)
        worker = RWorker(
            resolved_settings.r_home,
            resolved_settings.r_sandbox,
            resolved_settings.artifact_root.parent / "jobs",
        )
        await worker.verify()
        resolved_data_agent = data_agent or LlmDataAgent(resolved_settings.llm)
        dataset_service = DatasetService(
            repository, data_store, resolved_settings, resolved_data_agent, worker
        )
        app.state.dataset_service = dataset_service
        research = ResearchExecutor(
            dataset_service,
            worker,
            repository,
            resolved_settings.artifact_root,
            r_repair_agent
            or (
                LlmRRepairAgent(resolved_settings.llm) if resolved_settings.llm.configured else None
            ),
        )
        coordinator = DeterministicPlotRunCoordinator(
            repository,
            resolved_settings,
            research,
            dataset_service,
            figure_size_agent,
            reference_images,
        )
        coordinator.recover_interrupted_runs()
        assistant_turn_service = AssistantTurnService(
            repository=repository,
            coordinator=coordinator,
            intent_agent=resolved_intent_agent,
            settings=resolved_settings,
            data=dataset_service,
            data_agent=resolved_data_agent,
            reference_images=reference_images,
        )
        assistant_turn_service.runtime.recover()
        app.state.settings = resolved_settings
        app.state.repository = repository
        figure_exporter = FigureExporter(repository, resolved_settings.artifact_root)
        app.state.figure_exporter = figure_exporter
        app.state.coordinator = coordinator
        app.state.assistant_turn_service = assistant_turn_service
        report_store = ReportRepository(resolved_settings.database_path)
        report_service = ReportService(
            report_store,
            repository,
            dataset_service,
            assistant_turn_service,
            coordinator,
            resolved_data_agent,
            reference_images,
        )
        app.state.report_service = report_service
        report_service.recover()
        report_messages = ReportMessageRuntime(
            report_service, report_planner or LlmReportPlanner(resolved_settings.llm)
        )
        app.state.report_messages = report_messages
        report_messages.recover()
        # Created after the report store, which owns the shared figure selection table.
        composition_store = FigureCompositionRepository(resolved_settings.database_path)
        app.state.figure_compositions = FigureCompositionService(
            composition_store, repository, reference_images, figure_exporter
        )
        yield
        composition_store.close()
        await report_messages.shutdown()
        await report_service.shutdown()
        report_store.close()
        await assistant_turn_service.runtime.shutdown()
        await coordinator.shutdown()
        await dataset_service.shutdown()
        image_store.close()
        data_store.close()
        repository.close()

    application = FastAPI(
        title="Vis Platform API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(api_router)

    @application.exception_handler(DataError)
    async def data_error_handler(_request: Request, exception: DataError) -> JSONResponse:
        payload = ApiErrorEnvelope(
            error=ApiError(
                code=exception.code, message=str(exception), recoverable=exception.status != 404
            )
        )
        return JSONResponse(status_code=exception.status, content=payload.model_dump(mode="json"))

    @application.exception_handler(PlatformConnectionError)
    async def platform_error_handler(
        _request: Request, exception: PlatformConnectionError
    ) -> JSONResponse:
        payload = ApiErrorEnvelope(
            error=ApiError(code="PLATFORM_UNAVAILABLE", message=str(exception), recoverable=True)
        )
        return JSONResponse(status_code=502, content=payload.model_dump(mode="json"))

    @application.exception_handler(ResourceNotFoundError)
    async def not_found_handler(
        _request: Request, exception: ResourceNotFoundError
    ) -> JSONResponse:
        payload = ApiErrorEnvelope(
            error=ApiError(code="NOT_FOUND", message=str(exception), recoverable=False)
        )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=payload.model_dump(mode="json"),
        )

    @application.exception_handler(InvalidTransitionError)
    async def conflict_handler(
        _request: Request, exception: InvalidTransitionError
    ) -> JSONResponse:
        payload = ApiErrorEnvelope(
            error=ApiError(code="INVALID_TRANSITION", message=str(exception), recoverable=True)
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=payload.model_dump(mode="json"),
        )

    @application.exception_handler(InvalidPlannerAnswer)
    async def invalid_planner_answer(
        _request: Request, exception: InvalidPlannerAnswer
    ) -> JSONResponse:
        payload = ApiErrorEnvelope(
            error=ApiError(code="INVALID_ANSWER", message=str(exception), recoverable=True)
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=payload.model_dump(mode="json"),
        )

    @application.exception_handler(InvalidParameterError)
    async def invalid_parameter_handler(
        _request: Request, exception: InvalidParameterError
    ) -> JSONResponse:
        payload = ApiErrorEnvelope(
            error=ApiError(code="INVALID_PLOT_PARAMETERS", message=str(exception), recoverable=True)
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=payload.model_dump(mode="json"),
        )

    @application.exception_handler(PlotCapabilityError)
    async def plot_capability_handler(
        _request: Request, exception: PlotCapabilityError
    ) -> JSONResponse:
        payload = ApiErrorEnvelope(
            error=ApiError(
                code="PLOT_CAPABILITY_UNAVAILABLE",
                message=str(exception),
                recoverable=True,
            )
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=payload.model_dump(mode="json"),
        )

    @application.exception_handler(AssistantTurnError)
    async def assistant_turn_handler(
        _request: Request, exception: AssistantTurnError
    ) -> JSONResponse:
        error_status = {
            "ACTIVE_PLOT_REQUIRED": status.HTTP_409_CONFLICT,
            "LLM_NOT_CONFIGURED": status.HTTP_503_SERVICE_UNAVAILABLE,
        }.get(exception.code, status.HTTP_502_BAD_GATEWAY)
        payload = ApiErrorEnvelope(
            error=ApiError(
                code=exception.code,
                message=str(exception),
                recoverable=True,
                details={
                    "turn_id": exception.turn_id,
                    "trace": f"/api/v1/assistant-turns/{exception.turn_id}/trace",
                },
            )
        )
        return JSONResponse(
            status_code=error_status,
            content=payload.model_dump(mode="json"),
        )

    @application.exception_handler(DeveloperTraceAccessError)
    async def trace_access_handler(
        _request: Request, exception: DeveloperTraceAccessError
    ) -> JSONResponse:
        payload = ApiErrorEnvelope(
            error=ApiError(
                code="TRACE_ACCESS_DENIED",
                message=str(exception),
                recoverable=True,
            )
        )
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=payload.model_dump(mode="json"),
        )

    @application.exception_handler(RequestValidationError)
    async def validation_handler(
        _request: Request, _exception: RequestValidationError
    ) -> JSONResponse:
        payload = ApiErrorEnvelope(
            error=ApiError(
                code="VALIDATION_ERROR",
                message="The request does not match the API contract.",
                recoverable=True,
            )
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=payload.model_dump(mode="json"),
        )

    return application


app = create_app()
