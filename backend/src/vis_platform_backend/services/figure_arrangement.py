"""Arrange figure panels and render plots at their panel sizes."""

from __future__ import annotations

import asyncio
import math
from typing import Any

from vis_platform_backend.contracts.figure_arrangement import (
    ArrangedPanel,
    ArrangementNode,
    ArrangeRequest,
    RenderRequest,
)
from vis_platform_backend.contracts.figure_composition_content import (
    FigureCompositionContent,
    PlotPanelContent,
    SlotPanelContent,
)
from vis_platform_backend.contracts.figure_composition_operations import (
    FigureOperation,
    FigureOperationsRequest,
    PanelGeometry,
    ReplacePanel,
    SetPanelGeometry,
)
from vis_platform_backend.contracts.figure_compositions import FigureCompositionDocument
from vis_platform_backend.contracts.parameters import ParameterUpdateRequest
from vis_platform_backend.contracts.plot_runs import PlotResultSummary, RunStatus
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.domain.figure_compositions import MM_PER_INCH, reading_rows
from vis_platform_backend.domain.figure_layout import (
    arranged_panels,
    rows_arrangement,
    solve_arrangement,
)
from vis_platform_backend.domain.parameters import InvalidParameterError
from vis_platform_backend.services.figure_compositions import FigureCompositionService
from vis_platform_backend.services.figure_controls import SIZE_CONTROL_IDS
from vis_platform_backend.services.plot_runs import PlotCapabilityError, PlotRunCoordinator

MIN_RENDER_MM = MM_PER_INCH
TERMINAL = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}


def renderable(figure: PlotResultSummary) -> bool:
    """Only versions whose renderer accepts the standard size controls can be resized."""
    controls = {control.id for control in figure.controls}
    return figure.parameter_updates_available and controls >= SIZE_CONTROL_IDS


def _leaves(node: ArrangementNode) -> dict[str, ArrangedPanel]:
    if isinstance(node, ArrangedPanel):
        return {node.panel_id: node}
    return {key: leaf for child in node.children for key, leaf in _leaves(child).items()}


def _floor(value: float, step: float = 0.001) -> float:
    return round(math.floor(value / step + 1e-9) * step, 6)


