"""Solve a nested row/column arrangement into panel frames.

Every subtree is summarised by an affine relation between its width and height,
``height = alpha * width + beta``: a panel has ``alpha = 1 / aspect``; a column adds its
children's heights; a row shares one height, so its children's widths add up. The root is
then given the printable width, reduced when the result would be taller than the page.
Panels therefore keep their proportions, rows can hold different numbers of panels, and
groups can nest to any depth.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from vis_platform_backend.contracts.figure_arrangement import (
    ArrangedGroup,
    ArrangedPanel,
    ArrangementNode,
)
from vis_platform_backend.contracts.figure_composition_content import FigurePanel
from vis_platform_backend.contracts.figure_compositions import PanelFrame
from vis_platform_backend.data.errors import DataError

MIN_PANEL_MM = 5


@dataclass(frozen=True)
class Affine:
    alpha: float
    beta: float

    def height(self, width: float) -> float:
        return self.alpha * width + self.beta

    def width(self, height: float) -> float:
        return (height - self.beta) / self.alpha


def arranged_panels(node: ArrangementNode) -> list[str]:
    if isinstance(node, ArrangedPanel):
        return [node.panel_id]
    return [panel_id for child in node.children for panel_id in arranged_panels(child)]


def _affine(node: ArrangementNode, aspects: Mapping[str, float], gutter: float) -> Affine:
    if isinstance(node, ArrangedPanel):
        return Affine(1 / aspects[node.panel_id], 0)
    parts = [_affine(child, aspects, gutter) for child in node.children]
    gaps = (len(parts) - 1) * gutter
    if node.type == "column":
        return Affine(sum(p.alpha for p in parts), sum(p.beta for p in parts) + gaps)
    alpha = 1 / sum(1 / p.alpha for p in parts)
    return Affine(alpha, (sum(p.beta / p.alpha for p in parts) - gaps) * alpha)


def _place(
    node: ArrangementNode,
    aspects: Mapping[str, float],
    gutter: float,
    x: float,
    y: float,
    width: float,
    frames: dict[str, PanelFrame],
) -> None:
    height = _affine(node, aspects, gutter).height(width)
    if width < MIN_PANEL_MM or height < MIN_PANEL_MM:
        raise DataError(
            "The arrangement leaves no room for some panels. Use fewer panels per row or a "
            "smaller gutter.",
            "INVALID_FIGURE_LAYOUT",
            422,
        )
    if isinstance(node, ArrangedPanel):
        frames[node.panel_id] = PanelFrame(x_mm=x, y_mm=y, width_mm=width, height_mm=height)
        return
    assert isinstance(node, ArrangedGroup)
    for child in node.children:
        part = _affine(child, aspects, gutter)
        if node.type == "column":
            _place(child, aspects, gutter, x, y, width, frames)
            y += part.height(width) + gutter
        else:
            child_width = part.width(height)
            _place(child, aspects, gutter, x, y, child_width, frames)
            x += child_width + gutter


def solve_arrangement(
    node: ArrangementNode,
    aspects: Mapping[str, float],
    *,
    left: float,
    top: float,
    width: float,
    max_height: float,
    gutter: float,
) -> dict[str, PanelFrame]:
    """Fill the available width, or the available height when that runs out first."""
    ids = arranged_panels(node)
    if len(ids) != len(set(ids)):
        raise DataError(
            "Each panel can appear only once in an arrangement.", "INVALID_FIGURE_LAYOUT", 422
        )
    root = _affine(node, aspects, gutter)
    used = width
    if root.height(width) > max_height:
        used = root.width(max_height)
    frames: dict[str, PanelFrame] = {}
    _place(node, aspects, gutter, left + (width - used) / 2, top, used, frames)
    return frames


def rows_arrangement(rows: list[list[FigurePanel]]) -> ArrangementNode:
    """The tidy arrangement of existing reading-order rows."""
    groups: list[ArrangementNode] = []
    for row in rows:
        panels: list[ArrangementNode] = [ArrangedPanel(panel_id=panel.id) for panel in row]
        groups.append(panels[0] if len(panels) == 1 else ArrangedGroup(type="row", children=panels))
    return groups[0] if len(groups) == 1 else ArrangedGroup(type="column", children=groups)
