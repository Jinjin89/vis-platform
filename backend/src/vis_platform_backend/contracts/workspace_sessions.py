"""Workspace conversations: separate threads of assistant turns within one project."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .assistant_turns import AssistantTurnLinks, AssistantTurnSnapshot
from .common import SCHEMA_VERSION, Identifier, StrictModel
from .plot_runs import PlotRunSnapshot
from .questions import PlannerAnswerRequest, PlannerQuestions


class CreateWorkspaceSession(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    request_id: Identifier
    title: str = Field(min_length=1, max_length=200)


class WorkspaceSession(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    session_id: str
    project_id: str
    title: str
    created_at: datetime
    updated_at: datetime = Field(description="When the conversation last received a message.")


class WorkspaceSessionList(StrictModel):
    sessions: list[WorkspaceSession]
    total: int
    offset: int


class AnsweredQuestions(StrictModel):
    question: PlannerQuestions
    answer: PlannerAnswerRequest


class WorkspaceSessionTurn(StrictModel):
    turn: AssistantTurnSnapshot
    links: AssistantTurnLinks
    answers: list[AnsweredQuestions] = Field(
        description="Questions the assistant asked during this turn, with the answers given."
    )
    run: PlotRunSnapshot | None = Field(description="The plot or analysis run the turn started.")


class WorkspaceSessionDocument(WorkspaceSession):
    turns: list[WorkspaceSessionTurn] = Field(description="Oldest first.")
    figure: PlotRunSnapshot | None = Field(
        description=(
            "The current version of the latest figure this conversation created, "
            "including later parameter changes and restores."
        )
    )
