from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, model_validator

from .artifacts import ArtifactReference as ArtifactReference
from .common import SCHEMA_VERSION, StrictModel
from .datasets import AnalysisResult, ObjectReference
from .figures import FigureSize
from .parameters import ControlDefinition, ControlGroup
from .reference_images import ReferenceImage
from .research import ResearchPlan


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStage(StrEnum):
    RECEIVED = "received"
    UNDERSTANDING_INTENT = "understanding_intent"
    SELECTING_DATA = "selecting_data"
    PROFILING_DATA = "profiling_data"
    PLANNING_TRANSFORMATIONS = "planning_transformations"
    PLANNING_PLOT = "planning_plot"
    CHECKING_CAPABILITIES = "checking_capabilities"
    GENERATING_CODE = "generating_code"
    RUNNING_R = "running_r"
    VALIDATING_PLOT = "validating_plot"
    COMMITTING_VERSION = "committing_version"


class GenerationMode(StrEnum):
    AUTO = "auto"
    SKILL = "skill"
    RAW_CODE = "raw_code"


class GalleryMode(StrEnum):
    OFF = "off"
    AUTO = "auto"
    SELECTED = "selected"


class ControlsMode(StrEnum):
    LANGUAGE = "language"
    PANEL = "panel"
    HYBRID = "hybrid"


class EventType(StrEnum):
    RUN_STARTED = "run.started"
    PROGRESS_UPDATED = "progress.updated"
    QUESTION_REQUIRED = "question.required"
    APPROVAL_REQUIRED = "approval.required"
    PREVIEW_READY = "preview.ready"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"


class AutoDataScope(StrictModel):
    mode: Literal["auto"] = "auto"


class SelectedDataScope(StrictModel):
    mode: Literal["selected"]
    bundle_ids: list[str] = Field(min_length=1)


class DemoDataScope(StrictModel):
    """Explicitly select illustrative data instead of project data."""

    mode: Literal["demo"]


DataScope = Annotated[
    AutoDataScope | SelectedDataScope | DemoDataScope, Field(discriminator="mode")
]


class PlotRequest(StrictModel):
    text: str = Field(default="", max_length=10_000)
    reference_image_ids: list[str] | None = Field(default=None, max_length=3)
    generation_mode: GenerationMode = GenerationMode.AUTO
    skill_id: str | None = None
    gallery_mode: GalleryMode = GalleryMode.OFF
    gallery_reference_id: str | None = None
    controls_mode: ControlsMode = ControlsMode.HYBRID

    @model_validator(mode="after")
    def validate_conditional_fields(self) -> PlotRequest:
        if not self.text.strip() and not self.reference_image_ids:
            raise ValueError("Provide a request or a reference image.")
        if self.reference_image_ids and len(set(self.reference_image_ids)) != len(
            self.reference_image_ids
        ):
            raise ValueError("Reference image IDs must be unique.")
        if self.skill_id is not None and self.generation_mode is not GenerationMode.SKILL:
            raise ValueError("skill_id requires generation_mode='skill'")
        if self.gallery_mode is GalleryMode.SELECTED and self.gallery_reference_id is None:
            raise ValueError("gallery_reference_id is required when gallery_mode='selected'")
        if self.gallery_mode is not GalleryMode.SELECTED and self.gallery_reference_id is not None:
            raise ValueError("gallery_reference_id requires gallery_mode='selected'")
        return self


