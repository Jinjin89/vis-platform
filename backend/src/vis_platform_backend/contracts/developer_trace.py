from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, JsonValue

from .common import SCHEMA_VERSION, StrictModel


class TraceKind(StrEnum):
    LLM_TURN = "llm_turn"
    INTENT_DECISION = "intent_decision"
    ROUTING = "routing"
    STAGE = "stage"
    TOOL_CALL = "tool_call"
    R_EXECUTION = "r_execution"
    ERROR = "error"


class TraceStatus(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class DeveloperTraceEntry(StrictModel):
    trace_id: str
    sequence: int = Field(ge=1)
    kind: TraceKind
    actor: str
    name: str
    status: TraceStatus
    occurred_at: datetime
    duration_ms: int | None = Field(default=None, ge=0)
    input: dict[str, JsonValue] | None = None
    output: dict[str, JsonValue] | None = None
    error: dict[str, JsonValue] | None = None


class DeveloperTraceResponse(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    turn_id: str
    run_id: str | None = None
    entries: list[DeveloperTraceEntry]
    reasoning_content_exposed: Literal[False] = False
