from __future__ import annotations

import hmac
from datetime import datetime
from time import perf_counter
from typing import Any, cast
from uuid import uuid4

from pydantic import JsonValue, ValidationError

from vis_platform_backend.agents.data_agent import DataAgent
from vis_platform_backend.agents.intent import (
    ActivePlotContext,
    ConversationMessage,
    IntentAgent,
    IntentAgentError,
    IntentAgentInput,
    LlmTurnObservation,
)
from vis_platform_backend.agents.messages import ModelContext, ModelImage
from vis_platform_backend.agents.structured import StructuredAgentError
from vis_platform_backend.config import Settings
from vis_platform_backend.contracts.assistant_turns import (
    AssistantTurnAccepted,
    AssistantTurnLinks,
    AssistantTurnOutcome,
    AssistantTurnRequest,
    AssistantTurnResponse,
)
from vis_platform_backend.contracts.datasets import ObjectDescription, ObjectReference
from vis_platform_backend.contracts.developer_trace import (
    DeveloperTraceEntry,
    DeveloperTraceResponse,
    TraceKind,
    TraceStatus,
)
from vis_platform_backend.contracts.intent import IntentAction, IntentDecision, IntentKind
from vis_platform_backend.contracts.parameters import ControlDefinition, ParameterUpdateRequest
from vis_platform_backend.contracts.plot_runs import (
    AutoDataScope,
    CreatePlotRunRequest,
    DemoDataScope,
    PlotRequest,
    PlotResultSummary,
)
from vis_platform_backend.contracts.questions import ClarificationQuestion, PlannerQuestions
from vis_platform_backend.contracts.research import ResearchPlan
from vis_platform_backend.data.service import DataError, DatasetService
from vis_platform_backend.domain.capabilities import WorkspaceCapabilities
from vis_platform_backend.domain.parameters import InvalidParameterError, resolve_parameters
from vis_platform_backend.infrastructure.database import Repository, RequestConflictError, utc_now
from vis_platform_backend.services.assistant_runtime import AssistantRuntime
from vis_platform_backend.services.figure_controls import figure_controls, resolve_figure_size
from vis_platform_backend.services.plot_marks import MarkedPlot, PlotMarkService
from vis_platform_backend.services.plot_runs import (
    PlotCapabilityError,
    PlotRunCoordinator,
    ResourceNotFoundError,
)
from vis_platform_backend.services.point_maps import PointMapService
from vis_platform_backend.services.reference_images import ReferenceImageService
from vis_platform_backend.services.workspace_context import WorkspaceContextTools


class AssistantTurnError(RuntimeError):
    def __init__(self, message: str, *, code: str, turn_id: str) -> None:
        super().__init__(message)
        self.code = code
        self.turn_id = turn_id


class DeveloperTraceAccessError(PermissionError):
    pass


