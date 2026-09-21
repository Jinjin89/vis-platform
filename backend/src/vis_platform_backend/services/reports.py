from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from vis_platform_backend.agents.data_agent import DataAgent
from vis_platform_backend.contracts.assistant_turns import AssistantTurnRequest
from vis_platform_backend.contracts.parameters import ParameterUpdateRequest
from vis_platform_backend.contracts.plot_runs import PlotResultSummary
from vis_platform_backend.contracts.report_content import ReportContentInput, upgrade_report
from vis_platform_backend.contracts.report_messages import ReportMessage
from vis_platform_backend.contracts.report_operations import ReportOperationsRequest
from vis_platform_backend.contracts.reports import (
    CreateReportRequest,
    ReportContent,
    ReportDocument,
    ReportEdit,
    ReportFigureBlock,
    ReportGenerateRequest,
    ReportTextBlock,
    SaveReportRequest,
)
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.data.service import DatasetService
from vis_platform_backend.infrastructure.database import Repository, utc_now
from vis_platform_backend.infrastructure.report_messages import ReportMessageStore
from vis_platform_backend.infrastructure.reports import ACTIVE, ReportRepository
from vis_platform_backend.infrastructure.shared_figures import publish_version, selected_version
from vis_platform_backend.services.assistant_turns import AssistantTurnService
from vis_platform_backend.services.plot_runs import PlotRunCoordinator
from vis_platform_backend.services.reference_images import ReferenceImageService


