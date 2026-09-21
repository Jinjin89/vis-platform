from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from vis_platform_backend.agents.report_planner import ReportPlanner
from vis_platform_backend.agents.structured import StructuredAgentError
from vis_platform_backend.contracts.questions import PlannerAnswerRequest, PlannerQuestions
from vis_platform_backend.contracts.report_messages import (
    ReportMessage,
    ReportMessageAnswer,
    ReportMessageRequest,
    ReportPlan,
)
from vis_platform_backend.contracts.report_operations import ReportOperationsRequest
from vis_platform_backend.contracts.reports import ReportDocument, ReportGenerateRequest
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.domain.questions import validate_answers
from vis_platform_backend.infrastructure.database import utc_now
from vis_platform_backend.infrastructure.report_messages import ReportMessageStore
from vis_platform_backend.infrastructure.reports import ACTIVE
from vis_platform_backend.services.reports import ReportService


class ReportMessageRuntime:
    def __init__(self, reports: ReportService, planner: ReportPlanner) -> None:
        self.reports, self.planner = reports, planner
        self.store = ReportMessageStore(reports.store)
        reports.message_store = self.store
        self.tasks: dict[str, asyncio.Task[None]] = {}

    def submit(
        self, project_id: str, report_id: str, request: ReportMessageRequest
    ) -> ReportDocument:
        self.reports.store.get(project_id, report_id)
        state = ReportMessage(
            message_id="report_message_" + uuid4().hex,
            prompt=request.message,
            selection=request.selection,
            status="running",
            created_at=utc_now(),
        )
        message_id = self.store.create(
            project_id, report_id, request.model_dump(mode="json"), state.model_dump(mode="json")
        )
        record = self.store.get(message_id)
        if record["state"]["status"] == "running":
            self.start(message_id)
        return self.reports.get(project_id, report_id)

    def start(self, message_id: str) -> None:
        if message_id not in self.tasks or self.tasks[message_id].done():
            task = asyncio.create_task(self.execute(message_id))
            self.tasks[message_id] = task

            def discard(done: asyncio.Task[None]) -> None:
                if self.tasks.get(message_id) is done:
                    self.tasks.pop(message_id, None)

            task.add_done_callback(discard)

    def context(
        self, document: ReportDocument, record: dict[str, Any], expanded: list[str]
    ) -> dict[str, Any]:
        selection = record["request"].get("selection")
        selected_ids = {selection.get("section_id")} if selection else set()
        if selection and selection.get("block_id"):
            owner = next(
                (
                    section
                    for section in document.content.sections
                    if any(block.id == selection["block_id"] for block in section.blocks)
                ),
                None,
            )
            if owner:
                selected_ids.add(owner.id)
                selection = {"section_id": owner.id, "block_id": selection["block_id"]}
            else:
                selection = None
        elif selection and selection.get("section_id") not in {
            section.id for section in document.content.sections
        }:
            selection = None
        outline = []
        figure_number = 0
        for section in document.content.sections:
            items = []
            full = section.id in expanded or section.id in selected_ids
            for block in section.blocks:
                descriptor: dict[str, Any] = {"id": block.id, "type": block.type}
                if block.type == "text":
                    limit = 2500 if full else 450
                    descriptor.update(text=block.body[:limit], excerpted=len(block.body) > limit)
                elif block.type == "figure":
                    figure_number += 1
                    descriptor["figure_number"] = figure_number
                    descriptor["version_id"] = block.version_id
                    descriptor["image_id"] = block.image_id
                    if block.version_id:
                        figure = document.figures[
                            document.figure_bindings.get(block.id, block.version_id)
                        ]
                        descriptor.update(
                            version_id=figure.version_id,
                            follow_plot_id=block.follow_plot_id,
                            title=figure.title,
                            description=figure.caption or figure.preview.description,
                            result_ids=[result.result_id for result in figure.analysis_results],
                        )
                    else:
                        descriptor["description"] = block.caption
                elif block.type == "table":
                    descriptor.update(
                        title=block.title, columns=block.columns, source=block.source_description
                    )
                items.append(descriptor)
            outline.append(
                {
                    "id": section.id,
                    "title": section.title,
                    "slide_settings": section.slide.model_dump() if section.slide else None,
                    "level": section.level,
                    "parent_id": section.parent_id,
                    "blocks": items if full else items[:12],
                    "block_count": len(items),
                    "complete": full or len(items) <= 12,
                }
            )
        saved, total = self.reports.repository.list_figure_results(document.project_id, 0)
        history = [
            {
                "user": message.prompt,
                "assistant": (message.response_text or message.error or "")[:3000],
                "completed_actions": message.completed_actions,
            }
            for message in document.messages
            if message.message_id != record["message_id"]
        ][-8:]
        return {
            "message": record["request"]["message"],
            "selection_hint": selection,
            "document_kind": document.content.kind,
            "presentation": document.content.presentation.model_dump()
            if document.content.presentation
            else None,
            "report_title": document.title,
            "report_revision": document.revision,
            "outline": outline,
            "datasets": [
                {
                    "dataset_id": dataset.dataset_id,
                    "name": dataset.name,
                    "description": dataset.description,
                }
                for dataset in document.datasets
            ],
            "available_figures": [
                {
                    "version_id": figure["version_id"],
                    "title": figure.get("title"),
                    "description": figure.get("caption") or figure["preview"]["description"],
                }
                for figure in saved
            ],
            "available_figures_complete": total <= len(saved),
            "conversation": history,
            "clarification_answers": record["execution"]["answers"],
        }

    async def prepare(self, record: dict[str, Any], project_id: str) -> bool:
        expanded: list[str] = []
        # Re-read if another editor changes the report during planning.
        for _ in range(4):
            document = self.reports.get(project_id, record["report_id"])
            plan = await self.planner.plan(self.context(document, record, expanded))
            if self.store.get(record["message_id"])["state"]["status"] != "running":
                return False
            if plan.action == "inspect":
                valid = {section.id for section in document.content.sections}
                if not set(plan.inspect_section_ids).issubset(valid):
                    raise DataError(
                        "The planner requested an unavailable section.", "INVALID_REPORT_PLAN", 422
                    )
                expanded = list(dict.fromkeys([*expanded, *plan.inspect_section_ids]))
                continue
            if (
                self.reports.store.get(project_id, record["report_id"])["revision"]
                != document.revision
            ):
                continue
            if plan.action == "reply":
                self.store.update(
                    record["message_id"],
                    {"status": "completed", "phase": "finished", "response_text": plan.message},
                )
                return False
            if plan.action == "ask_user":
                questions = PlannerQuestions(questions=plan.questions)
                self.store.update(
                    record["message_id"],
                    {
                        "status": "awaiting_input",
                        "response_text": plan.message,
                        "question": questions.model_dump(mode="json"),
                    },
                )
                return False
            self.store.update(
                record["message_id"],
                execution={
                    "plan": plan.model_dump(mode="json"),
                    "revision": document.revision,
                    "step": 0,
                },
            )
            return True
        raise DataError(
            "The report changed repeatedly while planning. Please send the request again.",
            "REPORT_CONFLICT",
            409,
        )

    async def execute(self, message_id: str) -> None:
        try:
            record = self.store.get(message_id)
            project_id = str(record["project_id"])
            if record["execution"]["plan"] is None and not await self.prepare(record, project_id):
                return
            while True:
                record = self.store.get(message_id)
                if record["state"]["status"] not in ACTIVE:
                    return
                execution, state = record["execution"], record["state"]
                plan = ReportPlan.model_validate(execution["plan"])
                index = execution["step"]
                if index >= len(plan.steps):
                    self.store.update(
                        message_id,
                        {
                            "status": "completed",
                            "phase": "finished",
                            "active_edit_id": None,
                            "response_text": state.get("response_text")
                            or "\n".join(state["completed_actions"])
                            or "Updated the report.",
                        },
                    )
                    return
                step = plan.steps[index]
                step_key = f"{message_id}:{index}"
                if step.kind == "document":
                    self.store.update(message_id, {"phase": "applying", "status": "running"})
                    operation_request = ReportOperationsRequest(
                        request_id=step_key,
                        base_revision=execution["revision"],
                        operations=step.operations,
                        summary=step.summary,
                    )
                    revision = self.reports.store.apply_operations(
                        project_id,
                        record["report_id"],
                        operation_request,
                        lambda content: self.reports.validate(project_id, content),
                    )
                    self.store.update(
                        message_id,
                        {"completed_actions": [*state["completed_actions"], step.summary]},
                        {"step": index + 1, "revision": revision, "step_request": None},
                    )
                    continue
                if execution["step_request"] is None:
                    payload = ReportGenerateRequest(
                        request_id=step_key,
                        base_revision=execution["revision"],
                        section_id=step.section_id,
                        kind="figure" if step.kind == "plot" else "text",
                        block_id=step.block_id,
                        output_block_id=step.output_id,
                        insert_new=step.insert_new,
                        prompt=step.instructions,
                        before_block_id=step.before_id,
                        after_block_id=step.after_id,
                    )
                    self.store.update(
                        message_id, execution={"step_request": payload.model_dump(mode="json")}
                    )
                else:
                    payload = ReportGenerateRequest.model_validate(execution["step_request"])
                self.reports.generate(
                    project_id, record["report_id"], payload, message_id=message_id
                )
                edit = self.reports.store.edit_for_request(record["report_id"], step_key)
                self.store.update(
                    message_id, {"phase": "generating", "active_edit_id": edit["edit_id"]}
                )
                while True:
                    if self.store.get(message_id)["state"]["status"] not in ACTIVE:
                        return
                    current = self.reports.store.get_edit(edit["edit_id"])["state"]
                    if current["status"] in {"completed", "failed", "cancelled"}:
                        break
                    self.store.update(message_id, {"status": current["status"]})
                    await asyncio.sleep(0.4)
                if current["status"] != "completed":
                    self.store.update(
                        message_id,
                        {
                            "status": current["status"],
                            "phase": "finished",
                            "error": current.get("error")
                            or "The content request did not complete.",
                            "active_edit_id": None,
                        },
                    )
                    return
                updated = self.reports.get(project_id, record["report_id"])
                section = next(
                    section for section in updated.content.sections if section.id == step.section_id
                )
                action = (
                    (
                        "Refined the figure"
                        if step.block_id and not step.insert_new
                        else "Added a figure"
                    )
                    if step.kind == "plot"
                    else (
                        "Revised the paragraph"
                        if step.block_id and not step.insert_new
                        else "Added a paragraph"
                    )
                )
                note = f"{action} in “{section.title}”."
                reply = current.get("response_text") if step.kind == "write" else note
                self.store.update(
                    message_id,
                    {
                        "status": "running",
                        "active_edit_id": None,
                        "completed_actions": [*state["completed_actions"], note],
                        "response_text": "\n\n".join(
                            filter(None, [state.get("response_text"), reply])
                        ),
                    },
                    {"step": index + 1, "revision": updated.revision, "step_request": None},
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            record = self.store.get(message_id)
            if record["state"]["status"] in ACTIVE:
                self.store.update(
                    message_id,
                    {
                        "status": "failed",
                        "phase": "finished",
                        "error": str(error)
                        if isinstance(error, (DataError, StructuredAgentError))
                        else "The report request could not be completed. Please retry.",
                    },
                )

    def owned(self, project_id: str, report_id: str, message_id: str) -> dict[str, Any]:
        self.reports.store.get(project_id, report_id)
        record = self.store.get(message_id)
        if record["report_id"] != report_id:
            raise DataError("Report message was not found in this report.", "NOT_FOUND", 404)
        return record

    def answer(
        self, project_id: str, report_id: str, message_id: str, answer: ReportMessageAnswer
    ) -> ReportDocument:
        with self.store.lock, self.store.connection:
            record = self.owned(project_id, report_id, message_id)
            question = record["state"].get("question")
            if (
                record["state"]["status"] != "awaiting_input"
                or not question
                or question["interaction_id"] != answer.interaction_id
            ):
                raise DataError(
                    "This question is no longer waiting for an answer.", "REPORT_CONFLICT", 409
                )
            parsed = PlannerQuestions.model_validate(question)
            validate_answers(
                parsed, PlannerAnswerRequest(project_id=project_id, **answer.model_dump())
            )
            answers = [
                *record["execution"]["answers"],
                {"question": question, "answer": answer.model_dump(mode="json")},
            ]
            self.store.update(
                message_id,
                {"status": "running", "question": None, "response_text": None},
                {"answers": answers, "plan": None},
            )
        self.start(message_id)
        return self.reports.get(project_id, report_id)

    async def cancel(self, project_id: str, report_id: str, message_id: str) -> ReportDocument:
        record = self.owned(project_id, report_id, message_id)
        if record["state"]["status"] in ACTIVE:
            self.store.update(message_id, {"status": "cancelled", "phase": "finished"})
            if record["state"].get("active_edit_id"):
                await self.reports.cancel(project_id, report_id, record["state"]["active_edit_id"])
            if task := self.tasks.get(message_id):
                task.cancel()
        return self.reports.get(project_id, report_id)

    def recover(self) -> None:
        for record in self.store.list_messages():
            if record["state"]["status"] != "awaiting_input" or not record["state"].get("question"):
                self.start(record["message_id"])

    async def shutdown(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
