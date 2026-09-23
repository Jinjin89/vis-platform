from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from vis_platform_backend.agents.figure_size import FigureSizeAgent, LlmFigureSizeAgent
from vis_platform_backend.agents.structured import StructuredAgentError
from vis_platform_backend.config import Settings
from vis_platform_backend.contracts.activity import AgentActivity
from vis_platform_backend.contracts.developer_trace import (
    DeveloperTraceEntry,
    TraceKind,
    TraceStatus,
)
from vis_platform_backend.contracts.figures import FigureSize
from vis_platform_backend.contracts.parameters import (
    ControlDefinition,
    ParameterUpdateRequest,
    RestoreVersionRequest,
)
from vis_platform_backend.contracts.plot_runs import (
    Approval,
    ApprovalDecisionRequest,
    ArtifactReference,
    ControlsMode,
    CreatePlotRunRequest,
    EventType,
    PlotDataObject,
    PlotResultSummary,
    PlotRunAccepted,
    PlotRunSnapshot,
    Question,
    QuestionAnswerRequest,
    QuestionChoice,
    RunEvent,
    RunFailure,
    RunLinks,
    RunProgress,
    RunStage,
    RunStatus,
    ValidationStatus,
    ValidationSummary,
)
from vis_platform_backend.contracts.plot_source import PlotSource
from vis_platform_backend.contracts.plot_versions import PlotVersionList
from vis_platform_backend.contracts.projects import CreateProjectRequest, Project
from vis_platform_backend.contracts.research import ResearchPlan
from vis_platform_backend.data.service import DataError, DatasetService
from vis_platform_backend.domain.capabilities import PlotCapabilities
from vis_platform_backend.domain.parameters import resolve_parameters
from vis_platform_backend.domain.plot_runs import TERMINAL_STATUSES, can_transition
from vis_platform_backend.execution.runner import RExecutionError
from vis_platform_backend.infrastructure.database import Repository, RequestConflictError, utc_now
from vis_platform_backend.services.demo_figures import render_demo_figure
from vis_platform_backend.services.demo_parameters import parameterize_demo
from vis_platform_backend.services.plot_source import saved_plot_source
from vis_platform_backend.services.point_maps import RENDERER as POINT_MAP_RENDERER
from vis_platform_backend.services.point_maps import copy_view_files
from vis_platform_backend.services.reference_images import ReferenceImageService
from vis_platform_backend.services.research_execution import ResearchExecutor

logger = logging.getLogger(__name__)


class ResourceNotFoundError(LookupError):
    pass


class InvalidTransitionError(RuntimeError):
    pass


class PlotCapabilityError(RuntimeError):
    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = reasons
        super().__init__(" ".join(reasons))


class PlotRunCoordinator(Protocol):
    @property
    def capabilities(self) -> PlotCapabilities: ...

    @property
    def r_runtime_available(self) -> bool: ...

    def create_project(self, request: CreateProjectRequest) -> Project: ...

    def get_project(self, project_id: str) -> Project: ...

    def create_run(
        self, request: CreatePlotRunRequest, *, planned: bool = False
    ) -> PlotRunAccepted: ...

    def get_run(self, run_id: str) -> PlotRunSnapshot: ...

    def update_parameters(
        self,
        plot_id: str,
        request: ParameterUpdateRequest,
        *,
        idempotency_key: str | None = None,
        placement: bool = False,
    ) -> PlotRunAccepted: ...

    def restore_version(
        self, plot_id: str, request: RestoreVersionRequest, *, idempotency_key: str | None = None
    ) -> PlotRunAccepted: ...

    def list_versions(self, project_id: str, plot_id: str) -> PlotVersionList: ...

    def get_source(self, project_id: str, plot_id: str, version_id: str) -> PlotSource: ...

    def cancel_run(self, run_id: str) -> PlotRunSnapshot: ...

    def answer_question(
        self, run_id: str, question_id: str, answer: QuestionAnswerRequest
    ) -> PlotRunAccepted: ...

    def decide_approval(
        self, run_id: str, approval_id: str, decision: ApprovalDecisionRequest
    ) -> PlotRunAccepted: ...

    def get_artifact(self, artifact_id: str) -> dict[str, str]: ...

    def events(
        self, run_id: str, *, last_event_id: str | None = None
    ) -> AsyncIterator[RunEvent]: ...

    async def shutdown(self) -> None: ...


