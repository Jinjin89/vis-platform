"""Show the planners where the user pointed: the plot with numbered marks, and their data values."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import numpy as np
from cairosvg.surface import PNGSurface  # type: ignore[import-untyped]
from PIL import Image, ImageDraw, ImageFont

from vis_platform_backend.agents.messages import ModelImage
from vis_platform_backend.contracts.plot_marks import (
    ElementMark,
    ImageMark,
    PlotMark,
    SelectionMark,
)
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.domain.plot_marks import (
    PLOT_MAP,
    PlotPanel,
    describe_marks,
    image_fraction,
    parse_plot_map,
)
from vis_platform_backend.execution.runner import RExecutionError
from vis_platform_backend.infrastructure.database import Repository
from vis_platform_backend.services.figure_exports import embedded_images_only
from vis_platform_backend.services.figure_svg import read_svg
from vis_platform_backend.services.point_maps import PointMapService

MARKED_IMAGE_ID = "current-plot-marks"
LONG_SIDE = 1600
MARK = (214, 0, 111)
WHITE = (255, 255, 255)


@dataclass(frozen=True, slots=True)
class MarkedPlot:
    image: ModelImage
    marks: list[dict[str, Any]]


class PlotMarkService:
    def __init__(
        self, repository: Repository, artifact_root: Path, points: PointMapService | None = None
    ) -> None:
        self.repository = repository
        self.artifact_root = artifact_root.resolve()
        self.points = points

    async def prepare(self, project_id: str, version_id: str, marks: list[PlotMark]) -> MarkedPlot:
        """Draw the marks on the version's image and place them in its data coordinates.

        Marks from an interactive point view are drawn where their points are, and also say
        what the clicked point or dragged area holds in the source table.
        """
        placed, found = self._place(project_id, version_id, marks)
        result = self.repository.result_for_version(version_id, project_id)
        artifact = (
            self.repository.get_artifact(result["preview"]["artifact_id"]) if result else None
        )
        source = Path(artifact["storage_path"]).resolve() if artifact else None
        if source is None or not source.is_relative_to(self.artifact_root) or not source.is_file():
            raise DataError("The marked plot is unavailable.", "NOT_FOUND", 404)
        try:
            width, height = _raster_size(read_svg(source))
            png = PNGSurface.convert(
                bytestring=source.read_bytes(),
                output_width=width,
                output_height=height,
                background_color="white",
                url_fetcher=embedded_images_only,
            )
            with Image.open(io.BytesIO(png)) as raster:
                marked = draw_marks(raster.convert("RGB"), placed)
        except (RExecutionError, ValueError, KeyError, OSError) as error:
            raise DataError(
                "The marks could not be drawn on this plot.", "PLOT_MARKS_FAILED", 422
            ) from error
        buffer = io.BytesIO()
        marked.save(buffer, format="PNG")
        described = describe_marks(placed, _plot_map(source.with_name(PLOT_MAP)))
        for item, mark in zip(described, marks, strict=True):
            if isinstance(mark, ElementMark | SelectionMark):
                assert self.points is not None
                item["kind"] = mark.kind
                item["data"] = await self.points.summarize(
                    project_id, version_id, found[mark.number], single=mark.kind == "element"
                )
        return MarkedPlot(
            image=ModelImage(
                image_id=MARKED_IMAGE_ID,
                data=buffer.getvalue(),
                label="Current plot with the user's numbered marks",
            ),
            marks=described,
        )

    def check(self, project_id: str, version_id: str, marks: list[PlotMark]) -> None:
        """Refuse point-view marks the version cannot resolve, before any planning starts."""
        clicked = [mark for mark in marks if isinstance(mark, ElementMark)]
        if not any(isinstance(mark, ElementMark | SelectionMark) for mark in marks):
            return
        if self.points is None:
            raise DataError("Point views are unavailable.", "NOT_FOUND", 404)
        count = int(self.points.view(project_id, version_id)["count"])
        for mark in clicked:
            if mark.index >= count:
                raise DataError(
                    f"Mark {mark.number} names a point this view does not have.",
                    "INVALID_PLOT_MARK",
                    422,
                )

    def _place(
        self, project_id: str, version_id: str, marks: list[PlotMark]
    ) -> tuple[list[ImageMark], dict[int, np.ndarray]]:
        """Every mark as a place on the image, and the points each point-view mark covers."""
        if all(isinstance(mark, ImageMark) for mark in marks):
            return [mark for mark in marks if isinstance(mark, ImageMark)], {}
        if self.points is None:
            raise DataError("Point views are unavailable.", "NOT_FOUND", 404)
        directory = self.points.version_directory(project_id, version_id)
        panels = _plot_map(directory / PLOT_MAP)
        if not panels:
            raise DataError("This point view has no recorded plotting area.", "NOT_FOUND", 404)
        x, y = self.points.positions(directory)
        placed: list[ImageMark] = []
        found: dict[int, np.ndarray] = {}
        for mark in marks:
            if isinstance(mark, ImageMark):
                placed.append(mark)
            elif isinstance(mark, ElementMark):
                if mark.index >= len(x):
                    raise DataError(
                        f"Mark {mark.number} names a point this view does not have.",
                        "INVALID_PLOT_MARK",
                        422,
                    )
                found[mark.number] = np.array([mark.index])
                left, top = image_fraction(panels[0], float(x[mark.index]), float(y[mark.index]))
                placed.append(ImageMark(number=mark.number, kind="point", x=left, y=top))
            else:
                found[mark.number] = np.flatnonzero(
                    (x >= mark.x_from) & (x <= mark.x_to) & (y >= mark.y_from) & (y <= mark.y_to)
                )
                corners = [
                    image_fraction(panels[0], mark.x_from, mark.y_from),
                    image_fraction(panels[0], mark.x_to, mark.y_to),
                ]
                left, right = sorted(corner[0] for corner in corners)
                top, bottom = sorted(corner[1] for corner in corners)
                placed.append(
                    ImageMark(
                        number=mark.number,
                        kind="area",
                        x=left,
                        y=top,
                        width=max(right - left, 0.002),
                        height=max(bottom - top, 0.002),
                    )
                    if right - left > 0 and bottom - top > 0
                    else ImageMark(number=mark.number, kind="point", x=left, y=top)
                )
        return placed, found


def _raster_size(root: ET.Element) -> tuple[int, int]:
    box = root.get("viewBox", "").replace(",", " ").split()
    if len(box) != 4:
        raise ValueError("The plot has no view box.")
    width, height = float(box[2]), float(box[3])
    if width <= 0 or height <= 0:
        raise ValueError("The plot has no usable dimensions.")
    scale = LONG_SIDE / max(width, height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _plot_map(path: Path) -> tuple[PlotPanel, ...] | None:
    """The recorded plotting regions; None for plots drawn before they were recorded."""
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        return None
    try:
        return parse_plot_map(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        return None


def draw_marks(image: Image.Image, marks: list[ImageMark]) -> Image.Image:
    """Numbered rings for points and outlines for areas, each with a badge beside the place."""
    draw = ImageDraw.Draw(image)
    unit = max(image.size) / 100
    ring, badge, line = 1.8 * unit, 1.3 * unit, max(2, round(0.3 * unit))
    font = ImageFont.load_default(size=max(10, round(1.6 * unit)))
    for mark in marks:
        x, y = mark.x * image.width, mark.y * image.height
        if mark.kind == "point":
            box = (x - ring, y - ring, x + ring, y + ring)
            draw.ellipse(box, outline=WHITE, width=line + 4)
            draw.ellipse(box, outline=MARK, width=line)
            # Up and to the right, clear of the marked place.
            centre = (x + ring + badge * 0.6, y - ring - badge * 0.6)
        else:
            box = (x, y, x + mark.width * image.width, y + mark.height * image.height)
            draw.rectangle(box, outline=WHITE, width=line + 4)
            draw.rectangle(box, outline=MARK, width=line)
            centre = (x, y)
        cx = min(max(centre[0], badge), image.width - badge)
        cy = min(max(centre[1], badge), image.height - badge)
        draw.ellipse(
            (cx - badge, cy - badge, cx + badge, cy + badge), fill=MARK, outline=WHITE, width=2
        )
        draw.text((cx, cy), str(mark.number), fill=WHITE, font=font, anchor="mm")
    return image
