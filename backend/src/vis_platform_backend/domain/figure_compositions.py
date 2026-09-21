"""Figure composition rules: operations, panel geometry, page height, and reading-order labels."""

from __future__ import annotations

import itertools
import string
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from vis_platform_backend.contracts.figure_composition_content import (
    FigureCompositionContent,
    FigurePanel,
    PanelLabelStyle,
)
from vis_platform_backend.contracts.figure_composition_operations import (
    AddPanel,
    FigureOperation,
    RemovePanel,
    ReplacePanel,
    SetFigurePage,
    SetFigureTitle,
    SetLabelStyle,
    SetLegend,
    SetPanelGeometry,
)
from vis_platform_backend.contracts.figure_compositions import PanelFrame
from vis_platform_backend.data.errors import DataError

MM_PER_INCH = 25.4
IMAGE_DPI = 300
MIN_PAGE_HEIGHT_MM = 20
TOLERANCE_MM = 0.01


def _panel_index(panels: list[dict[str, Any]], panel_id: str) -> int:
    for index, panel in enumerate(panels):
        if panel["id"] == panel_id:
            return index
    raise DataError(f"Panel “{panel_id}” was not found in this figure.", "NOT_FOUND", 404)


def apply_figure_operations(
    content: FigureCompositionContent, operations: Sequence[FigureOperation]
) -> FigureCompositionContent:
    result = content.model_dump(mode="json")
    panels: list[dict[str, Any]] = result["panels"]
    for operation in operations:
        if isinstance(operation, SetFigureTitle):
            result["title"] = operation.title
        elif isinstance(operation, SetFigurePage):
            result["page"] = operation.page.model_dump(mode="json")
        elif isinstance(operation, SetLabelStyle):
            result["labels"] = operation.labels.model_dump(mode="json")
        elif isinstance(operation, AddPanel):
            index = (
                _panel_index(panels, operation.before_id) if operation.before_id else len(panels)
            )
            panels.insert(index, operation.panel.model_dump(mode="json"))
        elif isinstance(operation, ReplacePanel):
            panels[_panel_index(panels, operation.panel.id)] = operation.panel.model_dump(
                mode="json"
            )
        elif isinstance(operation, RemovePanel):
            panels.pop(_panel_index(panels, operation.panel_id))
            result["legend"]["entries"].pop(operation.panel_id, None)
        elif isinstance(operation, SetPanelGeometry):
            for panel_id, geometry in operation.panels.items():
                panels[_panel_index(panels, panel_id)].update(geometry.model_dump(mode="json"))
        elif isinstance(operation, SetLegend):
            result["legend"] = operation.legend.model_dump(mode="json")
    try:
        return FigureCompositionContent.model_validate(result)
    except ValidationError as error:
        detail = error.errors()[0]
        location = ".".join(str(part) for part in detail["loc"])
        message = detail["msg"].removeprefix("Value error, ")
        raise DataError(
            f"{location}: {message}" if location else message, "INVALID_FIGURE_OPERATION", 422
        ) from error


def plot_natural_size(width_in: float, height_in: float) -> tuple[float, float]:
    return width_in * MM_PER_INCH, height_in * MM_PER_INCH


def image_natural_size(width_px: int, height_px: int) -> tuple[float, float]:
    """Uploaded images have no physical size; they are placed at print resolution."""
    return width_px / IMAGE_DPI * MM_PER_INCH, height_px / IMAGE_DPI * MM_PER_INCH


def panel_frames(
    content: FigureCompositionContent, natural_sizes: Mapping[str, tuple[float, float]]
) -> dict[str, PanelFrame]:
    """A panel's displayed size is always its content's natural size times its scale."""
    frames = {}
    for panel in content.panels:
        width, height = natural_sizes[panel.id]
        frames[panel.id] = PanelFrame(
            x_mm=panel.x_mm,
            y_mm=panel.y_mm,
            width_mm=round(width * panel.scale, 3),
            height_mm=round(height * panel.scale, 3),
        )
    return frames


def check_bounds(content: FigureCompositionContent, frames: Mapping[str, PanelFrame]) -> None:
    page = content.page
    for panel in content.panels:
        frame = frames[panel.id]
        if (
            frame.x_mm + frame.width_mm > page.width_mm + TOLERANCE_MM
            or frame.y_mm + frame.height_mm > page.height_mm + TOLERANCE_MM
        ):
            raise DataError(
                f"Panel “{panel.id}” extends beyond the page. Move it or reduce its scale.",
                "INVALID_FIGURE_LAYOUT",
                422,
            )


def page_height(content: FigureCompositionContent, frames: Mapping[str, PanelFrame]) -> float:
    page = content.page
    if page.height_mode == "fixed":
        return page.height_mm
    bottom = max((frame.y_mm + frame.height_mm for frame in frames.values()), default=0)
    return round(min(page.height_mm, max(MIN_PAGE_HEIGHT_MM, bottom + page.margin_mm)), 3)


def reading_order(
    panels: Sequence[FigurePanel], frames: Mapping[str, PanelFrame]
) -> list[FigurePanel]:
    """Group panels into rows, then read each row from left to right.

    A panel joins the current row when it starts above the middle of the row's shortest panel.
    """
    rows: list[list[FigurePanel]] = []
    for panel in sorted(panels, key=lambda item: (frames[item.id].y_mm, frames[item.id].x_mm)):
        frame = frames[panel.id]
        if rows:
            row = rows[-1]
            top = min(frames[item.id].y_mm for item in row)
            shortest = min(frames[item.id].height_mm for item in row)
            if frame.y_mm < top + shortest / 2:
                row.append(panel)
                continue
        rows.append([panel])
    return [panel for row in rows for panel in sorted(row, key=lambda item: frames[item.id].x_mm)]


def _letters(style: PanelLabelStyle) -> Iterator[str]:
    alphabet = string.ascii_uppercase if style.case == "upper" else string.ascii_lowercase
    for length in itertools.count(1):
        for letters in itertools.product(alphabet, repeat=length):
            yield "".join(letters)


def panel_labels(
    content: FigureCompositionContent, frames: Mapping[str, PanelFrame]
) -> dict[str, str | None]:
    """Custom labels are kept; automatic labels follow reading order and skip custom ones."""
    shown = [panel for panel in content.panels if panel.show_label]
    reserved = {panel.label.casefold() for panel in shown if panel.label}
    letters = (letter for letter in _letters(content.labels) if letter.casefold() not in reserved)
    labels: dict[str, str | None] = {panel.id: None for panel in content.panels}
    for panel in reading_order(shown, frames):
        labels[panel.id] = panel.label or next(letters)
    return labels