class CreatePlotRunRequest(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    project_id: str
    request: PlotRequest
    data_scope: DataScope = Field(default_factory=AutoDataScope)
    base_version_id: str | None = None
    research_plan: ResearchPlan | None = None


class RunLinks(StrictModel):
    status: str
    events: str
    cancel: str


class PlotRunAccepted(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    run_id: str
    status: RunStatus
    stage: RunStage
    links: RunLinks


class ValidationStatus(StrEnum):
    DEMO_ONLY = "demo_only"
    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"


class ValidationSummary(StrictModel):
    status: ValidationStatus
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_warning_status(self) -> ValidationSummary:
        if self.status is ValidationStatus.PASSED and self.warnings:
            raise ValueError("passed validation cannot contain warnings")
        if self.status is ValidationStatus.PASSED_WITH_WARNINGS and not self.warnings:
            raise ValueError("passed_with_warnings validation requires warnings")
        return self


class PlotDataObject(StrictModel):
    object_id: str
    name: str
    source: str
    summary: str
    variable_mappings: dict[str, str] = Field(default_factory=dict)


class PlotResultSummary(StrictModel):
    reference_images: list[ReferenceImage] = Field(default_factory=list)
    figure_size: FigureSize | None = None
    contains_demo_data: bool | None = None
    plot_id: str
    version_id: str
    execution_mode: Literal["demo", "r"]
    preview: ArtifactReference
    controls_mode: ControlsMode
    controls: list[ControlDefinition] = Field(default_factory=list)
    control_groups: list[ControlGroup] = Field(default_factory=list)
    parameter_schema_version: Literal["1.0"] = "1.0"
    parameter_updates_available: bool = False
    data_summary: str = "Data provenance was not recorded for this version."
    data_used: list[PlotDataObject] = Field(default_factory=list)
    input_objects: list[ObjectReference] = Field(default_factory=list)
    analysis_results: list[AnalysisResult] = Field(default_factory=list)
    caption: str | None = None
    title: str | None = None
    validation: ValidationSummary

    @model_validator(mode="after")
    def validate_controls(self) -> PlotResultSummary:
        identifiers = [control.id for control in self.controls]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("control identifiers must be unique")
        groups = [group.id for group in self.control_groups]
        if len(groups) != len(set(groups)):
            raise ValueError("control groups must be unique")
        if groups and any(control.group not in groups for control in self.controls):
            raise ValueError("every control must belong to a declared group")
        if any(
            control.visible_when is not None
            and (
                control.visible_when.control_id not in identifiers
                or control.visible_when.control_id == control.id
            )
            for control in self.controls
        ):
            raise ValueError("visibility must reference another defined control")
        if self.parameter_updates_available and not self.controls:
            raise ValueError("parameter updates require executable controls")
        return self


class QuestionChoice(StrictModel):
    choice_id: str
    label: str
    description: str | None = None


class Question(StrictModel):
    question_id: str
    prompt: str
    reason: str
    choices: list[QuestionChoice] = Field(min_length=2)
    allow_free_text: bool = False


class QuestionAnswerRequest(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    choice_id: str | None = None
    free_text: str | None = Field(default=None, min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def require_one_answer(self) -> QuestionAnswerRequest:
        if (self.choice_id is None) == (self.free_text is None):
            raise ValueError("provide exactly one of choice_id or free_text")
        return self


class Approval(StrictModel):
    approval_id: str
    operation: str
    summary: str
    scientific_effect: str


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ApprovalDecisionRequest(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    decision: ApprovalDecision


class RunProgress(StrictModel):
    progress: int = Field(ge=0, le=100)
    message: str


class RunFailure(StrictModel):
    code: str
    message: str
    recoverable: bool


class PlotRunSnapshot(StrictModel):
    analysis_results: list[AnalysisResult] = Field(default_factory=list)
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    run_id: str
    project_id: str
    status: RunStatus
    stage: RunStage
    created_at: datetime
    updated_at: datetime
    result: PlotResultSummary | None = None
    progress: RunProgress | None = None
    pending_question: Question | None = None
    pending_approval: Approval | None = None
    failure: RunFailure | None = None


class RunEventBase(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    event_id: str
    run_id: str
    sequence: int = Field(ge=1)
    occurred_at: datetime


class RunStartedPayload(StrictModel):
    status: Literal["queued"]
    stage: Literal["received"]


class ProgressPayload(StrictModel):
    status: Literal["running"]
    stage: RunStage
    progress: int = Field(ge=0, le=100)
    message: str


class QuestionRequiredPayload(StrictModel):
    status: Literal["awaiting_input"]
    stage: RunStage
    question: Question


class ApprovalRequiredPayload(StrictModel):
    status: Literal["awaiting_approval"]
    stage: RunStage
    approval: Approval


class PreviewReadyPayload(StrictModel):
    artifact: ArtifactReference
    provisional: bool


class RunCompletedPayload(StrictModel):
    status: Literal["completed"]
    plot_id: str | None = None
    version_id: str | None = None


class RunFailedPayload(StrictModel):
    status: Literal["failed"]
    code: str
    message: str
    recoverable: bool


class RunCancelledPayload(StrictModel):
    status: Literal["cancelled"]


class RunStartedEvent(RunEventBase):
    type: Literal["run.started"] = "run.started"
    payload: RunStartedPayload


class ProgressUpdatedEvent(RunEventBase):
    type: Literal["progress.updated"] = "progress.updated"
    payload: ProgressPayload


class QuestionRequiredEvent(RunEventBase):
    type: Literal["question.required"] = "question.required"
    payload: QuestionRequiredPayload


class ApprovalRequiredEvent(RunEventBase):
    type: Literal["approval.required"] = "approval.required"
    payload: ApprovalRequiredPayload


class PreviewReadyEvent(RunEventBase):
    type: Literal["preview.ready"] = "preview.ready"
    payload: PreviewReadyPayload


class RunCompletedEvent(RunEventBase):
    type: Literal["run.completed"] = "run.completed"
    payload: RunCompletedPayload


class RunFailedEvent(RunEventBase):
    type: Literal["run.failed"] = "run.failed"
    payload: RunFailedPayload


class RunCancelledEvent(RunEventBase):
    type: Literal["run.cancelled"] = "run.cancelled"
    payload: RunCancelledPayload


type RunEvent = Annotated[
    RunStartedEvent
    | ProgressUpdatedEvent
    | QuestionRequiredEvent
    | ApprovalRequiredEvent
    | PreviewReadyEvent
    | RunCompletedEvent
    | RunFailedEvent
    | RunCancelledEvent,
    Field(discriminator="type"),
]

RUN_EVENT_ADAPTER: TypeAdapter[RunEvent] = TypeAdapter(RunEvent)


def build_run_event(
    *,
    event_id: str,
    run_id: str,
    sequence: int,
    event_type: EventType,
    occurred_at: datetime,
    payload: dict[str, object],
) -> RunEvent:
    return RUN_EVENT_ADAPTER.validate_python(
        {
            "event_id": event_id,
            "run_id": run_id,
            "sequence": sequence,
            "type": event_type.value,
            "occurred_at": occurred_at,
            "payload": payload,
        }
    )
