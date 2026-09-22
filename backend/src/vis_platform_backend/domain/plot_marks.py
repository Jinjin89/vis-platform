"""Where marks on a plot image fall in the plot's own data coordinates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from vis_platform_backend.contracts.plot_marks import PlotMark

MAX_PANELS = 100


@dataclass(frozen=True, slots=True)
class PlotPanel:
    """A plotting region, in fractions of the image from its bottom-left corner, and its axes."""

    left: float
    right: float
    bottom: float
    top: float
    x_range: tuple[float, float]
    y_range: tuple[float, float]
    x_log: bool
    y_log: bool

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x <= self.right and self.bottom <= y <= self.top

    def data_x(self, x: float) -> float:
        return _value(x, self.left, self.right, self.x_range, self.x_log)

    def data_y(self, y: float) -> float:
        return _value(y, self.bottom, self.top, self.y_range, self.y_log)


def _value(
    position: float, start: float, end: float, axis: tuple[float, float], log: bool
) -> float:
    value = axis[0] + (position - start) / (end - start) * (axis[1] - axis[0])
    return _significant(10**value if log else value)


def _significant(value: float) -> float:
    return float(f"{value:.4g}")


def parse_plot_map(data: Any) -> tuple[PlotPanel, ...]:
    """Read the regions recorded while drawing; anything malformed is left out."""
    panels = data.get("panels") if isinstance(data, dict) else None
    if not isinstance(panels, list):
        return ()
    parsed = []
    for item in panels[:MAX_PANELS]:
        try:
            x, y, usr = item["x"], item["y"], item["usr"]
            numbers = [float(value) for value in (*x, *y, *usr)]
            if len(x) != 2 or len(y) != 2 or len(usr) != 4:
                continue
            x_log, y_log = item.get("xlog", False), item.get("ylog", False)
        except (KeyError, TypeError, ValueError):
            continue
        if (
            not all(math.isfinite(value) for value in numbers)
            or not isinstance(x_log, bool)
            or not isinstance(y_log, bool)
            or numbers[0] >= numbers[1]
            or numbers[2] >= numbers[3]
        ):
            continue
        parsed.append(
            PlotPanel(
                left=numbers[0],
                right=numbers[1],
                bottom=numbers[2],
                top=numbers[3],
                x_range=(numbers[4], numbers[5]),
                y_range=(numbers[6], numbers[7]),
                x_log=x_log,
                y_log=y_log,
            )
        )
    return tuple(parsed)


def describe_marks(
    marks: list[PlotMark], panels: tuple[PlotPanel, ...] | None
) -> list[dict[str, Any]]:
    """Each mark's place on the image and, where the drawing was recorded, in data units.

    Image positions are fractions from the top-left corner. Plotting regions are numbered in
    drawing order; a place outside every region (a title, legend or margin) has none.
    """
    described = []
    for mark in marks:
        item: dict[str, Any] = {"number": mark.number, "kind": mark.kind}
        # Image fractions run down from the top; plotting regions run up from the bottom.
        if mark.kind == "point":
            item["image_position"] = {"x": round(mark.x, 4), "y": round(mark.y, 4)}
            if panels is not None:
                item["plot_regions"] = [
                    {"region": index, "x": panel.data_x(mark.x), "y": panel.data_y(1 - mark.y)}
                    for index, panel in enumerate(panels, start=1)
                    if panel.contains(mark.x, 1 - mark.y)
                ]
        else:
            left, right = mark.x, mark.x + mark.width
            bottom, top = 1 - mark.y - mark.height, 1 - mark.y
            item["image_area"] = {
                "left": round(left, 4),
                "top": round(mark.y, 4),
                "right": round(right, 4),
                "bottom": round(mark.y + mark.height, 4),
            }
            if panels is not None:
                regions = []
                for index, panel in enumerate(panels, start=1):
                    # The part of the area inside this region.
                    x0, x1 = max(left, panel.left), min(right, panel.right)
                    y0, y1 = max(bottom, panel.bottom), min(top, panel.top)
                    if x0 < x1 and y0 < y1:
                        regions.append(
                            {
                                "region": index,
                                "x_from": panel.data_x(x0),
                                "x_to": panel.data_x(x1),
                                "y_from": panel.data_y(y0),
                                "y_to": panel.data_y(y1),
                            }
                        )
                item["plot_regions"] = regions
        described.append(item)
    return described
