from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from vis_platform_backend.agents.messages import ModelImage
from vis_platform_backend.contracts.intent import IntentDecision
from vis_platform_backend.contracts.plot_runs import AutoDataScope, DataScope
from vis_platform_backend.domain.capabilities import WorkspaceCapabilities


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class ActivePlotContext:
    version_id: str
    original_request: str
    latest_request: str
    description: str
    execution_mode: str
    validation_status: str
    plot_id: str | None = None
    controls: tuple[dict[str, Any], ...] = ()
    control_groups: tuple[dict[str, Any], ...] = ()
    figure_size: dict[str, Any] | None = None
    parameter_updates_available: bool = False
    input_objects: tuple[dict[str, Any], ...] = ()
    analysis_results: tuple[dict[str, Any], ...] = ()
    reference_images: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class IntentAgentInput:
    text: str
    has_active_plot: bool
    generation_mode: str
    gallery_mode: str
    controls_mode: str
    conversation: tuple[ConversationMessage, ...] = ()
    active_plot: ActivePlotContext | None = None
    data_scope: DataScope = field(default_factory=AutoDataScope)
    capabilities: WorkspaceCapabilities = field(default_factory=WorkspaceCapabilities)
    workspace_context: dict[str, Any] = field(default_factory=dict)
    clarification_answers: tuple[dict[str, Any], ...] = ()
    previous_decision: dict[str, Any] | None = None
    reference_images: tuple[ModelImage, ...] = ()


@dataclass(frozen=True, slots=True)
class LlmTurnObservation:
    attempt: int
    duration_ms: int
    input: dict[str, Any]
    output: dict[str, Any] | None
    error: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class IntentAgentExecution:
    decision: IntentDecision
    turns: tuple[LlmTurnObservation, ...]


class IntentAgent(Protocol):
    async def analyze(self, input: IntentAgentInput) -> IntentAgentExecution: ...


class IntentAgentError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        turns: tuple[LlmTurnObservation, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.turns = turns
