from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import ConfigDict, Field, JsonValue, model_validator

from .common import StrictModel
from .questions import ClarificationQuestion


class IntentKind(StrEnum):
    SOCIAL = "social"
    PLOT_CREATE = "plot_create"
    PLOT_REFINE = "plot_refine"
    DATA_QUERY = "data_query"
    ANALYSIS_CREATE = "analysis_create"
    PLOT_QUERY = "plot_query"
    WORKSPACE_ACTION = "workspace_action"
    OUT_OF_SCOPE = "out_of_scope"
    UNSAFE = "unsafe"
    UNCLEAR = "unclear"


class IntentAction(StrEnum):
    REPLY = "reply"
    BUILD_CONTEXT = "build_context"
    REFINE_CONTEXT = "refine_context"
    CALL_DATA_TOOLS = "call_data_tools"
    EXECUTE_ANALYSIS = "execute_analysis"
    READ_PLOT_CONTEXT = "read_plot_context"
    EXECUTE_WORKSPACE_ACTION = "execute_workspace_action"
    ASK_USER = "ask_user"
    REJECT = "reject"


_EXECUTABLE_INTENTS = {
    IntentAction.BUILD_CONTEXT: IntentKind.PLOT_CREATE,
    IntentAction.REFINE_CONTEXT: IntentKind.PLOT_REFINE,
    IntentAction.CALL_DATA_TOOLS: IntentKind.DATA_QUERY,
    IntentAction.EXECUTE_ANALYSIS: IntentKind.ANALYSIS_CREATE,
    IntentAction.READ_PLOT_CONTEXT: IntentKind.PLOT_QUERY,
    IntentAction.EXECUTE_WORKSPACE_ACTION: IntentKind.WORKSPACE_ACTION,
}
_REQUIRED_DETAILS = {
    IntentAction.BUILD_CONTEXT: "plot",
    IntentAction.EXECUTE_ANALYSIS: "analysis",
    IntentAction.REFINE_CONTEXT: "refinement",
}


def _routing_schema() -> dict[str, JsonValue]:
    """Expose the same readiness constraints to the model that the backend validates."""
    rules: list[JsonValue] = [
        {
            "if": {"properties": {"next_action": {"const": action.value}}},
            "then": {"properties": {"kind": {"const": kind.value}}},
        }
        for action, kind in _EXECUTABLE_INTENTS.items()
    ]
    rules.extend(
        {
            "if": {"properties": {"next_action": {"const": action.value}}},
            "then": {"required": [detail], "properties": {detail: {"not": {"type": "null"}}}},
        }
        for action, detail in _REQUIRED_DETAILS.items()
    )
    rules.append(
        {
            "if": {
                "properties": {
                    "next_action": {
                        "enum": [
                            action.value
                            for action in IntentAction
                            if action not in _REQUIRED_DETAILS
                        ]
                    }
                }
            },
            "then": {
                "required": ["user_reply"],
                "properties": {
                    "user_reply": {"type": "string", "minLength": 1, "pattern": r"\S"},
                },
            },
        }
    )
    rules.append(
        {
            "if": {"required": ["questions"], "properties": {"questions": {"minItems": 1}}},
            "then": {"properties": {"next_action": {"const": "ask_user"}}},
        }
    )
    return {"allOf": rules}


class ModeRequests(StrictModel):
    data: Literal["auto", "demo"] | None = Field(
        default=None,
        description="User-selected data mode. Demo requires an explicit request; otherwise null.",
    )
    generation: Literal["auto", "skill", "raw_code"] | None = None
    gallery: Literal["off", "auto", "selected"] | None = None
    controls: Literal["language", "panel", "hybrid"] | None = None


class VariableMentions(StrictModel):
    x: list[str] = Field(default_factory=list)
    y: list[str] = Field(default_factory=list)
    group: list[str] = Field(default_factory=list)
    color: list[str] = Field(default_factory=list)
    facet: list[str] = Field(default_factory=list)


class PlotIntent(StrictModel):
    goal: str
    explicit_family: str | None = None
    variable_mentions: VariableMentions = Field(default_factory=VariableMentions)
    data_hints: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)
    statistics: list[str] = Field(default_factory=list)
    appearance: list[str] = Field(default_factory=list)


class RefinementChange(StrictModel):
    target: str
    value: str | float | int | bool | None = None
    change_class: Literal["visual", "computational", "interpretation_sensitive"]


class RefinementIntent(StrictModel):
    execution_strategy: Literal["parameters", "regenerate_render", "replan_analysis"] = "parameters"
    changes: list[RefinementChange] = Field(min_length=1)
    reuse_data: bool = True


class IntentDecision(StrictModel):
    model_config = ConfigDict(json_schema_extra=_routing_schema())

    kind: IntentKind
    subtype: str
    normalized_request: str = Field(
        min_length=1,
        max_length=10_000,
        description="Self-contained request preserving the user's goal and relevant prior context.",
    )
    confidence: float = Field(ge=0, le=1)
    next_action: IntentAction
    mode_requests: ModeRequests = Field(default_factory=ModeRequests)
    plot: PlotIntent | None = None
    analysis: PlotIntent | None = None
    dataset_ids: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Relevant dataset IDs from the current data catalog. Preserve explicit selection."
        ),
    )
    refinement: RefinementIntent | None = None
    reference_image_ids: list[str] | None = Field(
        default=None,
        max_length=3,
        description=(
            "Select available references; null uses request/refinement defaults. "
            "Empty only when clearing reference guidance."
        ),
    )
    missing_context: list[str] = Field(
        default_factory=list,
        description="Blocking unknowns that cannot be resolved from the supplied context.",
    )
    decision_summary: str
    user_reply: str | None = Field(default=None, min_length=1, max_length=6_000)
    questions: list[ClarificationQuestion] = Field(
        default_factory=list,
        max_length=4,
        description="Essential unresolved decisions for ask_user after checking available context.",
    )

    @model_validator(mode="after")
    def validate_route_payload(self) -> IntentDecision:
        if self.questions and self.next_action is not IntentAction.ASK_USER:
            raise ValueError("questions require next_action=ask_user")
        required_kind = _EXECUTABLE_INTENTS.get(self.next_action)
        if required_kind is not None and self.kind is not required_kind:
            raise ValueError("next_action does not match intent kind")
        detail = _REQUIRED_DETAILS.get(self.next_action)
        if detail is not None and getattr(self, detail) is None:
            raise ValueError(f"{self.kind.value} requires {detail} details")
        if detail is None and (self.user_reply is None or not self.user_reply.strip()):
            raise ValueError("message and non-plot routes require user_reply")
        return self