class FigureArrangementService:
    def __init__(
        self, compositions: FigureCompositionService, coordinator: PlotRunCoordinator
    ) -> None:
        self.compositions, self.coordinator = compositions, coordinator
        self.store = compositions.store
        self.tasks: dict[str, asyncio.Task[None]] = {}

    def arrange(
        self, project_id: str, composition_id: str, request: ArrangeRequest
    ) -> FigureCompositionDocument:
        content: FigureCompositionContent = self.store.get(project_id, composition_id)["content"]
        resolved = self.compositions.resolve(project_id, content)
        panels = {panel.id: panel for panel in content.panels}
        locked = [panel for panel in content.panels if panel.locked]
        movable = [panel for panel in content.panels if not panel.locked]
        if request.arrangement is None and not movable:
            raise DataError(
                "There are no unlocked panels to arrange.", "INVALID_FIGURE_LAYOUT", 422
            )
        node = request.arrangement or rows_arrangement(reading_rows(movable, resolved.frames))
        ids = arranged_panels(node)
        for panel_id in ids:
            if panel_id not in panels:
                raise DataError(f"Panel “{panel_id}” was not found.", "NOT_FOUND", 404)
            if panels[panel_id].locked:
                raise DataError(
                    f"Panel “{panel_id}” is locked. Unlock it or leave it out of the arrangement.",
                    "INVALID_FIGURE_LAYOUT",
                    422,
                )
        page, gutter = content.page, request.gutter_mm
        # Locked panels keep their places; the arrangement starts below them.
        top = max(
            [page.margin_mm]
            + [
                resolved.frames[p.id].y_mm + resolved.frames[p.id].height_mm + gutter
                for p in locked
            ]
        )
        leaves = _leaves(node)
        # Slots have no content proportions yet, so they take the shape they are given.
        slots = {pid for pid in ids if isinstance(panels[pid].content, SlotPanelContent)}
        resize = set()
        for panel_id in ids:
            plot = panels[panel_id].content
            if (
                request.render
                and isinstance(plot, PlotPanelContent)
                and renderable(resolved.figures[plot.version_id])
            ):
                resize.add(panel_id)
        aspects = {}
        for panel_id in ids:
            width, height = resolved.natural_sizes[panel_id]
            preferred = leaves[panel_id].aspect
            reshape = panel_id in resize or panel_id in slots
            aspects[panel_id] = preferred if reshape and preferred else width / height
        frames = solve_arrangement(
            node,
            aspects,
            left=page.margin_mm,
            top=top,
            width=page.width_mm - 2 * page.margin_mm,
            max_height=page.height_mm - page.margin_mm - top,
            gutter=gutter,
        )
        geometry, targets = {}, {}
        operations: list[FigureOperation] = []
        for panel_id, frame in frames.items():
            panel = panels[panel_id]
            if isinstance(panel.content, SlotPanelContent):
                size = {
                    "width_mm": max(5, _floor(frame.width_mm, 0.01)),
                    "height_mm": max(5, _floor(frame.height_mm, 0.01)),
                }
                reshaped = panel.content.model_copy(update=size)
                operations.append(
                    ReplacePanel(
                        op="replace_panel",
                        panel=panel.model_copy(
                            update={
                                "content": reshaped,
                                "x_mm": round(frame.x_mm, 2),
                                "y_mm": round(frame.y_mm, 2),
                                "scale": 1,
                            }
                        ),
                    )
                )
                continue
            width, height = resolved.natural_sizes[panel_id]
            # Until a render completes, resized plots are shown scaled inside their frame.
            scale = min(frame.width_mm / width, frame.height_mm / height)
            geometry[panel_id] = PanelGeometry(
                x_mm=round(frame.x_mm, 2), y_mm=round(frame.y_mm, 2), scale=max(0.05, _floor(scale))
            )
            if panel_id in resize:
                targets[panel_id] = (frame.width_mm, frame.height_mm)
        self.store.apply_operations(
            project_id,
            composition_id,
            FigureOperationsRequest(
                request_id=request.request_id,
                base_revision=request.base_revision,
                operations=[
                    *(
                        [SetPanelGeometry(op="set_panel_geometry", panels=geometry)]
                        if geometry
                        else []
                    ),
                    *operations,
                ],
                summary=request.summary,
            ),
            lambda updated: self.compositions.validate(project_id, updated),
        )
        if targets:
            self.start_renders(project_id, composition_id, request.request_id, targets)
        return self.compositions.get(project_id, composition_id)

    def render(
        self, project_id: str, composition_id: str, request: RenderRequest
    ) -> FigureCompositionDocument:
        content: FigureCompositionContent = self.store.get(project_id, composition_id)["content"]
        resolved = self.compositions.resolve(project_id, content)
        panels = {panel.id: panel for panel in content.panels}
        for panel_id, size in request.panels.items():
            panel = panels.get(panel_id)
            if panel is None:
                raise DataError(f"Panel “{panel_id}” was not found.", "NOT_FOUND", 404)
            if not isinstance(panel.content, PlotPanelContent) or not renderable(
                resolved.figures[panel.content.version_id]
            ):
                raise DataError(
                    f"Panel “{panel_id}” cannot be rendered at a new size; only saved plots "
                    "with size controls can.",
                    "FIGURE_RENDER_UNAVAILABLE",
                    422,
                )
            if (
                panel.x_mm + size.width_mm > content.page.width_mm + 0.01
                or panel.y_mm + size.height_mm > content.page.height_mm + 0.01
            ):
                raise DataError(
                    f"Panel “{panel_id}” would extend beyond the page at that size.",
                    "INVALID_FIGURE_LAYOUT",
                    422,
                )
        self.start_renders(
            project_id,
            composition_id,
            request.request_id,
            {key: (size.width_mm, size.height_mm) for key, size in request.panels.items()},
        )
        return self.compositions.get(project_id, composition_id)

    def start_renders(
        self,
        project_id: str,
        composition_id: str,
        request_id: str,
        targets: dict[str, tuple[float, float]],
    ) -> None:
        content: FigureCompositionContent = self.store.get(project_id, composition_id)["content"]
        panels = {panel.id: panel for panel in content.panels}
        states = []
        for panel_id, (width, height) in targets.items():
            plot = panels[panel_id].content
            assert isinstance(plot, PlotPanelContent)
            figure = self.compositions.figure(project_id, plot.version_id)
            # Plots render at 1 inch or more; smaller panels are scaled down afterwards.
            factor = max(1.0, MIN_RENDER_MM / width, MIN_RENDER_MM / height)
            states.append(
                {
                    "project_id": project_id,
                    "panel_id": panel_id,
                    "plot_id": figure.plot_id,
                    "base_version_id": plot.version_id,
                    "source_version_id": plot.source_version_id or plot.version_id,
                    "width_mm": round(width * factor, 2),
                    "height_mm": round(height * factor, 2),
                    "scale": _floor(1 / factor),
                    "run_id": None,
                }
            )
        for job_id in self.store.create_jobs(composition_id, request_id, states):
            job = self.store.job(job_id)
            if job["status"] == "running" and not job["state"]["run_id"]:
                self._submit(job)
            self._watch(job_id)

    def _submit(self, job: dict[str, Any]) -> None:
        state = job["state"]
        try:
            accepted = self.coordinator.update_parameters(
                state["plot_id"],
                ParameterUpdateRequest(
                    project_id=state["project_id"],
                    base_version_id=state["base_version_id"],
                    # Rounded down to the control's 0.01 in step so the panel stays on the page.
                    changes={
                        "figure_width": _floor(state["width_mm"] / MM_PER_INCH, 0.01),
                        "figure_height": _floor(state["height_mm"] / MM_PER_INCH, 0.01),
                    },
                ),
                idempotency_key=job["job_id"],
                placement=True,
            )
        except (PlotCapabilityError, InvalidParameterError, DataError) as error:
            self.store.update_job(job["job_id"], "failed", {"error": str(error)})
            return
        self.store.update_job(job["job_id"], "running", {"run_id": accepted.run_id})

    def _watch(self, job_id: str) -> None:
        if job_id not in self.tasks or self.tasks[job_id].done():
            task = asyncio.create_task(self._follow(job_id))
            self.tasks[job_id] = task
            task.add_done_callback(lambda done: self.tasks.pop(job_id, None))

    async def _follow(self, job_id: str) -> None:
        try:
            while True:
                job = self.store.job(job_id)
                if job["status"] != "running":
                    return
                snapshot = self.coordinator.get_run(job["state"]["run_id"])
                if snapshot.status in TERMINAL:
                    break
                await asyncio.sleep(0.2)
            if snapshot.status is RunStatus.COMPLETED and snapshot.result is not None:
                self._apply(job, snapshot.result)
            else:
                self.store.update_job(
                    job_id,
                    "failed",
                    {
                        "error": snapshot.failure.message
                        if snapshot.failure
                        else "The render did not complete."
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.store.update_job(
                job_id,
                "failed",
                {
                    "error": str(error)
                    if isinstance(error, DataError)
                    else "The rendered plot could not be placed. Please retry."
                },
            )

    def _apply(self, job: dict[str, Any], result: PlotResultSummary) -> None:
        state = job["state"]

        def update(content: FigureCompositionContent) -> FigureCompositionContent | None:
            data = content.model_dump(mode="json")
            panel = next((p for p in data["panels"] if p["id"] == state["panel_id"]), None)
            # A panel changed since the render started keeps the user's newer choice.
            if panel is None or panel["content"].get("version_id") != state["base_version_id"]:
                return None
            panel["content"] = {
                **panel["content"],
                "version_id": result.version_id,
                "source_version_id": state["source_version_id"],
            }
            panel["scale"] = state["scale"]
            return FigureCompositionContent.model_validate(data)

        applied = self.store.change(
            state["project_id"],
            self.store.job(job["job_id"])["composition_id"],
            update,
            "Rendered a plot at its panel size",
            lambda content: self.compositions.validate(state["project_id"], content),
        )
        self.store.update_job(
            job["job_id"],
            "completed" if applied else "discarded",
            {
                "version_id": result.version_id,
                "error": None
                if applied
                else "The panel changed before the render finished, so it was not applied.",
            },
        )

    def recover(self) -> None:
        for job in self.store.running_jobs():
            if job["state"].get("run_id"):
                self._watch(job["job_id"])
            else:
                self.store.update_job(
                    job["job_id"], "failed", {"error": "The render was interrupted. Try again."}
                )

    async def shutdown(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
