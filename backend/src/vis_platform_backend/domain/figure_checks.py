"""Print and layout checks. They describe problems; they never block saving a figure."""

from __future__ import annotations

from collections.abc import Mapping
from itertools import combinations

from vis_platform_backend.contracts.figure_composition_content import FigureCompositionContent
from vis_platform_backend.contracts.figure_compositions import FigureCheck, PanelFrame
from vis_platform_backend.domain.figure_compositions import IMAGE_DPI, reading_order

TOLERANCE_MM = 0.05
MIN_COVERAGE = 0.5


def _name(labels: Mapping[str, str | None], panel_id: str) -> str:
    label = labels.get(panel_id)
    return f"Panel {label}" if label else f"Panel “{panel_id}”"


def _intersection(a: PanelFrame, b: PanelFrame) -> float:
    width = min(a.x_mm + a.width_mm, b.x_mm + b.width_mm) - max(a.x_mm, b.x_mm)
    height = min(a.y_mm + a.height_mm, b.y_mm + b.height_mm) - max(a.y_mm, b.y_mm)
    return max(width, 0) * max(height, 0)


def _contains(outer: PanelFrame, inner: PanelFrame) -> bool:
    return (
        outer.x_mm <= inner.x_mm + TOLERANCE_MM
        and outer.y_mm <= inner.y_mm + TOLERANCE_MM
        and inner.x_mm + inner.width_mm <= outer.x_mm + outer.width_mm + TOLERANCE_MM
        and inner.y_mm + inner.height_mm <= outer.y_mm + outer.height_mm + TOLERANCE_MM
    )


def figure_checks(
    content: FigureCompositionContent,
    frames: Mapping[str, PanelFrame],
    labels: Mapping[str, str | None],
    page_height_mm: float,
    smallest_text_pt: Mapping[str, tuple[float, bool]],
) -> list[FigureCheck]:
    """``smallest_text_pt`` holds each plot panel's smallest text at its natural size, and
    whether it was measured rather than assumed."""
    page, checks = content.page, []
    margin = page.margin_mm
    outside = [
        panel.id
        for panel in content.panels
        if frames[panel.id].x_mm < margin - TOLERANCE_MM
        or frames[panel.id].y_mm < margin - TOLERANCE_MM
        or frames[panel.id].x_mm + frames[panel.id].width_mm > page.width_mm - margin + TOLERANCE_MM
        or frames[panel.id].y_mm + frames[panel.id].height_mm
        > page_height_mm - margin + TOLERANCE_MM
    ]
    if outside:
        checks.append(
            FigureCheck(
                code="outside_margin",
                severity="warning",
                message=f"{', '.join(_name(labels, i) for i in outside)} "
                f"{'extends' if len(outside) == 1 else 'extend'} into the {margin:g} mm margin.",
                panel_ids=outside,
            )
        )
    for first, second in combinations(content.panels, 2):
        a, b = frames[first.id], frames[second.id]
        # A panel fully inside another is an inset; only partial overlaps are reported.
        if _intersection(a, b) > TOLERANCE_MM**2 and not (_contains(a, b) or _contains(b, a)):
            checks.append(
                FigureCheck(
                    code="overlap",
                    severity="warning",
                    message=f"{_name(labels, first.id)} and {_name(labels, second.id)} overlap.",
                    panel_ids=[first.id, second.id],
                )
            )
    for panel in content.panels:
        if panel.content.type == "plot" and panel.id in smallest_text_pt:
            natural, measured = smallest_text_pt[panel.id]
            printed = natural * panel.scale
            if printed < content.min_font_pt - 0.05:
                checks.append(
                    FigureCheck(
                        code="small_text",
                        severity="warning",
                        message=(
                            f"The smallest text in {_name(labels, panel.id)} "
                            f"{'prints at' if measured else 'may print at about'} "
                            f"{printed:.1f} pt, below {content.min_font_pt:g} pt. Render the "
                            "plot at its panel size or enlarge the panel."
                        ),
                        panel_ids=[panel.id],
                    )
                )
        elif panel.content.type == "image" and panel.scale > 1.001:
            checks.append(
                FigureCheck(
                    code="low_resolution",
                    severity="warning",
                    message=f"{_name(labels, panel.id)} prints at "
                    f"{IMAGE_DPI / panel.scale:.0f} dpi; journals usually expect {IMAGE_DPI}.",
                    panel_ids=[panel.id],
                )
            )
    empty = [panel.id for panel in content.panels if panel.content.type == "slot"]
    if empty:
        checks.append(
            FigureCheck(
                code="empty_slot",
                severity="warning",
                message=f"{', '.join(_name(labels, i) for i in empty)} "
                f"{'has' if len(empty) == 1 else 'have'} no plot yet and "
                f"{'is' if len(empty) == 1 else 'are'} left out of exports.",
                panel_ids=empty,
            )
        )
    shown = [panel for panel in content.panels if panel.show_label]
    ordered = [labels[panel.id] for panel in reading_order(shown, frames)]
    if any(panel.label for panel in shown) and ordered != sorted(
        ordered, key=lambda label: (len(label or ""), (label or "").casefold())
    ):
        checks.append(
            FigureCheck(
                code="label_order",
                severity="info",
                message="Custom labels do not follow the reading order: "
                + ", ".join(label or "" for label in ordered)
                + ".",
                panel_ids=[panel.id for panel in shown if panel.label],
            )
        )
    printable = (page.width_mm - 2 * margin) * (page_height_mm - 2 * margin)
    covered = sum(frame.width_mm * frame.height_mm for frame in frames.values())
    if content.panels and printable > 0 and covered / printable < MIN_COVERAGE:
        checks.append(
            FigureCheck(
                code="unused_space",
                severity="info",
                message=f"Panels cover {covered / printable:.0%} of the printable area. "
                "Enlarge them or use a smaller page.",
            )
        )
    return checks