class AssistantTurnService:
    def __init__(
        self,
        *,
        repository: Repository,
        coordinator: PlotRunCoordinator,
        intent_agent: IntentAgent,
        settings: Settings,
        data: DatasetService | None = None,
        data_agent: DataAgent | None = None,
        reference_images: ReferenceImageService | None = None,
        point_maps: PointMapService | None = None,
    ) -> None:
        self._repository = repository
        self._reference_images = reference_images
        self._synchronous_turns: set[str] = set()
        self._data, self._data_agent = data, data_agent
        self._coordinator = coordinator
        self._intent_agent = intent_agent
        self._trace_enabled = settings.developer_trace_enabled
        self._trace_token = settings.developer_trace_token
        self.runtime = AssistantRuntime(repository, self._execute_turn, reference_images)
        self._plot_marks = PlotMarkService(repository, settings.artifact_root, point_maps)
        self._context_tools = WorkspaceContextTools(repository, data)
        self._secrets = tuple(
            secret for secret in (settings.llm.api_key,) if secret is not None and secret.strip()
        )

    async def create_turn(
        self, request: AssistantTurnRequest, idempotency_key: str | None = None
    ) -> AssistantTurnResponse:
        turn_id = self._prepare_turn(request, idempotency_key)
        state = self._repository.assistant_execution(turn_id)
        if state and state["response"] is not None:
            return AssistantTurnResponse.model_validate(state["response"])
        if turn_id in self._synchronous_turns or turn_id in self.runtime.tasks:
            raise DataError("This request is already processing.", "REQUEST_IN_PROGRESS", 409)
        if state and state["status"] != "running":
            raise DataError(
                "This request has already stopped. Send a new request to retry.",
                "REQUEST_STOPPED",
                409,
            )
        self._synchronous_turns.add(turn_id)
        try:
            return await self.runtime.execute(turn_id)
        finally:
            self._synchronous_turns.discard(turn_id)

    def start_turn(
        self, request: AssistantTurnRequest, idempotency_key: str | None = None
    ) -> AssistantTurnAccepted:
        turn_id = self._prepare_turn(request, idempotency_key)
        state = self._repository.assistant_execution(turn_id)
        if state and state["status"] == "running" and turn_id not in self._synchronous_turns:
            return self.runtime.start(turn_id)
        return self.runtime.accepted(turn_id)

    def _prepare_turn(
        self, request: AssistantTurnRequest, idempotency_key: str | None = None
    ) -> str:
        if not self._repository.project_exists(request.project_id):
            raise ResourceNotFoundError(f"Project {request.project_id} was not found")
        self._active_plot_context(request)
        if request.parameter_changes:
            assert request.base_version_id is not None
            saved = self._repository.result_for_version(request.base_version_id, request.project_id)
            assert saved is not None
            result = PlotResultSummary.model_validate(saved)
            if not result.parameter_updates_available:
                raise DataError(
                    "This version has no editable parameters.", "INVALID_PARAMETERS", 422
                )
            try:
                resolve_parameters(result.controls, request.parameter_changes, require_change=False)
            except InvalidParameterError as error:
                raise DataError(str(error), "INVALID_PARAMETERS", 422) from error
        if request.plot_marks:
            assert request.base_version_id is not None
            self._plot_marks.check(request.project_id, request.base_version_id, request.plot_marks)
        if request.request.reference_image_ids:
            if self._reference_images is None:
                raise DataError("Reference images are unavailable.", "IMAGES_UNAVAILABLE", 409)
            self._reference_images.resolve(request.project_id, request.request.reference_image_ids)
        if self._data:
            for result_id in request.result_ids:
                if self._data.store.get_result(request.project_id, result_id) is None:
                    raise DataError(
                        "The selected result was not found in this project.", "NOT_FOUND", 404
                    )
        turn_id = f"turn_{uuid4().hex}"
        try:
            saved_id = self._repository.create_assistant_turn(
                turn_id=turn_id,
                project_id=request.project_id,
                request=request.model_dump(mode="json"),
                created_at=utc_now(),
                idempotency_key=idempotency_key,
            )
        except RequestConflictError as error:
            raise DataError(str(error), "IDEMPOTENCY_CONFLICT", 409) from error
        if saved_id != turn_id:
            return saved_id
        self._repository.initialize_assistant_execution(turn_id)
        self.runtime.activity(
            turn_id, "received", "routing", "Coordinator", "Request received", "completed"
        )
        return turn_id

    async def _execute_turn(self, turn_id: str) -> AssistantTurnResponse:
        record = self._repository.get_assistant_turn(turn_id)
        assert record is not None
        request = AssistantTurnRequest.model_validate(record["request"])
        created_at = datetime.fromisoformat(record["created_at"])
        active_plot = self._active_plot_context(request)
        answers = self.runtime.answers_context(turn_id)
        pass_id = str(len(answers))
        context: dict[str, Any] = {"parameter_drafts": request.parameter_changes}
        for name, label, tool in (
            ("get_current_data", "Check current data", self._context_tools.get_current_data),
            (
                "get_current_results",
                "Check current results",
                self._context_tools.get_current_results,
            ),
        ):
            step = name + ":" + pass_id
            started = perf_counter()
            self.runtime.activity(
                turn_id, step, "tool", "Workspace tools", label, "running", tool_name=name
            )
            context[name] = tool(request.project_id)
            self.runtime.activity(
                turn_id,
                step,
                "tool",
                "Workspace tools",
                label,
                "completed",
                summary=context[name]["summary"],
                tool_name=name,
                duration_ms=int((perf_counter() - started) * 1000),
            )
        available_image_ids = self._available_image_ids(request, turn_id, active_plot)
        model_images: tuple[ModelImage, ...] = ()
        if available_image_ids and self._reference_images:
            model_images = self._reference_images.model_images(
                request.project_id, available_image_ids
            )
            context["available_reference_image_ids"] = available_image_ids
            self.runtime.activity(
                turn_id,
                "reference-images:" + pass_id,
                "tool",
                "Reference images",
                "Prepare plot references",
                "completed",
                summary="Reference images are included in planning.",
            )
        marked = await self._marked_plot(turn_id, request, pass_id)
        if marked:
            context["plot_marks"] = marked.marks
        intent_step = "intent:" + pass_id
        intent_label = "Continue with your choices" if answers else "Understand and plan"
        self.runtime.activity(
            turn_id, intent_step, "agent", "Intent planner", intent_label, "running"
        )
        intent_started = perf_counter()
        self._trace(
            turn_id=turn_id,
            kind=TraceKind.STAGE,
            actor="assistant_gateway",
            name="request_received",
            status=TraceStatus.SUCCEEDED,
            input={
                "text": request.request.text,
                "has_active_plot": request.base_version_id is not None,
                "generation_mode": request.request.generation_mode.value,
                "gallery_mode": request.request.gallery_mode.value,
                "controls_mode": request.request.controls_mode.value,
            },
        )

        agent_input = IntentAgentInput(
            text=request.request.text.strip()
            or (
                "Restyle the current figure using this reference and its saved data."
                if active_plot
                else "Create a plot like this reference using available data."
            ),
            reference_images=model_images + ((marked.image,) if marked else ()),
            has_active_plot=request.base_version_id is not None,
            generation_mode=request.request.generation_mode.value,
            gallery_mode=request.request.gallery_mode.value,
            controls_mode=request.request.controls_mode.value,
            conversation=self._conversation(request.project_id, turn_id),
            active_plot=active_plot,
            data_scope=request.data_scope,
            capabilities=WorkspaceCapabilities(
                plotting=self._coordinator.capabilities,
                data_upload=self._data is not None,
                data_discovery=self._data is not None,
            ),
            workspace_context=context,
            clarification_answers=answers,
            previous_decision=record["intent"] if answers else None,
        )
        try:
            execution = await self._intent_agent.analyze(agent_input)
        except IntentAgentError as error:
            self.runtime.activity(
                turn_id,
                intent_step,
                "agent",
                "Intent planner",
                intent_label,
                "failed",
                summary="The planner could not complete this request.",
                duration_ms=int((perf_counter() - intent_started) * 1000),
            )
            self._persist_llm_turns(turn_id, error.turns)
            self._trace(
                turn_id=turn_id,
                kind=TraceKind.ERROR,
                actor="intent_agent",
                name="intent_detection",
                status=TraceStatus.FAILED,
                error={"code": error.code, "message": str(error)},
            )
            raise AssistantTurnError(
                str(error),
                code=error.code,
                turn_id=turn_id,
            ) from error

        self._persist_llm_turns(turn_id, execution.turns)
        decision = execution.decision
        if decision.reference_image_ids is not None and not set(
            decision.reference_image_ids
        ).issubset(available_image_ids):
            raise AssistantTurnError(
                "The planner selected an unavailable reference image.",
                code="INVALID_REFERENCE_SELECTION",
                turn_id=turn_id,
            )
        self.runtime.activity(
            turn_id,
            intent_step,
            "agent",
            "Intent planner",
            intent_label,
            "completed",
            summary=str(_sanitize_value(decision.decision_summary, self._secrets))[:1000],
            duration_ms=int((perf_counter() - intent_started) * 1000),
        )
        self._trace(
            turn_id=turn_id,
            kind=TraceKind.INTENT_DECISION,
            actor="intent_agent",
            name="intent_detection",
            status=TraceStatus.SUCCEEDED,
            output=decision.model_dump(mode="json"),
        )

        selection_changed = False
        if (
            request.data_scope.mode == "selected"
            and active_plot
            and active_plot.execution_mode == "r"
            and self._data
        ):
            previous_sources = self._data.dataset_ids_for_objects(
                request.project_id,
                [ObjectReference.model_validate(item) for item in active_plot.input_objects],
            )
            selection_changed = not previous_sources.issubset(set(request.data_scope.bundle_ids))
        real_refinement = (
            decision.next_action is IntentAction.REFINE_CONTEXT
            and active_plot is not None
            and active_plot.execution_mode == "r"
            and decision.refinement is not None
            and (
                selection_changed
                or not decision.refinement.reuse_data
                or any(change.change_class != "visual" for change in decision.refinement.changes)
                or request.request.reference_image_ids is not None
                or decision.reference_image_ids is not None
                or decision.refinement.execution_strategy != "parameters"
            )
        )
        if (
            decision.next_action is IntentAction.EXECUTE_ANALYSIS
            or (
                decision.next_action is IntentAction.BUILD_CONTEXT
                and self._plot_request(request, decision).data_scope.mode != "demo"
            )
            or real_refinement
        ):
            return await self._start_research(
                turn_id, created_at, request, decision, context, answers, active_plot, marked
            )

        if decision.next_action in {IntentAction.BUILD_CONTEXT, IntentAction.REFINE_CONTEXT}:
            if decision.kind is IntentKind.PLOT_REFINE and active_plot is None:
                raise AssistantTurnError(
                    "There is no active plot to refine.",
                    code="ACTIVE_PLOT_REQUIRED",
                    turn_id=turn_id,
                )
            if decision.missing_context:
                return self._reply(
                    turn_id,
                    created_at,
                    decision,
                    "To proceed, I need: " + "; ".join(decision.missing_context) + ".",
                    blocked=True,
                    ask_user=True,
                )
            if decision.kind is IntentKind.PLOT_REFINE:
                assert active_plot is not None and decision.refinement is not None
                if not active_plot.parameter_updates_available or active_plot.plot_id is None:
                    return self._reply(
                        turn_id,
                        created_at,
                        decision,
                        "This saved figure has no connected parameter controls.",
                        blocked=True,
                    )
                if (
                    (request.data_scope.mode == "selected" and active_plot.execution_mode == "demo")
                    or not decision.refinement.reuse_data
                    or (
                        active_plot.execution_mode == "demo"
                        and decision.mode_requests.data == "auto"
                    )
                ):
                    return self._reply(
                        turn_id,
                        created_at,
                        decision,
                        "Changing the figure's data requires data access and a new plot plan.",
                        blocked=True,
                    )
                if (
                    request.request.generation_mode.value
                    not in self._coordinator.capabilities.generation_modes
                    or decision.mode_requests.generation
                    not in (None, *self._coordinator.capabilities.generation_modes)
                    or request.request.gallery_mode.value
                    not in self._coordinator.capabilities.gallery_modes
                    or decision.mode_requests.gallery
                    not in (None, *self._coordinator.capabilities.gallery_modes)
                ):
                    return self._reply(
                        turn_id,
                        created_at,
                        decision,
                        "The requested plotting engine or gallery is not connected.",
                        blocked=True,
                    )
                changes = decision.refinement.changes
                if any(change.change_class != "visual" for change in changes):
                    return self._reply(
                        turn_id,
                        created_at,
                        decision,
                        "This change requires a new analysis or scientific decision.",
                        blocked=True,
                    )
                if len({change.target for change in changes}) != len(changes):
                    return self._reply(
                        turn_id,
                        created_at,
                        decision,
                        "Each parameter needs one value before I can apply the changes.",
                        blocked=True,
                    )
                try:
                    update = ParameterUpdateRequest.model_validate(
                        {
                            "project_id": request.project_id,
                            "base_version_id": active_plot.version_id,
                            "changes": {
                                **{change.target: change.value for change in changes},
                                **request.parameter_changes,
                            },
                        }
                    )
                    run = self._coordinator.update_parameters(
                        active_plot.plot_id, update, idempotency_key=turn_id
                    )
                except (ValidationError, InvalidParameterError, PlotCapabilityError) as error:
                    message = (
                        str(error)
                        if not isinstance(error, ValidationError)
                        else "The requested parameter values need clarification."
                    )
                    return self._reply(turn_id, created_at, decision, message, blocked=True)
                data_mode = active_plot.execution_mode
            else:
                try:
                    plot_request = self._plot_request(request, decision)
                except ValidationError:
                    return self._reply(
                        turn_id,
                        created_at,
                        decision,
                        "The requested plotting options need more information "
                        "before I can proceed.",
                        blocked=True,
                    )
                blockers = self._coordinator.capabilities.blockers(plot_request)
                if blockers:
                    return self._reply(
                        turn_id, created_at, decision, " ".join(blockers), blocked=True
                    )
                run = self._coordinator.create_run(plot_request, planned=True)
                data_mode = plot_request.data_scope.mode
            self._repository.complete_assistant_turn(
                turn_id=turn_id,
                intent=decision.model_dump(mode="json"),
                outcome=AssistantTurnOutcome.PLOT_RUN.value,
                message=None,
                run_id=run.run_id,
            )
            self._trace(
                turn_id=turn_id,
                run_id=run.run_id,
                kind=TraceKind.ROUTING,
                actor="assistant_gateway",
                name="create_plot_run",
                status=TraceStatus.SUCCEEDED,
                output={
                    "route": decision.next_action.value,
                    "data_mode": data_mode,
                    "run_id": run.run_id,
                },
            )
            self.runtime.activity(
                turn_id,
                "route",
                "routing",
                "Coordinator",
                "Ready to render",
                "completed",
                summary="The request and available rendering capabilities are ready.",
            )
            return AssistantTurnResponse(
                turn_id=turn_id,
                outcome=AssistantTurnOutcome.PLOT_RUN,
                intent=decision,
                plot_run=run,
                links=self._links(turn_id),
                created_at=created_at,
            )

        if (
            decision.next_action is IntentAction.CALL_DATA_TOOLS
            and self._data is not None
            and self._data_agent is not None
        ):
            selected_ids = (
                request.data_scope.bundle_ids
                if request.data_scope.mode == "selected"
                else decision.dataset_ids
            )
            try:
                datasets = (
                    [self._data.get(request.project_id, item) for item in selected_ids]
                    if selected_ids
                    else self._data.list_datasets(request.project_id).datasets
                )
                self.runtime.activity(
                    turn_id,
                    "inspect-data",
                    "tool",
                    "Workspace tools",
                    "Inspect selected objects",
                    "running",
                    tool_name="inspect_objects",
                )
                answer = await self._data_agent.answer(
                    {
                        "request": decision.normalized_request,
                        "datasets": [item.model_dump(mode="json") for item in datasets],
                        "results": context.get("get_current_results"),
                        "previous_answers": answers,
                    }
                )
                self.runtime.activity(
                    turn_id,
                    "inspect-data",
                    "tool",
                    "Workspace tools",
                    "Inspect selected objects",
                    "completed",
                    tool_name="inspect_objects",
                    summary="Read the recorded schemas, profiles, and relationships.",
                )
                if answer.questions:
                    decision = decision.model_copy(update={"questions": answer.questions})
                return self._reply(
                    turn_id,
                    created_at,
                    decision,
                    answer.message,
                    blocked=bool(answer.questions),
                    ask_user=bool(answer.questions),
                )
            except (DataError, StructuredAgentError) as error:
                self.runtime.activity(
                    turn_id,
                    "inspect-data",
                    "tool",
                    "Workspace tools",
                    "Inspect selected objects",
                    "failed",
                    tool_name="inspect_objects",
                    summary=str(error),
                )
                return self._reply(turn_id, created_at, decision, str(error), blocked=True)
        if decision.next_action is IntentAction.CALL_DATA_TOOLS:
            return self._reply(
                turn_id,
                created_at,
                decision,
                "Data discovery and uploads are not connected in this workspace.",
                blocked=True,
            )
        if decision.next_action is IntentAction.EXECUTE_WORKSPACE_ACTION:
            return self._reply(
                turn_id,
                created_at,
                decision,
                "Chat-based workspace actions are not connected. "
                "You can use Stop for an active run or Export SVG for a completed figure.",
                blocked=True,
            )
        if decision.next_action is IntentAction.READ_PLOT_CONTEXT and active_plot is None:
            return self._reply(
                turn_id,
                created_at,
                decision,
                "There is no active figure to inspect.",
                blocked=True,
            )
        return self._reply(turn_id, created_at, decision, str(decision.user_reply))

    async def _start_research(
        self,
        turn_id: str,
        created_at: datetime,
        request: AssistantTurnRequest,
        decision: IntentDecision,
        context: dict[str, Any],
        answers: tuple[dict[str, Any], ...],
        active_plot: ActivePlotContext | None,
        marked: MarkedPlot | None = None,
    ) -> AssistantTurnResponse:
        if self._data is None or self._data_agent is None:
            return self._reply(
                turn_id, created_at, decision, "Data access is not connected.", blocked=True
            )
        plot_request = self._plot_request(request, decision)
        active_point_map = self._active_render_plan(request).get("point_map")
        # A point map stays one when refined, whichever interface asks.
        interactive = request.request.interactive or active_point_map is not None
        render_only = bool(
            active_plot
            and decision.refinement
            and decision.refinement.reuse_data
            and decision.refinement.execution_strategy != "replan_analysis"
            and all(change.change_class == "visual" for change in decision.refinement.changes)
        )
        if render_only and active_plot and self._data and request.data_scope.mode == "selected":
            previous_sources = self._data.dataset_ids_for_objects(
                request.project_id,
                [ObjectReference.model_validate(item) for item in active_plot.input_objects],
            )
            render_only = previous_sources.issubset(set(request.data_scope.bundle_ids))
        blockers = self._coordinator.capabilities.blockers(plot_request)
        if blockers:
            return self._reply(turn_id, created_at, decision, " ".join(blockers), blocked=True)
        try:
            selected = (
                request.data_scope.bundle_ids
                if request.data_scope.mode == "selected"
                else decision.dataset_ids
            )
            catalog = self._data.list_datasets(request.project_id)
            datasets = (
                [self._data.get(request.project_id, item) for item in selected]
                if selected
                else catalog.datasets
            )
            objects: list[ObjectDescription] = [
                obj for dataset in datasets for obj in dataset.objects if obj.readiness == "ready"
            ]
            results = self._data.results(request.project_id)
            chosen_results = results.results
            if request.result_ids:
                chosen_results = []
                for result_id in request.result_ids:
                    chosen = self._data.store.get_result(request.project_id, result_id)
                    if chosen is None:
                        raise DataError(
                            "The selected analysis result is unavailable.", "NOT_FOUND", 404
                        )
                    chosen_results.append(chosen)
            if not objects and not chosen_results:
                return self._reply(
                    turn_id,
                    created_at,
                    decision,
                    (
                        "Add a dataset from your analysis platform or upload files using "
                        "the data selector, then I can work with their contents."
                    ),
                    blocked=True,
                )
            self.runtime.activity(
                turn_id,
                "data-plan",
                "agent",
                "Data and analysis planner",
                "Select objects and plan analysis",
                "running",
            )
            planning = await self._data_agent.plan(
                ModelContext(
                    {
                        "render_only": render_only,
                        "interactive_view": interactive,
                        "reference_images": [
                            image.model_dump(mode="json")
                            for image in self._reference_images.resolve(
                                request.project_id, plot_request.request.reference_image_ids or []
                            )
                        ]
                        if self._reference_images
                        else [],
                        "request": decision.normalized_request,
                        "user_request": request.request.text,
                        "parameter_drafts": request.parameter_changes,
                        "intent": decision.kind.value,
                        "dataset_scope": selected,
                        "objects": [item.model_dump(mode="json") for item in objects[:30]],
                        "catalog_complete": (bool(selected) or catalog.complete)
                        and len(objects) <= 30,
                        "dataset_total": catalog.total,
                        "relationships": [
                            item.model_dump(mode="json")
                            for dataset in datasets
                            for item in dataset.relationships
                        ],
                        "results": [item.model_dump(mode="json") for item in chosen_results],
                        "selected_result_ids": request.result_ids,
                        "previous_answers": answers,
                        "active_figure": {
                            "render_code": self._active_render_code(request),
                            "point_map": active_point_map,
                            "figure_size": active_plot.figure_size,
                            "controls": active_plot.controls,
                            "control_groups": active_plot.control_groups,
                            "description": active_plot.description,
                            "inputs": active_plot.input_objects,
                            "results": active_plot.analysis_results,
                        }
                        if active_plot
                        else None,
                        **({"plot_marks": marked.marks} if marked else {}),
                    },
                    images=(
                        self._reference_images.model_images(
                            request.project_id, plot_request.request.reference_image_ids or []
                        )
                        if self._reference_images
                        else ()
                    )
                    + ((marked.image,) if marked else ()),
                )
            )
            self.runtime.activity(
                turn_id,
                "data-plan",
                "agent",
                "Data and analysis planner",
                "Select objects and plan analysis",
                "completed",
                summary=planning.summary[:1000],
            )
            if planning.action == "ask_user":
                clarified = decision.model_copy(update={"questions": planning.questions})
                return self._reply(
                    turn_id, created_at, clarified, planning.summary, blocked=True, ask_user=True
                )
            assert planning.plan is not None
            if planning.plan.point_map is not None and not interactive:
                raise DataError(
                    "Point maps are drawn in Pinpoint; plan an R figure here.",
                    "INVALID_POINT_MAP",
                    422,
                )
            if planning.plan.point_map is not None and planning.plan.reuse_result_id:
                raise DataError(
                    "A point map names its table, and any image, as plan inputs.",
                    "INVALID_POINT_MAP",
                    422,
                )
            if render_only and planning.plan.point_map is None:
                assert active_plot is not None
                result_ids = {item["result_id"] for item in active_plot.analysis_results}
                if (
                    planning.plan.reuse_result_id not in result_ids
                    or planning.plan.analysis_code is not None
                ):
                    raise DataError(
                        "A visual refinement must reuse the figure's saved analysis.",
                        "INVALID_RENDER_REUSE",
                        422,
                    )
            if (
                decision.kind is IntentKind.ANALYSIS_CREATE
                and planning.plan.render_code is not None
            ):
                return self._reply(
                    turn_id,
                    created_at,
                    decision,
                    (
                        "The analysis plan includes a figure that was not requested. "
                        "Please specify whether a figure is wanted."
                    ),
                    blocked=True,
                    ask_user=True,
                )
            if request.result_ids and planning.plan.reuse_result_id not in request.result_ids:
                raise DataError(
                    "The plan must use the analysis result you selected.",
                    "INVALID_DATA_SELECTION",
                    422,
                )
            if request.parameter_changes:
                # Explicit panel values take precedence over inferred language changes.
                controls: list[ControlDefinition] = list(planning.plan.controls)
                groups = planning.plan.control_groups
                size = planning.plan.figure_size
                if size is not None:
                    controls, groups = figure_controls(controls, groups, size)
                values = resolve_parameters(
                    controls, request.parameter_changes, require_change=False
                )
                planning.plan = ResearchPlan.model_validate(
                    {
                        **planning.plan.model_dump(),
                        "controls": [
                            {**control.model_dump(), "value": values[control.id]}
                            for control in controls
                        ],
                        "control_groups": [group.model_dump() for group in groups],
                        "figure_size": resolve_figure_size(values, size) if size else None,
                    }
                )
            plot_request.research_plan = planning.plan
            run = self._coordinator.create_run(plot_request, planned=True)
        except (
            DataError,
            StructuredAgentError,
            PlotCapabilityError,
            InvalidParameterError,
        ) as error:
            self.runtime.activity(
                turn_id,
                "data-plan",
                "agent",
                "Data and analysis planner",
                "Select objects and plan analysis",
                "failed",
                summary=str(error)[:1000],
            )
            return self._reply(turn_id, created_at, decision, str(error), blocked=True)
        self._repository.complete_assistant_turn(
            turn_id=turn_id,
            intent=decision.model_dump(mode="json"),
            outcome=AssistantTurnOutcome.PLOT_RUN.value,
            message=None,
            run_id=run.run_id,
        )
        return AssistantTurnResponse(
            turn_id=turn_id,
            outcome=AssistantTurnOutcome.PLOT_RUN,
            intent=decision,
            plot_run=run,
            links=self._links(turn_id),
            created_at=created_at,
        )

    def _reply(
        self,
        turn_id: str,
        created_at: datetime,
        decision: IntentDecision,
        message: str,
        *,
        blocked: bool = False,
        ask_user: bool = False,
    ) -> AssistantTurnResponse:
        requested_action = decision.next_action
        updates: dict[str, Any] = {"user_reply": message}
        if blocked:
            updates["next_action"] = IntentAction.ASK_USER if ask_user else IntentAction.REPLY
        decision = IntentDecision.model_validate({**decision.model_dump(), **updates})
        question = None
        if decision.next_action is IntentAction.ASK_USER:
            questions = decision.questions or [
                ClarificationQuestion(
                    header="One detail",
                    prompt=message,
                    selection="text",
                    reason="This information is needed to continue the same request.",
                )
            ]
            question = PlannerQuestions(questions=questions)
            self.runtime.activity(
                turn_id,
                question.interaction_id,
                "question",
                "Coordinator",
                "Your input is needed",
                "waiting",
                summary="Waiting for the choices needed to continue.",
            )
        else:
            self.runtime.activity(
                turn_id,
                "route",
                "routing",
                "Coordinator",
                "Readiness check" if blocked else "Response ready",
                "blocked" if blocked else "completed",
                summary=message[:700]
                if blocked
                else "Answer this request without creating a figure.",
            )
        outcome = AssistantTurnOutcome.QUESTION if question else AssistantTurnOutcome.MESSAGE
        self._repository.complete_assistant_turn(
            turn_id=turn_id,
            intent=decision.model_dump(mode="json"),
            outcome=outcome.value,
            message=message,
            run_id=None,
        )
        self._trace(
            turn_id=turn_id,
            kind=TraceKind.ROUTING,
            actor="assistant_gateway",
            name="readiness_blocked" if blocked else "reply_without_plot",
            status=TraceStatus.BLOCKED if blocked else TraceStatus.SUCCEEDED,
            output={
                "route": decision.next_action.value,
                "requested_route": requested_action.value,
                "artifact_created": False,
                "plot_run_created": False,
            },
        )
        return AssistantTurnResponse(
            turn_id=turn_id,
            outcome=outcome,
            question=question,
            intent=decision,
            message=message,
            links=self._links(turn_id),
            created_at=created_at,
        )

    def _plot_request(
        self, request: AssistantTurnRequest, decision: IntentDecision
    ) -> CreatePlotRunRequest:
        options = request.request.model_dump()
        options["text"] = decision.normalized_request
        if request.request.reference_image_ids is not None:
            options["reference_image_ids"] = request.request.reference_image_ids
        elif decision.reference_image_ids is not None:
            options["reference_image_ids"] = decision.reference_image_ids
        elif decision.kind is IntentKind.PLOT_REFINE:
            base = self._active_plot_context(request)
            options["reference_image_ids"] = (
                [item["image_id"] for item in base.reference_images] if base else []
            )
        else:
            options["reference_image_ids"] = []
        for name in ("generation", "gallery", "controls"):
            requested_mode = getattr(decision.mode_requests, name)
            current_mode = options[name + "_mode"]
            pinned = (name == "generation" and current_mode != "auto") or (
                name == "gallery" and current_mode != "off"
            )
            if requested_mode is not None and not pinned:
                options[name + "_mode"] = requested_mode
        data_scope = request.data_scope
        if isinstance(data_scope, AutoDataScope) and decision.mode_requests.data == "demo":
            data_scope = DemoDataScope(mode="demo")
        elif isinstance(data_scope, DemoDataScope) and decision.mode_requests.data == "auto":
            data_scope = AutoDataScope()
        return CreatePlotRunRequest(
            project_id=request.project_id,
            request=PlotRequest.model_validate(options),
            data_scope=data_scope,
            base_version_id=(
                request.base_version_id if decision.kind is IntentKind.PLOT_REFINE else None
            ),
        )

    def _active_plot_context(self, request: AssistantTurnRequest) -> ActivePlotContext | None:
        if request.base_version_id is None:
            return None
        result = self._repository.result_for_version(request.base_version_id, request.project_id)
        if result is None:
            raise ResourceNotFoundError(f"Plot version {request.base_version_id} was not found")
        history = self._repository.request_history_for_version(request.base_version_id)
        return ActivePlotContext(
            version_id=request.base_version_id,
            original_request=str(history[0]["request"]["text"]),
            latest_request=str(history[-1]["request"]["text"]),
            description=str(result["preview"]["description"]),
            execution_mode=str(result["execution_mode"]),
            validation_status=str(result["validation"]["status"]),
            plot_id=str(result["plot_id"]),
            controls=tuple(result.get("controls", [])),
            control_groups=tuple(result.get("control_groups", [])),
            figure_size=result.get("figure_size"),
            parameter_updates_available=bool(result.get("parameter_updates_available", False)),
            input_objects=tuple(result.get("input_objects", [])),
            analysis_results=tuple(result.get("analysis_results", [])),
            reference_images=tuple(result.get("reference_images", [])),
        )

    async def _marked_plot(
        self, turn_id: str, request: AssistantTurnRequest, pass_id: str
    ) -> MarkedPlot | None:
        """The plot as the user marked it, and where each mark falls in its data."""
        if not request.plot_marks:
            return None
        assert request.base_version_id is not None
        marked = await self._plot_marks.prepare(
            request.project_id, request.base_version_id, request.plot_marks
        )
        located = sum(1 for mark in marked.marks if mark.get("plot_regions"))
        self.runtime.activity(
            turn_id,
            "plot-marks:" + pass_id,
            "tool",
            "Plot marks",
            "Locate your marks",
            "completed",
            summary=(
                f"{located} of {len(marked.marks)} marks fall inside a plotting region."
                if "plot_regions" in marked.marks[0]
                else "Your marks are shown on the plot image."
            ),
        )
        return marked

    def _available_image_ids(
        self, request: AssistantTurnRequest, turn_id: str, active: ActivePlotContext | None
    ) -> list[str]:
        if request.request.reference_image_ids is not None:
            return request.request.reference_image_ids
        if active and active.reference_images:
            return [str(image["image_id"]) for image in active.reference_images]
        history = self._repository.assistant_history(request.project_id, before_turn_id=turn_id)
        for turn in reversed(history):
            if turn.get("reference_image_ids"):
                return list(turn["reference_image_ids"])
        return []

    def _active_render_plan(self, request: AssistantTurnRequest) -> dict[str, Any]:
        """The saved research plan of the version being refined, if it has one."""
        if not request.base_version_id:
            return {}
        plot_id = self._repository.plot_id_for_version(request.base_version_id)
        run_id = self._repository.run_id_for_version(
            request.project_id, plot_id or "", request.base_version_id
        )
        record = self._repository.get_run(run_id) if run_id else None
        plan = record["interaction"].get("render_spec", {}).get("plan", {}) if record else {}
        return plan if isinstance(plan, dict) else {}

    def _active_render_code(self, request: AssistantTurnRequest) -> str | None:
        return self._active_render_plan(request).get("render_code")

    def _conversation(self, project_id: str, turn_id: str) -> tuple[ConversationMessage, ...]:
        messages = []
        for turn in self._repository.assistant_history(project_id, before_turn_id=turn_id):
            reference_note = (
                ("\nAttached plot references: " + ", ".join(turn["reference_image_ids"]))
                if turn.get("reference_image_ids")
                else ""
            )
            messages.append(
                ConversationMessage(role="user", content=turn["text"][:2_000] + reference_note)
            )
            reply = turn["message"]
            if reply is None:
                reply = "Plot run status: " + str(turn["run_status"]) + "."
                if turn["result"] is not None:
                    reply += " " + str(turn["result"]["preview"]["description"])
            messages.append(ConversationMessage(role="assistant", content=reply[:2_000]))
        return tuple(messages)

    def get_trace(
        self,
        turn_id: str,
        *,
        access_token: str | None,
    ) -> DeveloperTraceResponse:
        if not self._trace_enabled:
            raise ResourceNotFoundError("Developer trace is disabled")
        if (
            self._trace_token is None
            or access_token is None
            or not hmac.compare_digest(self._trace_token, access_token)
        ):
            raise DeveloperTraceAccessError("Developer trace access was denied")
        turn = self._repository.get_assistant_turn(turn_id)
        if turn is None:
            raise ResourceNotFoundError(f"Assistant turn {turn_id} was not found")
        return DeveloperTraceResponse(
            turn_id=turn_id,
            run_id=turn["run_id"],
            entries=self._repository.list_developer_trace(turn_id),
        )

    def get_trace_for_run(
        self,
        run_id: str,
        *,
        access_token: str | None,
    ) -> DeveloperTraceResponse:
        turn_id = self._repository.turn_id_for_run(run_id)
        if turn_id is None:
            raise ResourceNotFoundError(f"No assistant trace exists for run {run_id}")
        return self.get_trace(turn_id, access_token=access_token)

    def _persist_llm_turns(
        self,
        turn_id: str,
        observations: tuple[LlmTurnObservation, ...],
    ) -> None:
        for observation in observations:
            self._trace(
                turn_id=turn_id,
                kind=TraceKind.LLM_TURN,
                actor="intent_agent",
                name="deepseek_intent",
                status=(TraceStatus.SUCCEEDED if observation.error is None else TraceStatus.FAILED),
                duration_ms=observation.duration_ms,
                input=observation.input,
                output=observation.output,
                error=observation.error,
            )

    def _trace(
        self,
        *,
        turn_id: str,
        kind: TraceKind,
        actor: str,
        name: str,
        status: TraceStatus,
        run_id: str | None = None,
        duration_ms: int | None = None,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        if not self._trace_enabled:
            return
        entry = DeveloperTraceEntry(
            trace_id=f"trace_{uuid4().hex}",
            sequence=1,
            kind=kind,
            actor=actor,
            name=name,
            status=status,
            occurred_at=utc_now(),
            duration_ms=duration_ms,
            input=_sanitized_mapping(input, self._secrets),
            output=_sanitized_mapping(output, self._secrets),
            error=_sanitized_mapping(error, self._secrets),
        )
        self._repository.append_developer_trace(
            turn_id=turn_id,
            run_id=run_id,
            entry=entry,
        )

    def _links(self, turn_id: str) -> AssistantTurnLinks:
        return self.runtime.links(turn_id)


_FORBIDDEN_TRACE_KEYS = {
    "api_key",
    "authorization",
    "data_file",
    "physical_path",
    "reasoning_content",
    "storage_path",
    "image_url",
}


def _sanitized_mapping(
    value: dict[str, Any] | None,
    secrets: tuple[str, ...],
) -> dict[str, JsonValue] | None:
    if value is None:
        return None
    sanitized = _sanitize_value(value, secrets)
    return cast(dict[str, JsonValue], sanitized)


def _sanitize_value(value: Any, secrets: tuple[str, ...]) -> JsonValue:
    if isinstance(value, dict):
        return {
            str(key): (
                "[redacted]"
                if str(key).casefold() in _FORBIDDEN_TRACE_KEYS
                else _sanitize_value(item, secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item, secrets) for item in value]
    if isinstance(value, str):
        sanitized = value
        for secret in secrets:
            sanitized = sanitized.replace(secret, "[redacted]")
        return sanitized
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)
