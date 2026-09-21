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
)
from vis_platform_backend.contracts.plot_runs import PlotResultSummary, PlotRunAccepted, RunStatus
from vis_platform_backend.contracts.questions import PlannerAnswerRequest, PlannerQuestions
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.data.service import DatasetService
from vis_platform_backend.domain.figure_compositions import MM_PER_INCH, image_natural_size
from vis_platform_backend.domain.figure_layout import append_below
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
                assistant = AssistantTurnAccepted.model_validate(plot["assistant"])
                run = PlotRunAccepted.model_validate(plot["run"]) if plot.get("run") else None
                message.active_step = FigurePlotStatus(
                    panel_id=plot["panel_id"],
                    block_id=plot["panel_id"] if plot["refine"] else None,
                    prompt=plot["prompt"],
                    status=message.status,
                    assistant=assistant,
                    assistant_state=self.assistant.runtime.snapshot(assistant.turn_id, project_id),
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
            "datasets": [
                {
                    "dataset_id": dataset.dataset_id,
                    "name": dataset.name,
                    "description": dataset.description,
                }
                for dataset in self.data.list_datasets(document.project_id).datasets
            ],
            "conversation": history,
            "clarification_answers": record["execution"]["answers"],
            "review": review,
            "completed_actions": record["state"]["completed_actions"] if review else [],
        }

    async def _prepare(self, record: dict[str, Any]) -> bool:
        message_id = record["message_id"]
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
        if execution["reviews"] >= MAX_REVIEWS or not any(
            isinstance(step, FigurePlotStep | FigureAddStep | FigureArrangeStep) for step in steps
        ):
            return False
        document = self.compositions.get(record["project_id"], record["composition_id"])
        if not any(check.severity == "warning" for check in document.checks):
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
        self, project_id: str, content: PlotPanelContent | ImagePanelContent
    ) -> tuple[float, float]:
        if isinstance(content, PlotPanelContent):
            return self.compositions.natural_size(
                self.compositions.figure(project_id, content.version_id)
            )
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
        while True:
            jobs = [
                job
                for job in self.figures.jobs(record["composition_id"], limit=100)
                if job["request_key"].startswith(key + ":")
            ]
            if all(job["status"] != "running" for job in jobs):
                break
            if self.store.get(message_id)["state"]["status"] not in ACTIVE:
                return None
            await asyncio.sleep(POLL_SECONDS)
        failed = [job for job in jobs if job["status"] != "completed"]
        if failed:
            return f"{step.summary} ({len(failed)} of {len(jobs)} plots kept their scaled size.)"
        return step.summary

    async def _plot(self, record: dict[str, Any], step: FigurePlotStep, key: str) -> str | None:
        message_id, project_id = record["message_id"], record["project_id"]
        plot = record["execution"].get("plot")
        if plot is None:
            content = self.figures.get(project_id, record["composition_id"])["content"]
            panel = next((p for p in content.panels if p.id == step.panel_id), None)
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
            text = ("Refine the selected plot: " if base else "Create a plot: ") + step.instructions
            if step.width_mm and step.height_mm:
                text += (
                    f"\nRender it at {step.width_mm / MM_PER_INCH:.2f} × "
                    f"{step.height_mm / MM_PER_INCH:.2f} inches for its figure panel."
                )
            text += f"\nFigure: {content.title}."
            turn = self.assistant.start_turn(
                AssistantTurnRequest.model_validate(
                    {
                        "project_id": project_id,
                        "request": {
                            "text": text,
                            **({"reference_image_ids": images} if images else {}),
                        },
                        "data_scope": {"mode": "auto"},
                        "base_version_id": base,
                    }
                ),
                idempotency_key=key,
            )
            plot = {
                "panel_id": step.panel_id,
                "prompt": step.instructions,
                "refine": panel is not None,
                "assistant": turn.model_dump(mode="json"),
                "run": None,
            }
            self.store.update(message_id, {"phase": "plotting"}, {"plot": plot})
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
                    self._use(record, step, run.result)
                    self.store.update(message_id, {"status": "running"}, {"plot": None})
                    return (
                        f"Refined panel “{step.panel_id}”."
                        if plot["refine"]
                        else f"Created panel “{step.panel_id}”."
                    )
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

    def _use(self, record: dict[str, Any], step: FigurePlotStep, result: PlotResultSummary) -> None:
        """Put a finished plot into its panel, keeping an existing panel's width on the page."""
        project_id = record["project_id"]
        width, height = self.compositions.natural_size(result)
        plot = PlotPanelContent(version_id=result.version_id)

        def update(content: FigureCompositionContent) -> FigureCompositionContent:
            panels = list(content.panels)
            index = next((i for i, p in enumerate(panels) if p.id == step.panel_id), None)
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
                    (page.width_mm - old.x_mm) / width,
                    (page.height_mm - old.y_mm) / height,
                )
                panels[index] = old.model_copy(
                    update={"content": plot, "scale": max(0.05, int(scale * 1000) / 1000)}
                )
            return FigureCompositionContent.model_validate(
                {**content.model_dump(mode="json"), "panels": [p.model_dump() for p in panels]}
            )

        self.figures.change(
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
