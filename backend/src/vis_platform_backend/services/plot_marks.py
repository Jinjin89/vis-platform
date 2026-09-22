"""Show the planners where the user pointed: the plot with numbered marks, and their data values."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from cairosvg.surface import PNGSurface  # type: ignore[import-untyped]
from PIL import Image, ImageDraw, ImageFont

from vis_platform_backend.agents.messages import ModelImage
from vis_platform_backend.contracts.plot_marks import PlotMark
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.domain.plot_marks import PlotPanel, describe_marks, parse_plot_map
from vis_platform_backend.execution.runner import RExecutionError
from vis_platform_backend.infrastructure.database import Repository
from vis_platform_backend.services.figure_exports import embedded_images_only
from vis_platform_backend.services.figure_svg import read_svg

MARKED_IMAGE_ID = "current-plot-marks"
PLOT_MAP = "plot-map.json"
LONG_SIDE = 1600
MARK = (214, 0, 111)
WHITE = (255, 255, 255)


@dataclass(frozen=True, slots=True)
class MarkedPlot:
    image: ModelImage
    marks: list[dict[str, Any]]


class PlotMarkService:
    def __init__(self, repository: Repository, artifact_root: Path) -> None:
        self.repository = repository
        self.artifact_root = artifact_root.resolve()

    def prepare(self, project_id: str, version_id: str, marks: list[PlotMark]) -> MarkedPlot:
        """Draw the marks on the version's image and place them in its data coordinates."""
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
                marked = draw_marks(raster.convert("RGB"), marks)
        except (RExecutionError, ValueError, KeyError, OSError) as error:
            raise DataError(
                "The marks could not be drawn on this plot.", "PLOT_MARKS_FAILED", 422
            ) from error
        buffer = io.BytesIO()
        marked.save(buffer, format="PNG")
        return MarkedPlot(
            image=ModelImage(
                image_id=MARKED_IMAGE_ID,
                data=buffer.getvalue(),
                label="Current plot with the user's numbered marks",
            ),
            marks=describe_marks(marks, _plot_map(source.with_name(PLOT_MAP))),
        )


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


def draw_marks(image: Image.Image, marks: list[PlotMark]) -> Image.Image:
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
