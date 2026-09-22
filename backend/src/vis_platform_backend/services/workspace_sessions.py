"""Workspace conversations, rebuilt from their persisted assistant turns and runs."""

from __future__ import annotations

from vis_platform_backend.contracts.plot_runs import PlotRunSnapshot
from vis_platform_backend.contracts.workspace_sessions import (
    AnsweredQuestions,
    CreateWorkspaceSession,
    WorkspaceSession,
    WorkspaceSessionDocument,
    WorkspaceSessionList,
    WorkspaceSessionTurn,
)
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.infrastructure.database import Repository
from vis_platform_backend.infrastructure.workspace_sessions import WorkspaceSessionRepository
from vis_platform_backend.services.assistant_runtime import AssistantRuntime
from vis_platform_backend.services.plot_runs import PlotRunCoordinator, ResourceNotFoundError


class WorkspaceSessionService:
    def __init__(
        self,
        store: WorkspaceSessionRepository,
        repository: Repository,
        runtime: AssistantRuntime,
        coordinator: PlotRunCoordinator,
    ) -> None:
        self.store, self.repository, self.runtime, self.coordinator = (
            store,
            repository,
            runtime,
            coordinator,
        )

    def check_project(self, project_id: str) -> None:
        if not self.repository.project_exists(project_id):
            raise DataError("The project was not found.", "NOT_FOUND", 404)

    def create(self, project_id: str, request: CreateWorkspaceSession) -> WorkspaceSession:
        self.check_project(project_id)
        session_id = self.store.create(project_id, request.title, request.request_id)
        return WorkspaceSession.model_validate(self.store.get(project_id, session_id))

    def list_sessions(self, project_id: str, offset: int) -> WorkspaceSessionList:
        self.check_project(project_id)
        items, total = self.store.list_sessions(project_id, offset)
        return WorkspaceSessionList.model_validate(
            {"sessions": items, "total": total, "offset": offset}
        )

    def get(self, project_id: str, session_id: str) -> WorkspaceSessionDocument:
        record = self.store.get(project_id, session_id)
        turns = []
        for turn_id in self.store.turn_ids(session_id):
            try:
                snapshot = self.runtime.snapshot(turn_id, project_id)
            except ResourceNotFoundError:
                # A turn is linked a moment before its execution record exists.
                continue
            turn = self.repository.get_assistant_turn(turn_id)
            state = self.repository.assistant_execution(turn_id)
            assert turn is not None and state is not None
            turns.append(
                WorkspaceSessionTurn(
                    turn=snapshot,
                    links=self.runtime.links(turn_id),
                    answers=[
                        AnsweredQuestions.model_validate(batch) for batch in state["answer_batches"]
                    ],
                    run=self.coordinator.get_run(turn["run_id"]) if turn["run_id"] else None,
                )
            )
        return WorkspaceSessionDocument.model_validate(
            {**record, "turns": turns, "figure": self._figure(project_id, turns)}
        )

    def _figure(self, project_id: str, turns: list[WorkspaceSessionTurn]) -> PlotRunSnapshot | None:
        for turn in reversed(turns):
            result = turn.run.result if turn.run else None
            if result is None:
                continue
            run_id = self.repository.current_run_id(project_id, result.plot_id)
            return self.coordinator.get_run(run_id) if run_id else turn.run
        return None