class ReportService:
    def __init__(
        self,
        store: ReportRepository,
        repository: Repository,
        data: DatasetService,
        assistant: AssistantTurnService,
        coordinator: PlotRunCoordinator,
        data_agent: DataAgent,
        images: ReferenceImageService,
    ) -> None:
        self.store, self.repository, self.data = store, repository, data
        self.assistant, self.coordinator, self.data_agent, self.images = (
            assistant,
            coordinator,
            data_agent,
            images,
        )
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.message_store: ReportMessageStore | None = None

    def check_project(self, project_id: str) -> None:
        self.data.check_project(project_id)

    def validate(self, project_id: str, content: ReportContent) -> None:
        self.check_project(project_id)
        for ref in content.datasets:
            dataset = self.data.get(project_id, ref.dataset_id, ref.revision_id)
            if ref.revision_id is None:
                ref.revision_id = dataset.revision_id
        for topic in content.sections:
            for block in topic.blocks:
                if isinstance(block, ReportFigureBlock):
                    if block.version_id:
                        figure = self.figure(project_id, block.version_id)
                        if block.follow_plot_id:
                            if figure.plot_id != block.follow_plot_id:
                                raise DataError(
                                    "The linked figure does not match its version.",
                                    "INVALID_REFERENCE",
                                    422,
                                )
                            if not self.linked_version(project_id, block.follow_plot_id):
                                raise DataError(
                                    "Link the shared figure before inserting it.",
                                    "INVALID_REFERENCE",
                                    422,
                                )
                    if block.image_id:
                        self.images.get(project_id, block.image_id)
                if isinstance(block, ReportTextBlock):
                    for version_id in block.evidence_version_ids:
                        self.figure(project_id, version_id)

    def figure(self, project_id: str, version_id: str) -> PlotResultSummary:
        record = self.repository.result_for_version(version_id, project_id)
        if record is None:
            raise DataError("The figure version was not found in this project.", "NOT_FOUND", 404)
        return PlotResultSummary.model_validate(record)

    def linked_version(self, project_id: str, plot_id: str) -> str | None:
        with self.store.lock:
            return selected_version(self.store.connection, project_id, plot_id)

    def link_figure(
        self,
        project_id: str,
        plot_id: str,
        version_id: str,
        expected: str | None = None,
        *,
        initialize: bool = True,
    ) -> PlotResultSummary:
        with self.store.lock, self.store.connection:
            selected = publish_version(
                self.store.connection,
                project_id,
                plot_id,
                version_id,
                expected,
                initialize=initialize,
            )
        return self.figure(project_id, selected)

    def normalize(self, project_id: str, content: ReportContentInput) -> ReportContent:
        def description(version_id: str) -> str:
            figure = self.figure(project_id, version_id)
            return figure.caption or figure.preview.description

        return upgrade_report(content, description)

    def operations(
        self, project_id: str, report_id: str, request: ReportOperationsRequest
    ) -> ReportDocument:
        self.store.apply_operations(
            project_id, report_id, request, lambda content: self.validate(project_id, content)
        )
        return self.get(project_id, report_id)

    def create(self, project_id: str, request: CreateReportRequest) -> ReportDocument:
        content = self.normalize(project_id, request.content)
        self.validate(project_id, content)
        report_id = self.store.create(
            project_id, content.model_dump(mode="json"), request.request_id
        )
        return self.get(project_id, report_id)

    def save(self, project_id: str, report_id: str, request: SaveReportRequest) -> ReportDocument:
        self.store.get(project_id, report_id)
        content = self.normalize(project_id, request.content)
        self.validate(project_id, content)
        self.store.save(
            project_id,
            report_id,
            request.base_revision,
            content.model_dump(mode="json"),
            request.summary,
        )
        return self.get(project_id, report_id)

    def get(self, project_id: str, report_id: str) -> ReportDocument:
        with self.store.lock:
            record = self.store.get(project_id, report_id)
            saved_edits = self.store.edits(report_id)
            messages = self.message_store.list_states(report_id) if self.message_store else []
        content = ReportContent.model_validate(record["content"])
        figures, images, bindings = {}, {}, {}
        for topic in content.sections:
            for block in topic.blocks:
                if isinstance(block, ReportFigureBlock):
                    if block.version_id:
                        resolved = (
                            self.linked_version(project_id, block.follow_plot_id)
                            if block.follow_plot_id
                            else None
                        ) or block.version_id
                        figures[block.version_id] = self.figure(project_id, block.version_id)
                        figures[resolved] = self.figure(project_id, resolved)
                        bindings[block.id] = resolved
                    elif block.image_id:
                        images[block.image_id] = self.images.get(project_id, block.image_id)
        edits = []
        for record_edit in saved_edits:
            state = ReportEdit.model_validate(record_edit["state"])
            if state.status in ACTIVE:
                if state.assistant:
                    state.assistant_state = self.assistant.runtime.snapshot(
                        state.assistant.turn_id, project_id
                    )
                if state.run:
                    state.run_state = self.coordinator.get_run(state.run.run_id)
            edits.append(state)
        stale = []
        current_results = {
            result.result_id
            for version in bindings.values()
            for result in figures[version].analysis_results
        }
        for topic in content.sections:
            for block in topic.blocks:
                if isinstance(block, ReportTextBlock) and block.evidence_version_ids:
                    cited = {
                        result.result_id
                        for version in block.evidence_version_ids
                        for result in self.figure(project_id, version).analysis_results
                    }
                    if cited and not cited.issubset(current_results):
                        stale.append(block.id)
        return ReportDocument(
            report_id=report_id,
            project_id=project_id,
            title=content.title,
            revision=record["revision"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
            content=content,
            datasets=[
                self.data.get(project_id, ref.dataset_id, ref.revision_id)
                for ref in content.datasets
            ],
            figure_bindings=bindings,
            figures=figures,
            images=images,
            edits=edits,
            messages=[ReportMessage.model_validate(item) for item in messages],
            stale_text_ids=stale,
        )

    def generate(
        self,
        project_id: str,
        report_id: str,
        request: ReportGenerateRequest,
        *,
        message_id: str | None = None,
    ) -> ReportDocument:
        document = self.get(project_id, report_id)
        # An idempotent retry can arrive after its result has already changed the report.
        for previous in self.store.edits(report_id):
            if previous["request"]["request_id"] == request.request_id:
                if previous["request"] != request.model_dump(mode="json"):
                    raise DataError(
                        "This edit key was used for other instructions.", "CONFLICT", 409
                    )
                return document
        topic = next((t for t in document.content.sections if t.id == request.section_id), None)
        if topic is None:
            raise DataError("Choose a topic for the new content.", "NOT_FOUND", 404)
        block = next((b for b in topic.blocks if b.id == request.block_id), None)
        if request.block_id and (
            block is None or (request.kind != "discussion" and block.type != request.kind)
        ):
            raise DataError(
                "The selected block does not match this edit.", "INVALID_REPORT_EDIT", 422
            )
        if request.parameter_changes and not (
            isinstance(block, ReportFigureBlock) and block.version_id
        ):
            raise DataError(
                "Parameter changes need an editable R figure.", "INVALID_REPORT_EDIT", 422
            )
        dataset_ids = [ref.dataset_id for ref in document.content.datasets]
        source = (
            document.figures[document.figure_bindings.get(block.id, block.version_id)]
            if isinstance(block, ReportFigureBlock) and block.version_id
            else None
        )
        if source:
            dataset_ids = sorted(
                self.data.dataset_ids_for_objects(project_id, source.input_objects)
            )
        if request.kind == "figure" and not dataset_ids and source is None:
            raise DataError(
                "Add a dataset to this report before creating a figure.",
                "REPORT_DATA_REQUIRED",
                422,
            )
        if request.kind == "figure" and not source:
            for ref in document.content.datasets:
                current = self.data.get(project_id, ref.dataset_id)
                if ref.revision_id and current.revision_id != ref.revision_id:
                    raise DataError(
                        "The source data changed. Refresh the report's dataset selection "
                        "before creating a figure.",
                        "REPORT_DATA_CHANGED",
                        409,
                    )
        edit_id = "report_edit_" + uuid4().hex
        output_id = (
            block.id
            if block and not request.insert_new
            else request.output_block_id or "block_" + uuid4().hex
        )
        if (not block or request.insert_new) and any(
            output_id == item.id for section in document.content.sections for item in section.blocks
        ):
            raise DataError("The new block ID already exists.", "INVALID_REPORT_OPERATION", 422)
        state = ReportEdit(
            edit_id=edit_id,
            section_id=topic.id,
            block_id=request.block_id,
            output_block_id=output_id,
            kind=request.kind,
            prompt=request.prompt,
            status="running",
            message_id=message_id,
            created_at=utc_now(),
        )
        topic_figures = [
            document.figures[document.figure_bindings.get(b.id, b.version_id)]
            for b in topic.blocks
            if isinstance(b, ReportFigureBlock) and b.version_id
        ]
        available_evidence = list(
            dict.fromkeys(
                [figure.version_id for figure in topic_figures]
                + [
                    document.figures[
                        document.figure_bindings.get(item.id, item.version_id)
                    ].version_id
                    for section in document.content.sections[:16]
                    for item in section.blocks
                    if isinstance(item, ReportFigureBlock) and item.version_id
                ]
            )
        )
        evidence_ids = available_evidence[:100]
        context = {
            "evidence_version_ids": evidence_ids,
            "project_id": project_id,
            "document_kind": document.content.kind,
            "report_title": document.title,
            "topic_title": topic.title,
            "block": block.model_dump(mode="json") if block else None,
            "dataset_ids": dataset_ids,
            "datasets": [d.model_dump(mode="json") for d in document.datasets],
            "figures": [f.model_dump(mode="json") for f in topic_figures],
            "source": source.model_dump(mode="json") if source else None,
            "section_text": [b.body for b in topic.blocks if isinstance(b, ReportTextBlock)],
            "report_context": {
                "complete": len(document.content.sections) <= 16 and len(available_evidence) <= 100,
                "sections": [
                    {
                        "title": section.title,
                        "authored_text": [
                            item.body[:2000]
                            for item in section.blocks
                            if isinstance(item, ReportTextBlock)
                        ],
                        "figures": [
                            {
                                "version_id": document.figures[
                                    document.figure_bindings.get(item.id, item.version_id)
                                ].version_id,
                                "title": document.figures[
                                    document.figure_bindings.get(item.id, item.version_id)
                                ].title,
                                "caption": document.figures[
                                    document.figure_bindings.get(item.id, item.version_id)
                                ].caption,
                                "results": [
                                    result.model_dump(mode="json")
                                    for result in document.figures[
                                        document.figure_bindings.get(item.id, item.version_id)
                                    ].analysis_results
                                ],
                            }
                            for item in section.blocks
                            if isinstance(item, ReportFigureBlock)
                            and item.version_id
                            and document.figures[
                                document.figure_bindings.get(item.id, item.version_id)
                            ].version_id
                            in evidence_ids
                        ],
                    }
                    for section in document.content.sections[:16]
                ],
            },
            "conversation": [
                {
                    "request": item["state"]["prompt"][:2000],
                    "response": (item["state"].get("response_text") or "")[:3000],
                    "kind": item["state"]["kind"],
                }
                for item in self.store.edits(report_id)
                if item["state"]["section_id"] == topic.id
                and item["state"]["status"] == "completed"
            ][-6:],
        }
        saved_id = self.store.create_edit(
            project_id,
            report_id,
            request.model_dump(mode="json"),
            context,
            state.model_dump(mode="json"),
        )
        self._start(saved_id)
        return self.get(project_id, report_id)

    def _start(self, edit_id: str) -> None:
        if edit_id not in self.tasks:
            task = asyncio.create_task(self._execute(edit_id))
            self.tasks[edit_id] = task
            task.add_done_callback(lambda completed: self.tasks.pop(edit_id, None))

    async def _execute(self, edit_id: str) -> None:
        try:
            record = self.store.get_edit(edit_id)
            context, request = record["context"], record["request"]
            if request["kind"] in {"text", "discussion"}:
                answer = await self.data_agent.answer(
                    {
                        "document_kind": context.get("document_kind", "report"),
                        "purpose": "report_discussion"
                        if request["kind"] == "discussion"
                        else "report_text",
                        "request": request["prompt"],
                        "report_title": context["report_title"],
                        "topic": context["topic_title"],
                        "existing_text": (context["block"] or {}).get("body", ""),
                        "section_text": context.get("section_text", []),
                        "report_context": context.get("report_context", {}),
                        "selected_figure": context.get("source"),
                        "selected_content": context.get("block"),
                        "conversation": context.get("conversation", []),
                        "datasets": context["datasets"],
                        "figures": context["figures"],
                        "results": [
                            result
                            for figure in context["figures"]
                            for result in figure["analysis_results"]
                        ],
                    }
                )
                if request["kind"] == "discussion":
                    reply = answer.message
                    if answer.questions:
                        reply += "\n\n" + "\n".join(q.prompt for q in answer.questions)
                    # Discussion is saved in the conversation without publishing a report block.
                    if self.store.get_edit(edit_id)["state"]["status"] in ACTIVE:
                        self.store.update_edit(
                            edit_id, {"status": "completed", "response_text": reply}
                        )
                    return
                if answer.questions:
                    raise DataError(answer.message, "REPORT_TEXT_NEEDS_CONTEXT", 422)
                block = ReportTextBlock(
                    id=record["state"]["output_block_id"],
                    body=answer.message,
                    evidence_version_ids=context.get(
                        "evidence_version_ids",
                        [figure["version_id"] for figure in context["figures"]],
                    ),
                )
                self.store.finish_edit(
                    edit_id,
                    context["project_id"],
                    block.model_dump(mode="json"),
                    response_text=answer.message,
                )
                return
            await self._start_figure(record)
            while True:
                record = self.store.get_edit(edit_id)
                state = record["state"]
                if state["status"] not in ACTIVE:
                    return
                if state.get("run"):
                    run = self.coordinator.get_run(state["run"]["run_id"])
                    if run.status == "completed":
                        if run.result is None:
                            raise DataError(
                                "The request produced no figure. "
                                "Try a more specific plotting instruction.",
                                "NO_FIGURE",
                                422,
                            )
                        original = context.get("block") or {}
                        linked = not request["insert_new"] and (
                            original.get("follow_plot_id") or not original
                        )
                        shared_update = None
                        if linked:
                            shared_update = (
                                run.result.plot_id,
                                run.result.version_id,
                                context["source"]["version_id"] if context.get("source") else None,
                            )
                        block_figure = ReportFigureBlock(
                            id=state["output_block_id"],
                            version_id=run.result.version_id,
                            follow_plot_id=run.result.plot_id if linked else None,
                            caption="",
                        )
                        self.store.finish_edit(
                            edit_id,
                            context["project_id"],
                            block_figure.model_dump(mode="json"),
                            shared_update=shared_update,
                            response_text=(
                                "Updated the figure."
                                if request.get("block_id") and not request["insert_new"]
                                else "Added a new figure to the section."
                            ),
                        )
                        return
                    if run.status in {"failed", "cancelled"}:
                        self.store.update_edit(
                            edit_id,
                            {
                                "status": str(run.status),
                                "error": run.failure.message
                                if run.failure
                                else "Request cancelled.",
                            },
                        )
                        return
                    self._status(edit_id, state, str(run.status))
                else:
                    snapshot = self.assistant.runtime.snapshot(
                        state["assistant"]["turn_id"], context["project_id"]
                    )
                    if snapshot.response and snapshot.response.plot_run:
                        self.store.update_edit(
                            edit_id,
                            {
                                "run": snapshot.response.plot_run.model_dump(mode="json"),
                                "status": "running",
                            },
                        )
                    elif snapshot.status in {"failed", "cancelled", "completed"}:
                        message = (
                            snapshot.error.message
                            if snapshot.error
                            else (snapshot.response.message if snapshot.response else None)
                        )
                        self.store.update_edit(
                            edit_id,
                            {
                                "status": "cancelled"
                                if snapshot.status == "cancelled"
                                else "failed",
                                "error": message or "No figure was created.",
                            },
                        )
                        return
                    else:
                        self._status(edit_id, state, snapshot.status)
                await asyncio.sleep(0.4)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            state = self.store.get_edit(edit_id)["state"]
            if state["status"] in ACTIVE:
                self.store.update_edit(
                    edit_id,
                    {
                        "status": "failed",
                        "error": str(error)
                        if isinstance(error, DataError)
                        else "This report edit could not be completed. Please retry.",
                    },
                )

    def _status(self, edit_id: str, state: dict[str, Any], status: str) -> None:
        resolved = status if status in {"awaiting_input", "awaiting_approval"} else "running"
        if state["status"] != resolved:
            self.store.update_edit(edit_id, {"status": resolved})

    async def _start_figure(self, record: dict[str, Any]) -> None:
        state, request, context = record["state"], record["request"], record["context"]
        if state.get("run") or state.get("assistant"):
            return
        source = context["source"]
        if source and not request["prompt"].strip():
            run = self.coordinator.update_parameters(
                source["plot_id"],
                ParameterUpdateRequest(
                    project_id=context["project_id"],
                    base_version_id=source["version_id"],
                    changes=request["parameter_changes"],
                ),
                idempotency_key=state["edit_id"],
            )
            self.store.update_edit(state["edit_id"], {"run": run.model_dump(mode="json")})
            return
        text = "Refine the selected plot" if source else "Create a plot from the selected dataset"
        text += f": {request['prompt']}\nReport topic: {context['topic_title']}."
        block = context["block"] or {}
        turn = self.assistant.start_turn(
            AssistantTurnRequest.model_validate(
                {
                    "project_id": context["project_id"],
                    "request": {
                        "text": text,
                        **(
                            {"reference_image_ids": [block["image_id"]]}
                            if block.get("image_id")
                            else {}
                        ),
                    },
                    "data_scope": (
                        {"mode": "selected", "bundle_ids": context["dataset_ids"]}
                        if context["dataset_ids"]
                        else {"mode": "auto"}
                    ),
                    "base_version_id": source["version_id"] if source else None,
                    "parameter_changes": request["parameter_changes"],
                }
            ),
            idempotency_key=state["edit_id"],
        )
        self.store.update_edit(state["edit_id"], {"assistant": turn.model_dump(mode="json")})

    async def cancel(self, project_id: str, report_id: str, edit_id: str) -> ReportDocument:
        self.store.get(project_id, report_id)
        edit = self.store.get_edit(edit_id)
        if edit["report_id"] != report_id:
            raise DataError("Report edit was not found.", "NOT_FOUND", 404)
        state = edit["state"]
        if state["status"] in ACTIVE:
            self.store.update_edit(edit_id, {"status": "cancelled", "error": "Request cancelled."})
            if state.get("run"):
                self.coordinator.cancel_run(state["run"]["run_id"])
            elif state.get("assistant"):
                self.assistant.runtime.cancel(state["assistant"]["turn_id"], project_id)
            if task := self.tasks.get(edit_id):
                task.cancel()
        else:
            self.store.update_edit(edit_id, {"dismissed": True})
        return self.get(project_id, report_id)

    def recover(self) -> None:
        for edit in self.store.edits():
            if edit["request"]["kind"] in {"text", "discussion"}:
                self.store.update_edit(
                    edit["edit_id"],
                    {
                        "status": "failed",
                        "error": (
                            "Text generation was interrupted. "
                            "Your previous content is preserved; retry the edit."
                        ),
                    },
                )
            else:
                self._start(edit["edit_id"])

    async def shutdown(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