class DeterministicPlotRunCoordinator:
    _STEPS: tuple[tuple[RunStage, str], ...] = (
        (RunStage.UNDERSTANDING_INTENT, "Understanding the request"),
        (RunStage.SELECTING_DATA, "Preparing illustrative data"),
        (RunStage.PROFILING_DATA, "Checking the demonstration inputs"),
        (RunStage.PLANNING_TRANSFORMATIONS, "Planning data preparation"),
        (RunStage.PLANNING_PLOT, "Planning the plot"),
        (RunStage.CHECKING_CAPABILITIES, "Checking plotting capabilities"),
        (RunStage.GENERATING_CODE, "Preparing the demonstration preview"),
        (RunStage.RUNNING_R, "Rendering the plot"),
        (RunStage.VALIDATING_PLOT, "Checking the demonstration output"),
        (RunStage.COMMITTING_VERSION, "Saving the plot version"),
    )

    def __init__(
        self,
        repository: Repository,
        settings: Settings,
        research: ResearchExecutor | None = None,
        data: DatasetService | None = None,
        figure_size_agent: FigureSizeAgent | None = None,
        reference_images: ReferenceImageService | None = None,
    ) -> None:
        self._repository = repository
        self._research, self._data = research, data
        self._reference_images = reference_images
        self._settings = settings
        self._figure_size_agent = figure_size_agent or LlmFigureSizeAgent(settings.llm)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._settings.artifact_root.mkdir(parents=True, exist_ok=True)

    @property
    def capabilities(self) -> PlotCapabilities:
        if self._research is not None and self._research.worker.available:
            return PlotCapabilities(
                data_modes=("demo", "auto", "selected"),
                generation_modes=("auto", "raw_code"),
                regeneration=True,
                description=(
                    "Versioned datasets and reusable analysis results with isolated "
                    "base-R analysis and SVG plotting. Explicit demonstration figures"
                    " are also available."
                ),
            )
        return PlotCapabilities()

    @property
    def r_runtime_available(self) -> bool:
        return self._research is not None and self._research.worker.available

    def create_project(self, request: CreateProjectRequest) -> Project:
        project = Project(
            project_id=f"project_{uuid4().hex}",
            name=request.name,
            created_at=utc_now(),
        )
        self._repository.create_project(project)
        return project

    def get_project(self, project_id: str) -> Project:
        project = self._repository.get_project(project_id)
        if project is None:
            raise ResourceNotFoundError(f"Project {project_id} was not found")
        return project

    def create_run(
        self, request: CreatePlotRunRequest, *, planned: bool = False
    ) -> PlotRunAccepted:
        if not self._repository.project_exists(request.project_id):
            raise ResourceNotFoundError(f"Project {request.project_id} was not found")
        if request.base_version_id is not None and not self._repository.version_belongs_to_project(
            request.base_version_id, request.project_id
        ):
            raise ResourceNotFoundError(f"Plot version {request.base_version_id} was not found")

        if request.request.reference_image_ids:
            if self._reference_images is None:
                raise PlotCapabilityError(("Reference image support is unavailable.",))
            self._reference_images.resolve(request.project_id, request.request.reference_image_ids)
            if not planned:
                raise PlotCapabilityError(
                    (
                        "Submit reference images through the assistant "
                        "so their visual context is planned.",
                    )
                )
            if request.data_scope.mode == "demo":
                raise PlotCapabilityError(
                    (
                        "Matching a reference image requires a dataset or saved analysis; "
                        "fixed demonstration figures cannot reproduce its design.",
                    )
                )
        blockers = self.capabilities.blockers(request)
        if blockers:
            raise PlotCapabilityError(blockers)

        if request.data_scope.mode != "demo":
            if request.research_plan is None or self._research is None:
                raise PlotCapabilityError(
                    ("Select data and resolve an analysis plan before execution.",)
                )
            self._research.validate_plan(
                request.project_id,
                request.research_plan,
                request.data_scope.bundle_ids if request.data_scope.mode == "selected" else None,
            )
        elif request.research_plan is not None:
            raise PlotCapabilityError(("A research plan cannot run with demonstration data.",))
        return self._enqueue_run(
            {**request.model_dump(mode="json"), **({"planned": True} if planned else {})}
        )

    def _enqueue_run(
        self, request: dict[str, Any], *, idempotency_key: str | None = None
    ) -> PlotRunAccepted:
        proposed_id = f"run_{uuid4().hex}"
        try:
            run_id = self._repository.create_run(
                run_id=proposed_id,
                project_id=request["project_id"],
                request=request,
                status=RunStatus.QUEUED,
                stage=RunStage.RECEIVED,
                created_at=utc_now(),
                idempotency_key=idempotency_key,
            )
        except RequestConflictError as error:
            raise InvalidTransitionError(str(error)) from error
        if run_id == proposed_id:
            self._append_event(
                run_id,
                EventType.RUN_STARTED,
                {"status": RunStatus.QUEUED.value, "stage": RunStage.RECEIVED.value},
            )
            self._start_execution(run_id)
        snapshot = self.get_run(run_id)
        return PlotRunAccepted(
            run_id=run_id, status=snapshot.status, stage=snapshot.stage, links=self._links(run_id)
        )

    def _version_record(self, project_id: str, plot_id: str, version_id: str) -> dict[str, Any]:
        run_id = self._repository.run_id_for_version(project_id, plot_id, version_id)
        if run_id is None:
            raise ResourceNotFoundError(f"Plot version {version_id} was not found")
        return self._get_record(run_id)

    def update_parameters(
        self,
        plot_id: str,
        request: ParameterUpdateRequest,
        *,
        idempotency_key: str | None = None,
        placement: bool = False,
    ) -> PlotRunAccepted:
        """A placement render sizes a version for one figure panel without making it current."""
        base = self._version_record(request.project_id, plot_id, request.base_version_id)
        result = PlotResultSummary.model_validate(base["result"])
        spec = base["interaction"].get("render_spec")
        if (
            not result.parameter_updates_available
            or spec is None
            or spec.get("renderer") not in {"demo-v1", "r-v1", POINT_MAP_RENDERER}
        ):
            raise PlotCapabilityError(
                ("This saved version has no connected parameter execution support.",)
            )
        if spec.get("renderer") == "r-v1" and not self.r_runtime_available:
            raise PlotCapabilityError(("The restricted R runtime is unavailable.",))
        values = resolve_parameters(result.controls, request.changes)
        labels = [control.label for control in result.controls if control.id in request.changes]
        child = dict(base["request"])
        child["base_version_id"] = request.base_version_id
        text = "Render at figure panel size" if placement else "Adjust " + ", ".join(labels)
        child["request"] = {**child["request"], "text": text}
        child["render_spec"] = {**spec, "parameters": values}
        child["operation"] = "parameters"
        child["placement"] = placement
        return self._enqueue_run(child, idempotency_key=idempotency_key)

    def restore_version(
        self, plot_id: str, request: RestoreVersionRequest, *, idempotency_key: str | None = None
    ) -> PlotRunAccepted:
        base = self._version_record(request.project_id, plot_id, request.source_version_id)
        spec = base["interaction"].get("render_spec")
        if spec is None or spec.get("renderer") not in {"demo-v1", "r-v1", POINT_MAP_RENDERER}:
            raise PlotCapabilityError(
                ("Restoring this saved version is not supported by its renderer.",)
            )
        child = dict(base["request"])
        child["base_version_id"] = request.source_version_id
        child["request"] = {**child["request"], "text": "Restore an earlier figure version"}
        child["render_spec"] = spec
        child["operation"] = "restore"
        return self._enqueue_run(child, idempotency_key=idempotency_key)

    def list_versions(self, project_id: str, plot_id: str) -> PlotVersionList:
        history = self._repository.plot_versions(project_id, plot_id)
        if history is None:
            raise ResourceNotFoundError(f"Plot {plot_id} was not found")
        return PlotVersionList.model_validate(
            {"project_id": project_id, "plot_id": plot_id, **history}
        )

    def get_source(self, project_id: str, plot_id: str, version_id: str) -> PlotSource:
        return saved_plot_source(self._version_record(project_id, plot_id, version_id))

    def get_run(self, run_id: str) -> PlotRunSnapshot:
        record = self._get_record(run_id)
        result = (
            PlotResultSummary.model_validate(record["result"])
            if record["result"] is not None
            else None
        )
        events = self._repository.list_events(run_id)
        progress = next(
            (
                RunProgress(
                    progress=event.payload.progress,
                    message=event.payload.message,
                )
                for event in reversed(events)
                if event.type == EventType.PROGRESS_UPDATED.value
            ),
            None,
        )
        failure = next(
            (
                RunFailure(
                    code=event.payload.code,
                    message=event.payload.message,
                    recoverable=event.payload.recoverable,
                )
                for event in reversed(events)
                if event.type == EventType.RUN_FAILED.value
            ),
            None,
        )
        interaction = record["interaction"]
        pending_question = (
            Question.model_validate(interaction["pending_question"])
            if "pending_question" in interaction
            else None
        )
        pending_approval = (
            Approval.model_validate(interaction["pending_approval"])
            if "pending_approval" in interaction
            else None
        )
        computed = []
        if self._data:
            for result_id in interaction.get("analysis_result_ids", []):
                computed_result = self._data.store.get_result(record["project_id"], result_id)
                if computed_result:
                    computed.append(computed_result)
        return PlotRunSnapshot(
            analysis_results=computed,
            run_id=record["run_id"],
            project_id=record["project_id"],
            status=RunStatus(record["status"]),
            stage=RunStage(record["stage"]),
            created_at=record["created_at"],
            updated_at=record["updated_at"],
            result=result,
            progress=progress,
            pending_question=pending_question,
            pending_approval=pending_approval,
            failure=failure,
        )

    def cancel_run(self, run_id: str) -> PlotRunSnapshot:
        record = self._get_record(run_id)
        status = RunStatus(record["status"])
        if status in TERMINAL_STATUSES:
            return self.get_run(run_id)
        self._transition(run_id, RunStatus.CANCELLED, RunStage(record["stage"]))
        self._append_event(
            run_id,
            EventType.RUN_CANCELLED,
            {"status": RunStatus.CANCELLED.value},
        )
        task = self._tasks.pop(run_id, None)
        if task is not None:
            task.cancel()
        return self.get_run(run_id)

    def answer_question(
        self, run_id: str, question_id: str, answer: QuestionAnswerRequest
    ) -> PlotRunAccepted:
        record = self._get_record(run_id)
        if RunStatus(record["status"]) is not RunStatus.AWAITING_INPUT:
            raise InvalidTransitionError("The plot run is not waiting for an answer")
        interaction = record["interaction"]
        question = Question.model_validate(interaction.get("pending_question"))
        if question.question_id != question_id:
            raise ResourceNotFoundError(f"Question {question_id} was not found")
        if answer.choice_id is not None and answer.choice_id not in {
            choice.choice_id for choice in question.choices
        }:
            raise InvalidTransitionError("The selected answer is not valid for this question")
        if answer.free_text is not None and not question.allow_free_text:
            raise InvalidTransitionError("This question does not accept free-text answers")

        interaction.pop("pending_question", None)
        interaction["question_resolved"] = True
        interaction["question_answer"] = answer.model_dump(mode="json")
        self._repository.update_interaction(run_id, interaction)
        stage = RunStage(record["stage"])
        self._transition(run_id, RunStatus.RUNNING, stage)
        self._start_execution(run_id, self._next_step_index(stage))
        return PlotRunAccepted(
            run_id=run_id,
            status=RunStatus.RUNNING,
            stage=stage,
            links=self._links(run_id),
        )

    def decide_approval(
        self, run_id: str, approval_id: str, decision: ApprovalDecisionRequest
    ) -> PlotRunAccepted:
        record = self._get_record(run_id)
        if RunStatus(record["status"]) is not RunStatus.AWAITING_APPROVAL:
            raise InvalidTransitionError("The plot run is not waiting for approval")
        interaction = record["interaction"]
        approval = Approval.model_validate(interaction.get("pending_approval"))
        if approval.approval_id != approval_id:
            raise ResourceNotFoundError(f"Approval {approval_id} was not found")

        interaction.pop("pending_approval", None)
        interaction["approval_resolved"] = True
        interaction["approval_decision"] = decision.decision.value
        self._repository.update_interaction(run_id, interaction)
        stage = RunStage(record["stage"])
        self._transition(run_id, RunStatus.RUNNING, stage)
        self._start_execution(run_id, self._next_step_index(stage))
        return PlotRunAccepted(
            run_id=run_id,
            status=RunStatus.RUNNING,
            stage=stage,
            links=self._links(run_id),
        )

    def get_artifact(self, artifact_id: str) -> dict[str, str]:
        artifact = self._repository.get_artifact(artifact_id)
        if artifact is None:
            raise ResourceNotFoundError(f"Artifact {artifact_id} was not found")
        storage_path = Path(artifact["storage_path"])
        resolved_root = self._settings.artifact_root.resolve()
        resolved_path = storage_path.resolve()
        allowed_media_types = {
            "image/jpeg",
            "image/png",
            "image/svg+xml",
            "image/tiff",
            "application/pdf",
            "text/csv",
            "application/x-r-rds",
            "text/plain",
            "application/json",
        }
        if (
            storage_path.is_symlink()
            or not resolved_path.is_relative_to(resolved_root)
            or not resolved_path.is_file()
            or artifact["media_type"] not in allowed_media_types
        ):
            raise ResourceNotFoundError(f"Artifact {artifact_id} is unavailable")
        artifact["storage_path"] = str(resolved_path)
        return artifact

    async def events(
        self, run_id: str, *, last_event_id: str | None = None
    ) -> AsyncIterator[RunEvent]:
        self._get_record(run_id)
        sequence = (
            self._repository.sequence_for_event(run_id, last_event_id)
            if last_event_id is not None
            else 0
        )
        while True:
            events = self._repository.list_events(run_id, after_sequence=sequence)
            for event in events:
                sequence = event.sequence
                yield event
            snapshot = self.get_run(run_id)
            if snapshot.status in TERMINAL_STATUSES and not events:
                return
            await asyncio.sleep(0.25)

    async def shutdown(self) -> None:
        active_tasks = list(self._tasks.items())
        for run_id, task in active_tasks:
            if not task.done():
                self._mark_interrupted(run_id)
            task.cancel()
        if active_tasks:
            await asyncio.gather(
                *(task for _run_id, task in active_tasks),
                return_exceptions=True,
            )
        self._tasks.clear()

    def recover_interrupted_runs(self) -> None:
        for run_id in self._repository.active_run_ids():
            self._mark_interrupted(run_id)

    async def _execute(self, run_id: str, start_index: int = 0) -> None:
        try:
            request = self._get_record(run_id)["request"]
            if request.get("research_plan") is not None or request.get("render_spec", {}).get(
                "renderer"
            ) in {"r-v1", POINT_MAP_RENDERER}:
                await self._execute_research(run_id)
                return
            for index in range(start_index, len(self._STEPS)):
                stage, message = self._STEPS[index]
                record = self._get_record(run_id)
                if RunStatus(record["status"]) is RunStatus.CANCELLED:
                    return
                target_status = RunStatus.RUNNING
                current_status = RunStatus(record["status"])
                if current_status is not target_status:
                    self._transition(run_id, target_status, stage)
                else:
                    self._repository.update_run(run_id, status=target_status, stage=stage)
                self._append_event(
                    run_id,
                    EventType.PROGRESS_UPDATED,
                    {
                        "status": target_status.value,
                        "stage": stage.value,
                        "progress": int((index + 1) / len(self._STEPS) * 90),
                        "message": message,
                    },
                )
                await asyncio.sleep(self._settings.fake_step_delay_seconds)
                self._trace_stage(run_id, stage, message)

                if RunStatus(self._get_record(run_id)["status"]) is RunStatus.CANCELLED:
                    return
                if "render_spec" not in record["request"] and not record["request"].get("planned"):
                    if self._pause_for_question_if_needed(run_id, stage):
                        return
                    if self._pause_for_approval_if_needed(run_id, stage):
                        return
                if stage is RunStage.PLANNING_PLOT:
                    await self._recommend_demo_size(run_id)

            self._public_activity(run_id, "render", "Plot renderer", "Render figure", "running")
            prepared_result = self._create_demo_result(run_id)
            result = prepared_result.result
            record = self._get_record(run_id)
            self._repository.commit_completed_run(
                run_id=run_id,
                project_id=record["project_id"],
                plot_id=result.plot_id,
                version_id=result.version_id,
                parent_version_id=record["request"].get("base_version_id"),
                stage=RunStage.COMMITTING_VERSION,
                result=result.model_dump(mode="json"),
                artifact_id=result.preview.artifact_id,
                artifact_media_type=result.preview.media_type,
                artifact_filename=prepared_result.artifact_path.name,
                artifact_storage_path=prepared_result.artifact_path,
                make_current=not record["request"].get("placement", False),
            )
            self._public_activity(
                run_id,
                "render",
                "Plot renderer",
                "Render figure",
                "completed",
                "The demonstration preview was rendered with its saved parameters.",
            )
            self._public_activity(
                run_id,
                "version",
                "Coordinator",
                "Save figure version",
                "completed",
                "The new version is saved; earlier versions are preserved.",
            )
            self._append_event(
                run_id,
                EventType.PREVIEW_READY,
                {
                    "artifact": result.preview.model_dump(mode="json"),
                    "provisional": False,
                },
            )
            self._append_event(
                run_id,
                EventType.RUN_COMPLETED,
                {
                    "status": RunStatus.COMPLETED.value,
                    "plot_id": result.plot_id,
                    "version_id": result.version_id,
                },
            )
        except asyncio.CancelledError:
            return
        except Exception as error:
            logger.exception("Plot run %s failed", run_id)
            self._public_activity(
                run_id,
                "render",
                "Plot renderer",
                "Render figure",
                "failed",
                "The figure could not be rendered. The previous version is unchanged.",
            )
            failed_record = self._repository.get_run(run_id)
            if (
                failed_record is not None
                and RunStatus(failed_record["status"]) not in TERMINAL_STATUSES
            ):
                self._repository.update_run(
                    run_id,
                    status=RunStatus.FAILED,
                    stage=RunStage(failed_record["stage"]),
                )
                self._append_event(
                    run_id,
                    EventType.RUN_FAILED,
                    {
                        "status": RunStatus.FAILED.value,
                        "code": "RESEARCH_EXECUTION_FAILED"
                        if request.get("research_plan")
                        else "DEMO_COORDINATOR_FAILURE",
                        "message": str(error)
                        if isinstance(error, (DataError, RExecutionError, StructuredAgentError))
                        else "The plot run failed.",
                        "recoverable": True,
                    },
                )

    async def _execute_research(self, run_id: str) -> None:
        assert self._research is not None and self._data is not None
        record = self._get_record(run_id)
        request = record["request"]
        spec = request.get("render_spec")
        self._transition(run_id, RunStatus.RUNNING, RunStage.SELECTING_DATA)
        self._append_event(
            run_id,
            EventType.PROGRESS_UPDATED,
            {
                "status": "running",
                "stage": "selecting_data",
                "progress": 15,
                "message": "Resolve the selected data revisions",
            },
        )
        if request.get("operation") == "restore" and spec:
            source = self._version_record(
                record["project_id"],
                self._repository.plot_id_for_version(request["base_version_id"]) or "",
                request["base_version_id"],
            )
            result = PlotResultSummary.model_validate(source["result"])
            original = self.get_artifact(result.preview.artifact_id)
            path = self._settings.artifact_root / run_id / "preview.svg"
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original["storage_path"], path)
            copy_view_files(Path(original["storage_path"]).parent, path.parent)
            result.version_id = f"version_{uuid4().hex}"
            result.preview = result.preview.model_copy(
                update={"artifact_id": f"artifact_{uuid4().hex}"}
            )
            result.preview.href = f"/api/v1/artifacts/{result.preview.artifact_id}"
            self._repository.update_interaction(
                run_id,
                {
                    "render_spec": spec,
                    "analysis_result_ids": [item.result_id for item in result.analysis_results],
                },
            )
        else:
            plan_data = spec["plan"] if spec else request["research_plan"]
            if spec:
                # r-v1 versions saved before explicit geometry used a 9 × 6 inch device.
                saved_size = (
                    plan_data.get("figure_size")
                    or spec.get("figure_size")
                    or {"width": 9, "height": 6, "unit": "in"}
                )
                plan_data = {
                    **plan_data,
                    "figure_size": saved_size,
                    "reuse_result_id": spec["result_id"],
                    "analysis_code": None,
                    "outputs": [],
                    "inputs": [],
                    "relationships": [],
                }
            plan = ResearchPlan.model_validate(plan_data)
            self._repository.update_run(run_id, status=RunStatus.RUNNING, stage=RunStage.RUNNING_R)
            self._append_event(
                run_id,
                EventType.PROGRESS_UPDATED,
                {
                    "status": "running",
                    "stage": "running_r",
                    "progress": 40,
                    "message": "Read the selected columns and draw the point map"
                    if plan.point_map
                    else "Reuse the saved result and render"
                    if plan.reuse_result_id
                    else "Analyze the selected data in R",
                },
            )
            self._public_activity(
                run_id, "analysis", "R worker", "Execute analysis and rendering", "running"
            )
            execution = await self._research.execute(
                record["project_id"], run_id, plan, spec.get("parameters") if spec else None
            )
            self._repository.update_interaction(
                run_id,
                {
                    **self._get_record(run_id)["interaction"],
                    "render_spec": execution.spec,
                    "analysis_result_ids": [execution.result.result_id],
                },
            )
            self._public_activity(
                run_id,
                "analysis",
                "R worker",
                "Execute analysis and rendering",
                "completed",
                "The saved outputs reference the selected input revisions.",
            )
            if execution.preview is None:
                self._repository.update_run(
                    run_id, status=RunStatus.COMPLETED, stage=RunStage.COMMITTING_VERSION
                )
                self._append_event(run_id, EventType.RUN_COMPLETED, {"status": "completed"})
                return
            path = execution.preview
            artifact_id = f"artifact_{uuid4().hex}"
            data_used = []
            for reference in execution.result.inputs:
                item = self._data.inspect(record["project_id"], reference)
                data_used.append(
                    PlotDataObject(
                        object_id=item.object_id,
                        name=item.name,
                        source=item.owner_kind,
                        summary=item.description,
                    )
                )
            values = execution.spec["parameters"]
            effective_plan = ResearchPlan.model_validate(execution.spec["plan"])
            controls: list[ControlDefinition] = [
                control.model_copy(update={"value": values[control.id]})
                for control in effective_plan.controls
            ]
            result = PlotResultSummary(
                figure_size=effective_plan.figure_size,
                contains_demo_data=execution.result.contains_demo_data,
                plot_id=(
                    self._repository.plot_id_for_version(request["base_version_id"])
                    or f"plot_{uuid4().hex}"
                )
                if request.get("base_version_id")
                else f"plot_{uuid4().hex}",
                version_id=f"version_{uuid4().hex}",
                execution_mode="r",
                interactive_view="points"
                if execution.spec.get("renderer") == POINT_MAP_RENDERER
                else None,
                title=plan.title,
                preview=ArtifactReference(
                    artifact_id=artifact_id,
                    role="preview",
                    media_type="image/svg+xml",
                    href=f"/api/v1/artifacts/{artifact_id}",
                    description=plan.description,
                ),
                controls_mode=ControlsMode(request["request"]["controls_mode"]),
                controls=controls,
                control_groups=effective_plan.control_groups,
                parameter_updates_available=bool(controls),
                data_used=data_used,
                input_objects=execution.result.inputs,
                analysis_results=[execution.result],
                data_summary="Uses saved input revisions and the recorded analysis result.",
                caption=plan.description,
                validation=ValidationSummary(
                    status=ValidationStatus.PASSED_WITH_WARNINGS,
                    warnings=[
                        (
                            "Output structure and rendering were checked; scientific and "
                            "publication review has not been performed."
                        )
                    ],
                ),
            )
        if self._reference_images:
            result.reference_images = self._reference_images.resolve(
                record["project_id"], request["request"].get("reference_image_ids") or []
            )
        self._repository.commit_completed_run(
            run_id=run_id,
            project_id=record["project_id"],
            plot_id=result.plot_id,
            version_id=result.version_id,
            parent_version_id=request.get("base_version_id"),
            stage=RunStage.COMMITTING_VERSION,
            result=result.model_dump(mode="json"),
            artifact_id=result.preview.artifact_id,
            artifact_media_type=result.preview.media_type,
            artifact_filename=path.name,
            artifact_storage_path=path,
            make_current=not request.get("placement", False),
        )
        self._append_event(
            run_id,
            EventType.PREVIEW_READY,
            {"artifact": result.preview.model_dump(mode="json"), "provisional": False},
        )
        self._append_event(
            run_id,
            EventType.RUN_COMPLETED,
            {"status": "completed", "plot_id": result.plot_id, "version_id": result.version_id},
        )
        self._public_activity(
            run_id,
            "version",
            "Coordinator",
            "Save figure version",
            "completed",
            "The figure and its exact data and analysis references are saved.",
        )

    async def _recommend_demo_size(self, run_id: str) -> None:
        record = self._get_record(run_id)
        # Saved versions carry their size; only new figures need a recommendation.
        if record["request"].get("render_spec") is not None or record["interaction"].get(
            "figure_size"
        ):
            return
        text = str(record["request"]["request"]["text"])
        answer = record["interaction"].get("question_answer", {})
        figure = render_demo_figure(
            text, survival_outcome=answer.get("choice_id") or answer.get("free_text")
        )
        turn_id = self._repository.turn_id_for_run(run_id)
        turn = self._repository.get_assistant_turn(turn_id) if turn_id else None
        original = turn["request"]["request"]["text"] if turn else text
        self._public_activity(
            run_id,
            "figure-size",
            "Figure planner",
            "Recommend figure size",
            "running",
            kind="agent",
        )
        try:
            size = await self._figure_size_agent.recommend(
                {
                    "user_request": original,
                    "request": text,
                    "figure": {
                        "kind": figure.kind.value,
                        "title": figure.title,
                        "description": figure.description,
                    },
                    "previous_answer": answer or None,
                }
            )
        except StructuredAgentError:
            self._public_activity(
                run_id,
                "figure-size",
                "Figure planner",
                "Recommend figure size",
                "failed",
                "The model could not recommend a figure size.",
                kind="agent",
            )
            raise
        record = self._get_record(run_id)
        if RunStatus(record["status"]) is RunStatus.CANCELLED:
            return
        self._repository.update_interaction(
            run_id, {**record["interaction"], "figure_size": size.model_dump(mode="json")}
        )
        self._public_activity(
            run_id,
            "figure-size",
            "Figure planner",
            "Recommend figure size",
            "completed",
            f"Recommended output: {size.width:g} × {size.height:g} inches.",
            kind="agent",
        )

    def _create_demo_result(self, run_id: str) -> PreparedDemoResult:
        record = self._get_record(run_id)
        controls_mode = ControlsMode(record["request"]["request"]["controls_mode"])
        base_version_id = record["request"].get("base_version_id")
        spec = record["request"].get("render_spec")
        if spec is None:
            question_answer = record["interaction"].get("question_answer", {})
            spec = {
                "renderer": "demo-v1",
                "figure_size": record["interaction"]["figure_size"],
                "request_text": str(record["request"]["request"]["text"]),
                "survival_outcome": question_answer.get("choice_id")
                or question_answer.get("free_text"),
                "parameters": {},
            }
        # Only historical demo-v1 specs may lack recorded geometry.
        initial_size = FigureSize.model_validate(
            spec.get("figure_size")
            or {
                "width": spec["parameters"].get("figure_width", 10),
                "height": spec["parameters"].get("figure_height", 5.83),
            }
        )
        parameterized = parameterize_demo(
            render_demo_figure(spec["request_text"], survival_outcome=spec.get("survival_outcome")),
            spec["parameters"],
            initial_size,
        )
        demo_figure = parameterized.figure
        spec = {
            **spec,
            "parameters": parameterized.values,
            "figure_size": parameterized.figure_size.model_dump(mode="json"),
        }
        self._repository.update_interaction(run_id, {**record["interaction"], "render_spec": spec})
        plot_id = (
            self._repository.plot_id_for_version(base_version_id)
            if base_version_id is not None
            else None
        )
        artifact_id = f"artifact_{uuid4().hex}"
        output_directory = self._settings.artifact_root / run_id
        output_directory.mkdir(parents=True, exist_ok=True)
        artifact_path = output_directory / "preview.svg"
        artifact_path.write_text(demo_figure.svg, encoding="utf-8")
        result = PlotResultSummary(
            plot_id=plot_id or f"plot_{uuid4().hex}",
            version_id=f"version_{uuid4().hex}",
            execution_mode="demo",
            figure_size=parameterized.figure_size,
            contains_demo_data=True,
            preview=ArtifactReference(
                artifact_id=artifact_id,
                role="preview",
                media_type="image/svg+xml",
                href=f"/api/v1/artifacts/{artifact_id}",
                description=demo_figure.description,
            ),
            controls_mode=controls_mode,
            controls=parameterized.controls if controls_mode is not ControlsMode.LANGUAGE else [],
            control_groups=parameterized.groups
            if controls_mode is not ControlsMode.LANGUAGE
            else [],
            parameter_updates_available=controls_mode is not ControlsMode.LANGUAGE,
            data_summary=(
                "This figure uses illustrative values. "
                "No research dataset was selected or analyzed."
            ),
            caption=demo_figure.description,
            title=demo_figure.title,
            validation=ValidationSummary(status=ValidationStatus.DEMO_ONLY),
        )
        return PreparedDemoResult(result=result, artifact_path=artifact_path)

    def _pause_for_question_if_needed(self, run_id: str, stage: RunStage) -> bool:
        if stage is not RunStage.SELECTING_DATA:
            return False
        record = self._get_record(run_id)
        interaction = record["interaction"]
        prompt = str(record["request"]["request"]["text"]).casefold()
        if "survival" not in prompt or interaction.get("question_resolved") is True:
            return False
        question = Question(
            question_id=f"question_{uuid4().hex}",
            prompt="Which survival outcome should be shown?",
            reason=(
                "Choose the endpoint this demonstration figure should illustrate; "
                "no research dataset is connected."
            ),
            choices=[
                QuestionChoice(choice_id="overall_survival", label="Overall survival"),
                QuestionChoice(
                    choice_id="progression_free_survival",
                    label="Progression-free survival",
                ),
            ],
        )
        interaction["pending_question"] = question.model_dump(mode="json")
        self._repository.update_interaction(run_id, interaction)
        self._transition(run_id, RunStatus.AWAITING_INPUT, stage)
        self._append_event(
            run_id,
            EventType.QUESTION_REQUIRED,
            {
                "status": RunStatus.AWAITING_INPUT.value,
                "stage": stage.value,
                "question": question.model_dump(mode="json"),
            },
        )
        return True

    def _pause_for_approval_if_needed(self, run_id: str, stage: RunStage) -> bool:
        if stage is not RunStage.PLANNING_TRANSFORMATIONS:
            return False
        record = self._get_record(run_id)
        interaction = record["interaction"]
        prompt = str(record["request"]["request"]["text"]).casefold()
        if "remove outlier" not in prompt or interaction.get("approval_resolved") is True:
            return False
        approval = Approval(
            approval_id=f"approval_{uuid4().hex}",
            operation="remove_outliers",
            summary="Remove observations classified as outliers before plotting.",
            scientific_effect="The displayed distributions and calculated statistics may change.",
        )
        interaction["pending_approval"] = approval.model_dump(mode="json")
        self._repository.update_interaction(run_id, interaction)
        self._transition(run_id, RunStatus.AWAITING_APPROVAL, stage)
        self._append_event(
            run_id,
            EventType.APPROVAL_REQUIRED,
            {
                "status": RunStatus.AWAITING_APPROVAL.value,
                "stage": stage.value,
                "approval": approval.model_dump(mode="json"),
            },
        )
        return True

    def _transition(
        self,
        run_id: str,
        status: RunStatus,
        stage: RunStage,
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        current = RunStatus(self._get_record(run_id)["status"])
        if current is not status and not can_transition(current, status):
            raise InvalidTransitionError(f"Cannot transition from {current} to {status}")
        self._repository.update_run(run_id, status=status, stage=stage, result=result)

    def _append_event(
        self, run_id: str, event_type: EventType, payload: dict[str, object]
    ) -> RunEvent:
        return self._repository.append_event(
            event_id=f"event_{uuid4().hex}",
            run_id=run_id,
            event_type=event_type,
            occurred_at=utc_now(),
            payload=payload,
        )

    def _public_activity(
        self,
        run_id: str,
        step: str,
        actor: str,
        label: str,
        status: str,
        summary: str | None = None,
        *,
        kind: str = "render",
    ) -> None:
        turn_id = self._repository.turn_id_for_run(run_id)
        if turn_id is None:
            return
        entry = AgentActivity.model_validate(
            {
                "sequence": 1,
                "step_id": run_id + ":" + step,
                "kind": kind,
                "actor": actor,
                "label": label,
                "status": status,
                "summary": summary,
                "occurred_at": utc_now(),
            }
        )
        self._repository.append_assistant_activity(turn_id, entry.model_dump(mode="json"))

    def _trace_stage(self, run_id: str, stage: RunStage, message: str) -> None:
        if not self._settings.developer_trace_enabled:
            return
        turn_id = self._repository.turn_id_for_run(run_id)
        if turn_id is None:
            return
        is_r_placeholder = stage is RunStage.RUNNING_R
        entry = DeveloperTraceEntry(
            trace_id=f"trace_{uuid4().hex}",
            sequence=1,
            kind=(TraceKind.R_EXECUTION if is_r_placeholder else TraceKind.STAGE),
            actor="demo_coordinator",
            name=stage.value,
            status=(TraceStatus.BLOCKED if is_r_placeholder else TraceStatus.SUCCEEDED),
            occurred_at=utc_now(),
            duration_ms=int(self._settings.fake_step_delay_seconds * 1_000),
            output={
                "message": message,
                "demo_only": True,
                "note": (
                    "No R worker is connected; this is a contract placeholder."
                    if is_r_placeholder
                    else "No agent or tool is connected to this demo stage yet."
                ),
            },
        )
        self._repository.append_developer_trace(
            turn_id=turn_id,
            run_id=run_id,
            entry=entry,
        )

    def _start_execution(self, run_id: str, start_index: int = 0) -> None:
        task = asyncio.create_task(self._execute(run_id, start_index))
        self._tasks[run_id] = task
        task.add_done_callback(partial(self._discard_task, run_id))

    def _next_step_index(self, stage: RunStage) -> int:
        return next(
            index + 1
            for index, (candidate, _message) in enumerate(self._STEPS)
            if candidate is stage
        )

    def _discard_task(self, run_id: str, expected: asyncio.Task[None]) -> None:
        if self._tasks.get(run_id) is expected:
            self._tasks.pop(run_id, None)

    def _mark_interrupted(self, run_id: str) -> None:
        record = self._repository.get_run(run_id)
        if record is None or RunStatus(record["status"]) in TERMINAL_STATUSES:
            return
        self._repository.update_run(
            run_id,
            status=RunStatus.FAILED,
            stage=RunStage(record["stage"]),
        )
        self._append_event(
            run_id,
            EventType.RUN_FAILED,
            {
                "status": RunStatus.FAILED.value,
                "code": "RUN_INTERRUPTED",
                "message": "The backend stopped before the plot run completed.",
                "recoverable": True,
            },
        )

    def _get_record(self, run_id: str) -> dict[str, Any]:
        record = self._repository.get_run(run_id)
        if record is None:
            raise ResourceNotFoundError(f"Plot run {run_id} was not found")
        return record

    @staticmethod
    def _links(run_id: str) -> RunLinks:
        base = f"/api/v1/plot-runs/{run_id}"
        return RunLinks(status=base, events=f"{base}/events", cancel=f"{base}/cancel")


@dataclass(frozen=True, slots=True)
class PreparedDemoResult:
    result: PlotResultSummary
    artifact_path: Path
