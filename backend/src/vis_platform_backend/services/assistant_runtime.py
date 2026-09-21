from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

from vis_platform_backend.contracts.activity import AgentActivity
from vis_platform_backend.contracts.assistant_turns import (
    AssistantTurnAccepted,
    AssistantTurnLinks,
    AssistantTurnOutcome,
    AssistantTurnResponse,
    AssistantTurnSnapshot,
)
from vis_platform_backend.contracts.questions import PlannerAnswerRequest, PlannerQuestions
from vis_platform_backend.domain.questions import validate_answers
from vis_platform_backend.infrastructure.database import Repository, RequestConflictError, utc_now
from vis_platform_backend.services.plot_runs import InvalidTransitionError, ResourceNotFoundError
from vis_platform_backend.services.reference_images import ReferenceImageService


class AssistantRuntime:
    def __init__(
        self,
        repository: Repository,
        handler: Callable[[str], Awaitable[AssistantTurnResponse]],
        reference_images: ReferenceImageService | None = None,
    ) -> None:
        self.repository = repository
        self.reference_images = reference_images
        self.handler = handler
        self.tasks: dict[str, asyncio.Task[None]] = {}

    def links(self, turn_id: str) -> AssistantTurnLinks:
        turn = self.repository.get_assistant_turn(turn_id)
        if turn is None:
            raise ResourceNotFoundError("Assistant request was not found")
        base = f"/api/v1/assistant-turns/{turn_id}"
        query = "?" + urlencode({"project_id": turn["project_id"]})
        return AssistantTurnLinks(
            trace=f"{base}/trace",
            status=base + query,
            events=f"{base}/events" + query,
            cancel=f"{base}/cancel" + query,
        )

    def accepted(self, turn_id: str) -> AssistantTurnAccepted:
        return AssistantTurnAccepted(turn_id=turn_id, links=self.links(turn_id))

    def activity(
        self,
        turn_id: str,
        step_id: str,
        kind: str,
        actor: str,
        label: str,
        status: str,
        summary: str | None = None,
        tool_name: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        entry = AgentActivity.model_validate(
            {
                "sequence": 1,
                "step_id": step_id,
                "kind": kind,
                "actor": actor,
                "label": label,
                "status": status,
                "summary": summary,
                "tool_name": tool_name,
                "duration_ms": duration_ms,
                "occurred_at": utc_now(),
            }
        )
        self.repository.append_assistant_activity(turn_id, entry.model_dump(mode="json"))

    async def execute(self, turn_id: str) -> AssistantTurnResponse:
        try:
            response = await self.handler(turn_id)
            response = response.model_copy(
                update={
                    "activity": [
                        AgentActivity.model_validate(entry)
                        for entry in self.repository.assistant_activity(turn_id)
                    ]
                }
            )
            waiting = response.outcome is AssistantTurnOutcome.QUESTION
            self.repository.update_assistant_execution(
                turn_id,
                status="awaiting_input" if waiting else "completed",
                response=response.model_dump(mode="json"),
                question=response.question.model_dump(mode="json") if response.question else None,
            )
            return response
        except asyncio.CancelledError:
            raise
        except Exception as error:
            state = self.repository.assistant_execution(turn_id)
            if state is not None and state["status"] == "running":
                public = {
                    "code": str(getattr(error, "code", "ASSISTANT_FAILED")),
                    "message": "The assistant request could not be completed. Please retry.",
                }
                self.activity(
                    turn_id,
                    "failure",
                    "routing",
                    "Coordinator",
                    "Request stopped",
                    "failed",
                    public["message"],
                )
                self.repository.update_assistant_execution(turn_id, status="failed", error=public)
            raise

    def start(self, turn_id: str) -> AssistantTurnAccepted:
        if turn_id not in self.tasks or self.tasks[turn_id].done():
            task = asyncio.create_task(self._background(turn_id))
            self.tasks[turn_id] = task
            task.add_done_callback(lambda completed: self._discard(turn_id, completed))
        return self.accepted(turn_id)

    async def _background(self, turn_id: str) -> None:
        try:
            await self.execute(turn_id)
        except (Exception, asyncio.CancelledError):
            return

    def _discard(self, turn_id: str, task: asyncio.Task[None]) -> None:
        if self.tasks.get(turn_id) is task:
            self.tasks.pop(turn_id, None)

    def snapshot(self, turn_id: str, project_id: str) -> AssistantTurnSnapshot:
        turn = self.repository.get_assistant_turn(turn_id)
        state = self.repository.assistant_execution(turn_id)
        if turn is None or turn["project_id"] != project_id or state is None:
            raise ResourceNotFoundError("Assistant request was not found")
        run = self.repository.get_run(turn["run_id"]) if turn["run_id"] else None
        activity = self.repository.assistant_activity(turn_id)
        return AssistantTurnSnapshot.model_validate(
            {
                "turn_id": turn_id,
                "project_id": project_id,
                "request_text": turn["request"]["request"]["text"],
                "reference_images": [
                    image.model_dump(mode="json")
                    for image in self.reference_images.resolve(
                        project_id, turn["request"]["request"].get("reference_image_ids") or []
                    )
                ]
                if self.reference_images
                else [],
                "revision": state["revision"],
                "status": state["status"],
                "activity": activity,
                "question": state["question"],
                "response": state["response"],
                "error": state["error"],
                "run_status": run["status"] if run else None,
            }
        )

    def answer(self, turn_id: str, request: PlannerAnswerRequest) -> AssistantTurnAccepted:
        snapshot = self.snapshot(turn_id, request.project_id)
        payload = request.model_dump(mode="json")
        if (
            snapshot.question is not None
            and snapshot.question.interaction_id == request.interaction_id
        ):
            validate_answers(snapshot.question, request)
        try:
            claimed = self.repository.claim_assistant_answer(turn_id, payload)
        except RequestConflictError as error:
            raise InvalidTransitionError(str(error)) from error
        if claimed:
            self.activity(
                turn_id,
                request.interaction_id,
                "question",
                "You",
                "Choices received",
                "completed",
                "Your answers are saved with this request.",
            )
            return self.start(turn_id)
        return self.accepted(turn_id)

    def _stop_activity(self, turn_id: str, status: str, summary: str) -> None:
        for entry in self.repository.assistant_activity(turn_id):
            if entry["status"] in {"running", "waiting"}:
                self.activity(
                    turn_id,
                    entry["step_id"],
                    entry["kind"],
                    entry["actor"],
                    entry["label"],
                    status,
                    summary=summary,
                    tool_name=entry.get("tool_name"),
                )

    def cancel(self, turn_id: str, project_id: str) -> AssistantTurnSnapshot:
        snapshot = self.snapshot(turn_id, project_id)
        if snapshot.status not in {"running", "awaiting_input"}:
            return snapshot
        self.activity(turn_id, "cancel", "routing", "Coordinator", "Request cancelled", "cancelled")
        self._stop_activity(turn_id, "cancelled", "Stopped at your request.")
        self.repository.update_assistant_execution(turn_id, status="cancelled")
        task = self.tasks.pop(turn_id, None)
        if task is not None:
            task.cancel()
        return self.snapshot(turn_id, project_id)

    async def events(self, turn_id: str, project_id: str, after: int = -1) -> AsyncIterator[str]:
        while True:
            snapshot = self.snapshot(turn_id, project_id)
            if snapshot.revision > after:
                after = snapshot.revision
                yield (
                    f"id: {after}\nevent: assistant.updated\ndata: {snapshot.model_dump_json()}\n\n"
                )
            if snapshot.status in {"awaiting_input", "failed", "cancelled"} or (
                snapshot.status == "completed"
                and snapshot.run_status in {None, "completed", "failed", "cancelled"}
            ):
                return
            await asyncio.sleep(0.2)

    def recover(self) -> None:
        for turn_id in self.repository.running_assistant_ids():
            self._stop_activity(turn_id, "failed", "Interrupted by a server restart.")
            self.activity(
                turn_id, "interrupted", "routing", "Coordinator", "Request interrupted", "failed"
            )
            self.repository.update_assistant_execution(
                turn_id,
                status="failed",
                error={
                    "code": "ASSISTANT_INTERRUPTED",
                    "message": "The server restarted before this request finished. Please retry.",
                },
            )

    async def shutdown(self) -> None:
        tasks = list(self.tasks.items())
        for turn_id, task in tasks:
            state = self.repository.assistant_execution(turn_id)
            if state is not None and state["status"] == "running":
                self._stop_activity(turn_id, "failed", "Interrupted when the server stopped.")
                self.repository.update_assistant_execution(
                    turn_id,
                    status="failed",
                    error={
                        "code": "ASSISTANT_INTERRUPTED",
                        "message": "The server stopped before this request finished. Please retry.",
                    },
                )
            task.cancel()
        if tasks:
            await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
        self.tasks.clear()

    def answers_context(self, turn_id: str) -> tuple[dict[str, Any], ...]:
        state = self.repository.assistant_execution(turn_id)
        entries = []
        for batch in state["answer_batches"] if state else []:
            questions = PlannerQuestions.model_validate(batch["question"])
            request = PlannerAnswerRequest.model_validate(batch["answer"])
            for answer in request.answers:
                question = next(
                    q for q in questions.questions if q.question_id == answer.question_id
                )
                entries.append(
                    {
                        "question": question.prompt,
                        "choices": [
                            c.label for c in question.choices if c.choice_id in answer.choice_ids
                        ],
                        "free_text": answer.free_text,
                    }
                )
        return tuple(entries)
