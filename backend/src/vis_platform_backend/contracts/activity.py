from datetime import datetime
from typing import Literal

from pydantic import Field

from .common import StrictModel


class AgentActivity(StrictModel):
    sequence: int = Field(ge=1)
    step_id: str
    kind: Literal["agent", "tool", "routing", "question", "render"]
    actor: str
    label: str
    status: Literal["running", "completed", "waiting", "blocked", "failed", "cancelled"]
    summary: str | None = None
    tool_name: str | None = None
    occurred_at: datetime
    duration_ms: int | None = Field(default=None, ge=0)
