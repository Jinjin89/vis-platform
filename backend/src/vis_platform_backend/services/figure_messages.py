"""Run figure assistant messages: plan, apply edits, plot through the shared agent, arrange."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter

from vis_platform_backend.agents.figure_planner import FigurePlanner
from vis_platform_backend.agents.structured import StructuredAgentError
from vis_platform_backend.contracts.assistant_turns import (
    AssistantTurnAccepted,
    AssistantTurnRequest,
)
from vis_platform_backend.contracts.figure_arrangement import ArrangeRequest
from vis_platform_backend.contracts.figure_composition_content import (
    FigureCompositionContent,
    FigurePanel,
    ImagePanelContent,
    PlotPanelContent,
    SlotPanelContent,
)
from vis_platform_backend.contracts.figure_composition_operations import (
    AddPanel,
    FigureOperationsRequest,
)
from vis_platform_backend.contracts.figure_compositions import FigureCompositionDocument
from vis_platform_backend.contracts.figure_messages import (
    FigureAddStep,
    FigureArrangeStep,
    FigureEditStep,
    FigureMessage,
    FigureMessageAnswer,
    FigureMessageRequest,
    FigurePlanStep,
    FigurePlotStatus,
    FigurePlotStep,
    FigureSlotsStep,
)
from vis_platform_backend.contracts.parameters import ParameterUpdateRequest
from vis_platform_backend.contracts.plot_runs import PlotResultSummary, PlotRunAccepted, RunStatus
from vis_platform_backend.contracts.questions import PlannerAnswerRequest, PlannerQuestions
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.data.service import DatasetService
from vis_platform_backend.domain.figure_compositions import (
    MM_PER_INCH,
    apply_figure_operations,
    image_natural_size,
    reading_order,
)
from vis_platform_backend.domain.figure_layout import append_below
from vis_platform_backend.domain.parameters import InvalidParameterError, resolve_parameters
from vis_platform_backend.domain.questions import validate_answers
from vis_platform_backend.infrastructure.database import utc_now
from vis_platform_backend.infrastructure.figure_messages import ACTIVE, FigureMessageStore
from vis_platform_backend.services.assistant_turns import AssistantTurnService
from vis_platform_backend.services.figure_arrangement import FigureArrangementService, renderable
from vis_platform_backend.services.figure_compositions import FigureCompositionService
from vis_platform_backend.services.plot_runs import PlotRunCoordinator

STEPS = TypeAdapter(list[FigurePlanStep])
MAX_REVIEWS = 2
GUTTER_MM = 4
POLL_SECONDS = 0.4
# A fitted plot this far from its slot's size is rendered again at the slot size.
FIT_TOLERANCE_MM = 0.5


class FigureMessageRuntime:
    def __init__(
        self,
        compositions: FigureCompositionService,
        arrangement: FigureArrangementService,
        assistant: AssistantTurnService,
        coordinator: PlotRunCoordinator,
        data: DatasetService,
        planner: FigurePlanner,
    ) -> None:
        self.compositions, self.arrangement = compositions, arrangement
        self.assistant, self.coordinator, self.data, self.planner = (
            assistant,
            coordinator,
            data,
            planner,
        )
        self.figures = compositions.store
        self.store = FigureMessageStore(self.figures)
        compositions.conversation = self.messages
        self.tasks: dict[str, asyncio.Task[None]] = {}

    # Public API

    def submit(
        self, project_id: str, composition_id: str, request: FigureMessageRequest
    ) -> FigureCompositionDocument:
        content: FigureCompositionContent = self.figures.get(project_id, composition_id)["content"]
        panels = {panel.id: panel for panel in content.panels}
        # A repeated request returns its message, even after its slots were filled.
        fill = [] if self.store.submitted(composition_id, request.request_id) else request.fill
        for panel_id in fill:
            slot = panels.get(panel_id)
            if slot is None or not isinstance(slot.content, SlotPanelContent):
                raise DataError(
                    f"Panel “{panel_id}” is not an empty slot.", "INVALID_FIGURE_OPERATION", 422
                )
            if not slot.content.prompt.strip():
                raise DataError(
                    f"Describe the plot for panel “{panel_id}” before creating it.",
                    "INVALID_FIGURE_OPERATION",
                    422,
                )
        if request.refine and not self.store.submitted(composition_id, request.request_id):
            self._check_refinement(project_id, panels.get(request.refine.panel_id), request)
        state = FigureMessage(
            message_id="figure_message_" + uuid4().hex,
            prompt=request.message,
            selection=request.selection,
            status="running",
            created_at=utc_now(),
        )
        message_id = self.store.create(
            project_id,
            composition_id,
            request.model_dump(mode="json"),
            state.model_dump(mode="json"),
        )
        if self.store.get(message_id)["state"]["status"] == "running":
            self.start(message_id)
        return self.compositions.get(project_id, composition_id)

    def _check_refinement(
        self, project_id: str, panel: FigurePanel | None, request: FigureMessageRequest
    ) -> None:
        assert request.refine is not None
        if panel is None or not isinstance(panel.content, PlotPanelContent):
            raise DataError(
                f"Panel “{request.refine.panel_id}” is not a plot to refine.",
                "INVALID_FIGURE_OPERATION",
                422,
            )
        if not request.refine.parameter_changes:
            return
        figure = self.compositions.figure(project_id, panel.content.version_id)
        if not figure.parameter_updates_available:
            raise DataError("This plot has no editable parameters.", "INVALID_PARAMETERS", 422)
        try:
            resolve_parameters(
                figure.controls, request.refine.parameter_changes, require_change=False
            )
        except InvalidParameterError as error:
            raise DataError(str(error), "INVALID_PARAMETERS", 422) from error

    def answer(
        self,
        project_id: str,
        composition_id: str,
        message_id: str,
        answer: FigureMessageAnswer,
    ) -> FigureCompositionDocument:
        with self.store.lock, self.store.connection:
            record = self._owned(project_id, composition_id, message_id)
            question = record["state"].get("question")
            if (
                record["state"]["status"] != "awaiting_input"
                or not question
                or question["interaction_id"] != answer.interaction_id
            ):
                raise DataError(
                    "This question is no longer waiting for an answer.", "FIGURE_CONFLICT", 409
                )
            validate_answers(
                PlannerQuestions.model_validate(question),
                PlannerAnswerRequest(project_id=project_id, **answer.model_dump()),
            )
            self.store.update(
                message_id,
                {"status": "running", "phase": "planning", "question": None},
                {
                    "answers": [
                        *record["execution"]["answers"],
                        {"question": question, "answer": answer.model_dump(mode="json")},
                    ],
                    "steps": None,
                },
            )
        self.start(message_id)
        return self.compositions.get(project_id, composition_id)

    async def cancel(
        self, project_id: str, composition_id: str, message_id: str
    ) -> FigureCompositionDocument:
        record = self._owned(project_id, composition_id, message_id)
        if record["state"]["status"] in ACTIVE:
            self.store.update(message_id, {"status": "cancelled", "phase": "finished"})
            if task := self.tasks.get(message_id):
                task.cancel()
            plot = record["execution"].get("plot")
            if plot and plot.get("run"):
                self.coordinator.cancel_run(plot["run"]["run_id"])
            elif plot:
                self.assistant.runtime.cancel(plot["assistant"]["turn_id"], project_id)
        return self.compositions.get(project_id, composition_id)

    def messages(self, project_id: str, composition_id: str) -> list[FigureMessage]:
        """The conversation, with live states for a plot step that is still running."""
        messages = []
        for record in self.store.list_messages(composition_id):
            message = FigureMessage.model_validate(record["state"])
            plot = record["execution"].get("plot")
            if plot and message.status in ACTIVE:
                # A parameter-only refinement runs without an assistant turn.
                assistant = (
                    AssistantTurnAccepted.model_validate(plot["assistant"])
                    if plot.get("assistant")
                    else None
                )
                run = PlotRunAccepted.model_validate(plot["run"]) if plot.get("run") else None
                message.active_step = FigurePlotStatus(
                    panel_id=plot["panel_id"],
                    block_id=plot["panel_id"] if plot["refine"] else None,
                    prompt=plot["prompt"],
                    status=message.status,
                    assistant=assistant,
                    assistant_state=(
                        self.assistant.runtime.snapshot(assistant.turn_id, project_id)
                        if assistant
                        else None
                    ),
                    run=run,
                    run_state=self.coordinator.get_run(run.run_id) if run else None,
                )
            messages.append(message)
        return messages

    def recover(self) -> None:
        for record in self.store.active_messages():
            # A planner question waits for the user; everything else resumes.
            if not (
                record["state"]["status"] == "awaiting_input" and record["state"].get("question")
            ):
                self.start(record["message_id"])

    async def shutdown(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def start(self, message_id: str) -> None:
        if message_id not in self.tasks or self.tasks[message_id].done():
            task = asyncio.create_task(self.execute(message_id))
            self.tasks[message_id] = task
            task.add_done_callback(lambda done: self.tasks.pop(message_id, None))

    # Planning

    def context(
        self, document: FigureCompositionDocument, record: dict[str, Any], *, review: bool = False
    ) -> dict[str, Any]:
        content = document.content
        selection = record["request"].get("selection") or {}
        panels = []
        for panel in content.panels:
            resolved = document.panels[panel.id]
            item: dict[str, Any] = {
                "id": panel.id,
                "label": resolved.label,
                "locked": panel.locked,
                "scale": panel.scale,
                "frame_mm": {
                    key: round(value, 1) for key, value in resolved.frame.model_dump().items()
                },
                "natural_size_mm": [
                    round(resolved.natural_width_mm, 1),
                    round(resolved.natural_height_mm, 1),
                ],
                "legend": content.legend.entries.get(panel.id),
            }
            if isinstance(panel.content, PlotPanelContent):
                figure = document.figures[panel.content.version_id]
                item.update(
                    type="plot",
                    version_id=figure.version_id,
                    title=figure.title,
                    description=figure.caption or figure.preview.description,
                    data=figure.data_summary,
                    renderable=renderable(figure),
                )
            elif isinstance(panel.content, SlotPanelContent):
                item.update(type="slot", prompt=panel.content.prompt)
            else:
                image = document.images[panel.content.image_id]
                item.update(type="image", image_id=image.image_id, name=image.name)
            panels.append(item)
        used = {
            panel.content.version_id
            for panel in content.panels
            if isinstance(panel.content, PlotPanelContent)
        }
        saved, _ = self.compositions.repository.list_figure_results(document.project_id, 0)
        history = [
            {
                "user": item.prompt,
                "assistant": (item.response_text or item.error or "")[:2000],
                "completed_actions": item.completed_actions,
            }
            for item in document.messages
            if item.message_id != record["message_id"]
        ][-8:]
        return {
            "message": record["request"]["message"],
            "selection_hint": [
                panel_id
                for panel_id in selection.get("panel_ids", [])
                if panel_id in document.panels
            ],
            "figure": {
                "title": content.title,
                "page": content.page.model_dump(),
                "page_height_mm": document.page_height_mm,
                "printable_width_mm": content.page.width_mm - 2 * content.page.margin_mm,
                "labels": content.labels.model_dump(),
                "min_font_pt": content.min_font_pt,
                "legend_title": content.legend.title,
            },
            "panels": panels,
            "checks": [check.model_dump() for check in document.checks],
            "available_plots": [
                {
                    "version_id": figure["version_id"],
                    "title": figure.get("title"),
                    "description": figure.get("caption") or figure["preview"]["description"],
                }
                for figure in saved
                if figure["version_id"] not in used
            ],
            # New plots use the figure's datasets; without any, the plot agent finds project data.
            "data_source": "figure" if document.datasets else "project",
            "datasets": [
                {
                    "dataset_id": dataset.dataset_id,
                    "name": dataset.name,
                    "description": dataset.description,
                }
                for dataset in (
                    document.datasets or self.data.list_datasets(document.project_id).datasets
                )
            ],
            "conversation": history,
            "clarification_answers": record["execution"]["answers"],
            "review": review,
            "completed_actions": record["state"]["completed_actions"] if review else [],
        }

    async def _prepare(self, record: dict[str, Any]) -> bool:
        message_id = record["message_id"]
        if refine := record["request"].get("refine"):
            # Refining a named panel is a direct instruction, like filling a slot.
            content = self.figures.get(record["project_id"], record["composition_id"])["content"]
            panel = next((p for p in content.panels if p.id == refine["panel_id"]), None)
            if panel is None or not isinstance(panel.content, PlotPanelContent):
                self.store.update(
                    message_id,
                    {
                        "status": "failed",
                        "phase": "finished",
                        "error": "The panel was removed or replaced before it could be refined.",
                    },
                )
                return False
            step = FigurePlotStep(
                kind="plot",
                panel_id=panel.id,
                instructions=refine["instructions"].strip() or "Apply the parameter changes.",
            )
            self.store.update(
                message_id,
                execution={"steps": STEPS.dump_python([step], mode="json"), "step": 0},
            )
            return True
        if fill := record["request"].get("fill"):
            # Filling named slots is a direct instruction; no planning is needed.
            content = self.figures.get(record["project_id"], record["composition_id"])["content"]
            prompts = {
                panel.id: panel.content.prompt
                for panel in content.panels
                if isinstance(panel.content, SlotPanelContent)
            }
            # A slot filled or removed since the request was sent is skipped.
            queued = [panel_id for panel_id in fill if prompts.get(panel_id, "").strip()]
            steps: list[FigurePlanStep] = [
                FigurePlotStep(kind="plot", panel_id=panel_id, instructions=prompts[panel_id])
                for panel_id in queued
            ]
            self.store.update(
                message_id,
                {"panels": [{"panel_id": panel_id, "status": "waiting"} for panel_id in queued]},
                {"steps": STEPS.dump_python(steps, mode="json"), "step": 0},
            )
            return True
        document = self.compositions.get(record["project_id"], record["composition_id"])
        plan = await self.planner.plan(self.context(document, record))
        if self.store.get(message_id)["state"]["status"] not in ACTIVE:
            return False
        if plan.action == "reply":
            self.store.update(
                message_id,
                {"status": "completed", "phase": "finished", "response_text": plan.message},
            )
            return False
        if plan.action == "ask_user":
            questions = PlannerQuestions(questions=plan.questions)
            self.store.update(
                message_id,
                {
                    "status": "awaiting_input",
                    "response_text": plan.message,
                    "question": questions.model_dump(mode="json"),
                },
            )
            return False
        self.store.update(
            message_id,
            {"response_text": plan.message},
            {"steps": STEPS.dump_python(plan.steps, mode="json"), "step": 0},
        )
        return True

    async def _review(self, record: dict[str, Any]) -> bool:
        """After layout changes, let the planner fix remaining warnings (bounded rounds)."""
        execution, message_id = record["execution"], record["message_id"]
        steps = STEPS.validate_python(execution["steps"])
        if (
            execution["reviews"] >= MAX_REVIEWS
            or record["request"].get("fill")
            or record["request"].get("refine")
            or not any(
                isinstance(
                    step, FigurePlotStep | FigureAddStep | FigureArrangeStep | FigureSlotsStep
                )
                for step in steps
            )
        ):
            return False
        document = self.compositions.get(record["project_id"], record["composition_id"])
        # New plots are reviewed once so the legend can describe results, not intentions.
        # Empty slots are left to the user, who can revise the description and retry.
        built = execution["reviews"] == 0 and any(
            isinstance(step, FigureSlotsStep) for step in steps
        )
        if not built and not any(
            check.severity == "warning" and check.code != "empty_slot" for check in document.checks
        ):
            return False
        self.store.update(message_id, {"phase": "reviewing"})
        plan = await self.planner.plan(self.context(document, record, review=True))
        reviews = execution["reviews"] + 1
        if plan.action != "execute":
            self.store.update(message_id, execution={"reviews": reviews})
            return False
        self.store.update(
            message_id,
            execution={
                "steps": [*execution["steps"], *STEPS.dump_python(plan.steps, mode="json")],
                "reviews": reviews,
            },
        )
        return True

    # Execution

    async def execute(self, message_id: str) -> None:
        try:
            record = self.store.get(message_id)
            if record["execution"]["steps"] is None and not await self._prepare(record):
                return
            while True:
                record = self.store.get(message_id)
                if record["state"]["status"] not in ACTIVE:
                    return
                execution = record["execution"]
                steps = STEPS.validate_python(execution["steps"])
                index = execution["step"]
                if index >= len(steps):
                    if await self._review(record):
                        continue
                    self.store.update(
                        message_id,
                        {"status": "completed", "phase": "finished", "active_step": None},
                    )
                    return
                step, key = steps[index], f"{message_id}:{index}"
                note: str | None
                if isinstance(step, FigureEditStep):
                    self._edit(record, step, key)
                    note = step.summary
                elif isinstance(step, FigureAddStep):
                    self._add(record, step, key)
                    note = f"Added panel “{step.panel_id}”."
                elif isinstance(step, FigureArrangeStep):
                    note = await self._arrange(record, step, key)
                    if note is None:
                        return
                elif isinstance(step, FigureSlotsStep):
                    fills = await self._slots(record, step, key)
                    if fills is None:
                        return
                    # The new slots are filled next, one at a time, in reading order.
                    record = self.store.get(message_id)
                    self.store.update(
                        message_id,
                        {
                            "completed_actions": [
                                *record["state"]["completed_actions"],
                                step.summary,
                            ],
                            "panels": [
                                *record["state"].get("panels", []),
                                *(
                                    {"panel_id": fill.panel_id, "status": "waiting"}
                                    for fill in fills
                                ),
                            ],
                        },
                        {
                            "steps": [
                                *execution["steps"][: index + 1],
                                *STEPS.dump_python(list[FigurePlanStep](fills), mode="json"),
                                *execution["steps"][index + 1 :],
                            ],
                            "step": index + 1,
                        },
                    )
                    continue
                else:
                    note = await self._plot(record, step, key)
                    if note is None:
                        return
                record = self.store.get(message_id)
                self.store.update(
                    message_id,
                    {"completed_actions": [*record["state"]["completed_actions"], note]},
                    {"step": index + 1},
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if self.store.get(message_id)["state"]["status"] in ACTIVE:
                self.store.update(
                    message_id,
                    {
                        "status": "failed",
                        "phase": "finished",
                        "error": str(error)
                        if isinstance(error, DataError | StructuredAgentError)
                        else "The figure request could not be completed. Please retry.",
                    },
                )

    def _revision(self, record: dict[str, Any]) -> int:
        return int(self.figures.get(record["project_id"], record["composition_id"])["revision"])

    def _apply(self, record: dict[str, Any], key: str, operations: list[Any], summary: str) -> None:
        # A step that already committed (before a restart) is not applied twice.
        if self.figures.operation_applied(record["composition_id"], key):
            return
        self.figures.apply_operations(
            record["project_id"],
            record["composition_id"],
            FigureOperationsRequest(
                request_id=key,
                base_revision=self._revision(record),
                operations=operations,
                summary=summary,
            ),
            lambda content: self.compositions.validate(record["project_id"], content),
        )

    def _edit(self, record: dict[str, Any], step: FigureEditStep, key: str) -> None:
        self.store.update(record["message_id"], {"phase": "editing"})
        self._apply(record, key, list(step.operations), step.summary)

    def _natural_size(
        self, project_id: str, content: PlotPanelContent | ImagePanelContent | SlotPanelContent
    ) -> tuple[float, float]:
        if isinstance(content, PlotPanelContent):
            return self.compositions.natural_size(
                self.compositions.figure(project_id, content.version_id)
            )
        if isinstance(content, SlotPanelContent):
            return content.width_mm, content.height_mm
        image = self.compositions.images.get(project_id, content.image_id)
        return image_natural_size(image.width, image.height)

    def _place(
        self, record: dict[str, Any], content: FigureCompositionContent, panel: FigurePanel
    ) -> FigurePanel:
        """Give a new panel a provisional place below the existing content."""
        project_id = record["project_id"]
        frames = self.compositions.resolve(project_id, content).frames
        x, y, scale = append_below(
            frames,
            self._natural_size(project_id, panel.content),
            page_width=content.page.width_mm,
            page_height=content.page.height_mm,
            margin=content.page.margin_mm,
            gutter=GUTTER_MM,
        )
        return panel.model_copy(update={"x_mm": round(x, 2), "y_mm": round(y, 2), "scale": scale})

    def _add(self, record: dict[str, Any], step: FigureAddStep, key: str) -> None:
        self.store.update(record["message_id"], {"phase": "editing"})
        content = self.figures.get(record["project_id"], record["composition_id"])["content"]
        source: PlotPanelContent | ImagePanelContent = (
            PlotPanelContent(version_id=step.version_id)
            if step.version_id
            else ImagePanelContent(image_id=step.image_id or "")
        )
        panel = self._place(
            record, content, FigurePanel(id=step.panel_id, content=source, x_mm=0, y_mm=0)
        )
        self._apply(record, key, [AddPanel(op="add_panel", panel=panel)], "Added a panel")

    async def _arrange(
        self, record: dict[str, Any], step: FigureArrangeStep, key: str
    ) -> str | None:
        message_id = record["message_id"]
        self.store.update(message_id, {"phase": "arranging"})
        if not self.figures.operation_applied(record["composition_id"], key):
            self.arrangement.arrange(
                record["project_id"],
                record["composition_id"],
                ArrangeRequest(
                    request_id=key,
                    base_revision=self._revision(record),
                    arrangement=step.arrangement,
                    gutter_mm=step.gutter_mm,
                    render=step.render,
                    summary=step.summary,
                ),
            )
        jobs = await self._renders(record, key)
        if jobs is None:
            return None
        failed = [job for job in jobs if job["status"] != "completed"]
        if failed:
            return f"{step.summary} ({len(failed)} of {len(jobs)} plots kept their scaled size.)"
        return step.summary

    async def _renders(self, record: dict[str, Any], key: str) -> list[dict[str, Any]] | None:
        """Wait for the renders a step started; None when the message stopped meanwhile."""
        while True:
            jobs = [
                job
                for job in self.figures.jobs(record["composition_id"], limit=100)
                if job["request_key"].startswith(key + ":")
            ]
            if all(job["status"] != "running" for job in jobs):
                return jobs
            if self.store.get(record["message_id"])["state"]["status"] not in ACTIVE:
                return None
            await asyncio.sleep(POLL_SECONDS)

    async def _slots(
        self, record: dict[str, Any], step: FigureSlotsStep, key: str
    ) -> list[FigurePlotStep] | None:
        """Lay out the planned panels, then return one fill per slot in reading order."""
        message_id, project_id = record["message_id"], record["project_id"]
        self.store.update(message_id, {"phase": "editing"})
        added = key + ":slots"
        if not self.figures.operation_applied(record["composition_id"], added):
            content = self.figures.get(project_id, record["composition_id"])["content"]
            page = content.page
            operations = []
            for slot in step.slots:
                # Provisional size only; the arrangement below decides the final one.
                width = min((page.width_mm - 2 * page.margin_mm) / 2, 90.0)
                size = SlotPanelContent(
                    prompt=slot.prompt,
                    width_mm=round(width, 2),
                    height_mm=round(max(5.0, width / slot.aspect), 2),
                )
                panel = self._place(
                    record, content, FigurePanel(id=slot.panel_id, content=size, x_mm=0, y_mm=0)
                )
                operation = AddPanel(op="add_panel", panel=panel)
                content = apply_figure_operations(content, [operation])
                operations.append(operation)
            self._apply(record, added, operations, f"Planned {len(operations)} panels")
        arrangement = FigureArrangeStep(
            kind="arrange",
            arrangement=step.arrangement,
            render=True,
            gutter_mm=step.gutter_mm,
            summary=step.summary,
        )
        if await self._arrange(record, arrangement, key) is None:
            return None
        document = self.compositions.get(project_id, record["composition_id"])
        frames = {panel_id: panel.frame for panel_id, panel in document.panels.items()}
        prompts = {slot.panel_id: slot.prompt for slot in step.slots}
        return [
            FigurePlotStep(kind="plot", panel_id=panel.id, instructions=prompts[panel.id])
            for panel in reading_order(document.content.panels, frames)
            if panel.id in prompts and isinstance(panel.content, SlotPanelContent)
        ]

    async def _plot(self, record: dict[str, Any], step: FigurePlotStep, key: str) -> str | None:
        message_id, project_id = record["message_id"], record["project_id"]
        plot = record["execution"].get("plot") or self._start_plot(record, step, key)
        try:
            result = await self._plot_result(record, plot)
        except DataError as error:
            if not plot.get("slot"):
                raise
            # A slot that cannot be made keeps its place and description for a retry.
            self._progress(message_id, step.panel_id, "failed", str(error))
            self.store.update(message_id, {"status": "running"}, {"plot": None})
            return f"Panel “{step.panel_id}” could not be created: {error}"
        if result is None:
            return None
        if not plot.get("placed"):
            placed = self._use(record, step, result, slot=bool(plot.get("slot")))
            plot = {**plot, "placed": True, "kept": placed}
            self.store.update(message_id, {"status": "running"}, {"plot": plot})
        if not plot.get("slot"):
            self.store.update(message_id, execution={"plot": None})
            return (
                f"Refined panel “{step.panel_id}”."
                if plot["refine"]
                else f"Created panel “{step.panel_id}”."
            )
        if not plot["kept"]:
            self._progress(message_id, step.panel_id, "failed", "The slot was removed.")
            self.store.update(message_id, execution={"plot": None})
            return (
                f"Panel “{step.panel_id}” was removed before its plot finished; "
                "the plot is kept with your saved plots."
            )
        width, height = plot["size_mm"]
        natural = self.compositions.natural_size(result)
        content = self.figures.get(project_id, record["composition_id"])["content"]
        current = next((p.content for p in content.panels if p.id == step.panel_id), None)
        if (
            renderable(result)
            and isinstance(current, PlotPanelContent)
            and current.version_id == result.version_id
            and (
                abs(natural[0] - width) > FIT_TOLERANCE_MM
                or abs(natural[1] - height) > FIT_TOLERANCE_MM
            )
        ):
            # Rendered again at the slot's size, so its text prints as designed.
            self.arrangement.start_renders(
                project_id, record["composition_id"], key + ":fit", {step.panel_id: (width, height)}
            )
            if await self._renders(record, key + ":fit") is None:
                return None
        self._progress(message_id, step.panel_id, "completed")
        self.store.update(message_id, execution={"plot": None})
        return f"Created panel “{step.panel_id}”."

    def _start_plot(self, record: dict[str, Any], step: FigurePlotStep, key: str) -> dict[str, Any]:
        """Start the shared plot agent for a slot, a new panel, or a panel to refine."""
        message_id, project_id = record["message_id"], record["project_id"]
        content = self.figures.get(project_id, record["composition_id"])["content"]
        panel = next((p for p in content.panels if p.id == step.panel_id), None)
        slot = panel is not None and isinstance(panel.content, SlotPanelContent)
        base = (
            panel.content.version_id
            if panel and isinstance(panel.content, PlotPanelContent)
            else None
        )
        images = (
            [panel.content.image_id]
            if panel and isinstance(panel.content, ImagePanelContent)
            else []
        )
        size: tuple[float, float] | None = None
        if panel is not None and slot:
            frame = self.compositions.resolve(project_id, content).frames[panel.id]
            size = (frame.width_mm, frame.height_mm)
        elif step.width_mm and step.height_mm:
            size = (step.width_mm, step.height_mm)
        text = ("Refine the selected plot: " if base else "Create a plot: ") + step.instructions
        if size:
            # Plots are at least 1 in; a smaller slot shows its plot scaled down.
            factor = max(1.0, MM_PER_INCH / size[0], MM_PER_INCH / size[1])
            text += (
                f"\nRender it at {size[0] * factor / MM_PER_INCH:.2f} × "
                f"{size[1] * factor / MM_PER_INCH:.2f} inches for its figure panel."
            )
        text += f"\nFigure: {content.title}."
        refine = record["request"].get("refine") or {}
        changes = (
            refine["parameter_changes"] if base and refine.get("panel_id") == step.panel_id else {}
        )
        plot = {
            "panel_id": step.panel_id,
            "prompt": step.instructions,
            "refine": panel is not None and not slot,
            "slot": slot,
            "size_mm": list(size) if slot and size else None,
            "assistant": None,
            "run": None,
        }
        dataset_ids = [dataset.dataset_id for dataset in content.datasets]
        if base:
            source = self.compositions.figure(project_id, base)
            dataset_ids = sorted(
                self.data.dataset_ids_for_objects(project_id, source.input_objects)
            )
            if changes and not refine["instructions"].strip():
                # Parameter edits alone re-render the plot without the assistant.
                run = self.coordinator.update_parameters(
                    source.plot_id,
                    ParameterUpdateRequest(
                        project_id=project_id, base_version_id=base, changes=changes
                    ),
                    idempotency_key=key,
                )
                plot["run"] = run.model_dump(mode="json")
                self.store.update(message_id, {"phase": "plotting"}, {"plot": plot})
                return plot
        turn = self.assistant.start_turn(
            AssistantTurnRequest.model_validate(
                {
                    "project_id": project_id,
                    "request": {
                        "text": text,
                        **({"reference_image_ids": images} if images else {}),
                    },
                    "data_scope": (
                        {"mode": "selected", "bundle_ids": dataset_ids}
                        if dataset_ids
                        else {"mode": "auto"}
                    ),
                    "base_version_id": base,
                    "parameter_changes": changes,
                }
            ),
            idempotency_key=key,
        )
        plot["assistant"] = turn.model_dump(mode="json")
        self.store.update(message_id, {"phase": "plotting"}, {"plot": plot})
        if slot:
            self._progress(message_id, step.panel_id, "plotting")
        return plot

    async def _plot_result(
        self, record: dict[str, Any], plot: dict[str, Any]
    ) -> PlotResultSummary | None:
        """Follow the assistant turn and its plot run; None when the message stopped."""
        message_id, project_id = record["message_id"], record["project_id"]
        while True:
            if self.store.get(message_id)["state"]["status"] not in ACTIVE:
                return None
            if plot["run"]:
                run = self.coordinator.get_run(plot["run"]["run_id"])
                if run.status is RunStatus.COMPLETED:
                    if run.result is None:
                        raise DataError(
                            "The request produced no figure. Try a more specific instruction.",
                            "NO_FIGURE",
                            422,
                        )
                    return run.result
                if run.status in {RunStatus.FAILED, RunStatus.CANCELLED}:
                    raise DataError(
                        run.failure.message if run.failure else "The plot was cancelled.",
                        "FIGURE_PLOT_FAILED",
                        422,
                    )
                self._wait(message_id, run.status.value)
            else:
                snapshot = self.assistant.runtime.snapshot(plot["assistant"]["turn_id"], project_id)
                if snapshot.response and snapshot.response.plot_run:
                    plot["run"] = snapshot.response.plot_run.model_dump(mode="json")
                    self.store.update(message_id, execution={"plot": plot})
                    continue
                if snapshot.status in {"failed", "cancelled", "completed"}:
                    raise DataError(
                        (snapshot.error.message if snapshot.error else None)
                        or (snapshot.response.message if snapshot.response else None)
                        or "No plot was created.",
                        "FIGURE_PLOT_FAILED",
                        422,
                    )
                self._wait(message_id, snapshot.status)
            await asyncio.sleep(POLL_SECONDS)

    def _wait(self, message_id: str, status: str) -> None:
        resolved = status if status in {"awaiting_input", "awaiting_approval"} else "running"
        if self.store.get(message_id)["state"]["status"] != resolved:
            self.store.update(message_id, {"status": resolved})

    def _progress(
        self, message_id: str, panel_id: str, status: str, error: str | None = None
    ) -> None:
        panels = self.store.get(message_id)["state"].get("panels", [])
        self.store.update(
            message_id,
            {
                "panels": [
                    {**item, "status": status, "error": error}
                    if item["panel_id"] == panel_id
                    else item
                    for item in panels
                ]
            },
        )

    def _use(
        self, record: dict[str, Any], step: FigurePlotStep, result: PlotResultSummary, *, slot: bool
    ) -> bool:
        """Put a finished plot into its panel; False when its slot no longer exists.

        A slot's plot is fitted inside the slot. A refined plot keeps the panel's width, and a
        plot for a new panel is placed below the existing content.
        """
        project_id = record["project_id"]
        width, height = self.compositions.natural_size(result)
        plot = PlotPanelContent(version_id=result.version_id)

        def update(content: FigureCompositionContent) -> FigureCompositionContent | None:
            panels = list(content.panels)
            index = next((i for i, p in enumerate(panels) if p.id == step.panel_id), None)
            if slot and (index is None or not isinstance(panels[index].content, SlotPanelContent)):
                return None
            if index is None:
                panels.append(
                    self._place(
                        record, content, FigurePanel(id=step.panel_id, content=plot, x_mm=0, y_mm=0)
                    )
                )
            else:
                old = panels[index]
                frame = self.compositions.resolve(project_id, content).frames[old.id]
                page = content.page
                scale = min(
                    frame.width_mm / width,
                    (frame.height_mm if slot else page.height_mm - old.y_mm) / height,
                    (page.width_mm - old.x_mm) / width,
                )
                panels[index] = old.model_copy(
                    update={"content": plot, "scale": max(0.05, int(scale * 1000) / 1000)}
                )
            return FigureCompositionContent.model_validate(
                {**content.model_dump(mode="json"), "panels": [p.model_dump() for p in panels]}
            )

        return self.figures.change(
            project_id,
            record["composition_id"],
            update,
            f"Placed the plot for panel “{step.panel_id}”",
            lambda content: self.compositions.validate(project_id, content),
        )

    def _owned(self, project_id: str, composition_id: str, message_id: str) -> dict[str, Any]:
        self.figures.get(project_id, composition_id)
        record = self.store.get(message_id)
        if record["composition_id"] != composition_id:
            raise DataError("Figure message was not found in this figure.", "NOT_FOUND", 404)
        return record
