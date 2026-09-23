"""Draw a point map: vector axes, text, and legend around a raster of the points.

Millions of points cannot be vector shapes in a printable file, so the points (and any image
under them) are drawn at print resolution and embedded; everything that must stay sharp and
editable is vector.
"""

from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

import numpy as np
from PIL import Image

SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
FONT = "Helvetica, Arial, sans-serif"
MISSING = (189, 189, 189)
# Distinct, colour-blind-aware hues first; more categories cycle through lighter variants.
CATEGORICAL = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
    "#bcbd22", "#17becf", "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5", "#c49c94",
    "#f7b6d2", "#c7c7c7", "#dbdb8d", "#9edae5",
]  # fmt: skip
VIRIDIS = [
    "#440154", "#482878", "#3e4989", "#31688e", "#26828e",
    "#1f9e89", "#35b779", "#6ece58", "#b5de2b", "#fde725",
]  # fmt: skip
PRINT_DPI = 300
# Keeps the saved drawing under the preview limit, with room for the vector layer.
RASTER_BUDGET = 6 * 1024 * 1024


def rgb(hex_color: str) -> tuple[int, int, int]:
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16))


def category_colors(count: int) -> list[str]:
    return [CATEGORICAL[index % len(CATEGORICAL)] for index in range(count)]


def ramp(values: np.ndarray, low: float, high: float) -> np.ndarray:
    """Viridis colours for values; missing values are grey."""
    stops = np.array([rgb(color) for color in VIRIDIS], dtype=np.float32)
    span = high - low if high > low else 1.0
    position = np.clip((values - low) / span, 0, 1) * (len(VIRIDIS) - 1)
    position = np.nan_to_num(position, nan=0.0)
    lower = np.floor(position).astype(np.int32).clip(0, len(VIRIDIS) - 2)
    weight = (position - lower)[:, None]
    colors = stops[lower] * (1 - weight) + stops[lower + 1] * weight
    colors[np.isnan(values)] = MISSING
    return np.asarray(colors, dtype=np.uint8)


def nice_ticks(low: float, high: float, count: int = 5) -> list[float]:
    span = high - low
    if not math.isfinite(span) or span <= 0:
        return [low]
    step = 10 ** math.floor(math.log10(span / count))
    error = span / count / step
    step *= 10 if error >= 7.5 else 5 if error >= 3.5 else 2 if error >= 1.5 else 1
    first = math.ceil(low / step - 1e-9) * step
    return [first + index * step for index in range(int((high - first) / step + 1e-9) + 1)]


def tick_label(value: float, ticks: list[float]) -> str:
    step = abs(ticks[1] - ticks[0]) if len(ticks) > 1 else abs(value) or 1
    decimals = max(0, -math.floor(math.log10(step)))
    text = f"{value:.{decimals}f}"
    return "0" if float(text) == 0 else text


@dataclass(frozen=True)
class Frame:
    """The map's geometry: its data window and the plotting area in points (1/72 inch)."""

    width: float
    height: float
    left: float
    top: float
    plot_width: float
    plot_height: float
    x_domain: tuple[float, float]
    y_domain: tuple[float, float]
    y_down: bool

    def plot_map(self) -> dict[str, Any]:
        """The plotting region, read by marks exactly as regions recorded while R draws."""
        y_axis = [self.y_domain[1], self.y_domain[0]] if self.y_down else list(self.y_domain)
        return {
            "panels": [
                {
                    "x": [self.left / self.width, (self.left + self.plot_width) / self.width],
                    "y": [
                        1 - (self.top + self.plot_height) / self.height,
                        1 - self.top / self.height,
                    ],
                    "usr": [*self.x_domain, *y_axis],
                    "xlog": False,
                    "ylog": False,
                }
            ]
        }


def layout(
    width_in: float,
    height_in: float,
    x_domain: tuple[float, float],
    y_domain: tuple[float, float],
    *,
    y_down: bool,
    equal_aspect: bool,
    titled: bool,
    legend_width: float,
) -> Frame:
    width, height = width_in * 72, height_in * 72
    left, top = 46.0, 22.0 if titled else 10.0
    plot_width = max(20.0, width - left - 12 - legend_width)
    plot_height = max(20.0, height - top - 36)
    if equal_aspect:
        aspect = (x_domain[1] - x_domain[0]) / (y_domain[1] - y_domain[0])
        if plot_width / plot_height > aspect:
            narrower = plot_height * aspect
            left += (plot_width - narrower) / 2
            plot_width = narrower
        else:
            shorter = plot_width / aspect
            top += (plot_height - shorter) / 2
            plot_height = shorter
    return Frame(width, height, left, top, plot_width, plot_height, x_domain, y_domain, y_down)


def raster(
    frame: Frame,
    x: np.ndarray,
    y: np.ndarray,
    colors: np.ndarray,
    *,
    point_size: float,
    opacity: float,
    background: Image.Image | None,
    dpi: float,
) -> Image.Image:
    """The plotting area at `dpi`: the background, then the points.

    Each point first marks the pixel it falls in; the marks are then widened to the point's
    disc by shifting the whole grid, so the cost depends on the figure's pixels rather than
    on the number of points. Overlaps darken as when stacked: a pixel covered n times has
    opacity 1 - (1 - opacity)^n, in the colour of a point covering it, later points on top.
    """
    scale = dpi / 72
    width = max(1, round(frame.plot_width * scale))
    height = max(1, round(frame.plot_height * scale))
    (x0, x1), (y0, y1) = frame.x_domain, frame.y_domain
    columns = (x - x0) / (x1 - x0) * width
    rows = ((y - y0) if frame.y_down else (y1 - y)) / (y1 - y0) * height
    inside = (columns >= 0) & (columns < width) & (rows >= 0) & (rows < height)
    index = np.asarray(rows[inside], dtype=np.int64) * width + np.asarray(
        columns[inside], dtype=np.int64
    )
    hits = np.bincount(index, minlength=width * height).astype(np.float32).reshape(height, width)
    # Each pixel keeps its latest point: assigning to repeated pixels keeps the last value, and
    # widening keeps the maximum, so later points stay on top.
    latest = np.full(width * height, -1, dtype=np.int64)
    latest[index] = np.arange(len(index))
    latest_grid = latest.reshape(height, width)
    radius = max(point_size * scale / 2, 0.5)
    reach = math.floor(radius)
    counts = np.zeros((height, width), dtype=np.float32)
    top = np.full((height, width), -1, dtype=np.int64)
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            if dx * dx + dy * dy > radius * radius:
                continue
            # Pixels [target] receive the marks at [source], dy rows and dx columns away.
            target = (slice(max(0, dy), height + min(0, dy)), slice(max(0, dx), width + min(0, dx)))
            source = (
                slice(max(0, -dy), height - max(0, dy)),
                slice(max(0, -dx), width - max(0, dx)),
            )
            counts[target] += hits[source]
            np.maximum(top[target], latest_grid[source], out=top[target])
    painted = np.zeros((height, width, 3), dtype=np.uint8)
    covered = top >= 0
    painted[covered] = colors[inside][top[covered]]
    alpha = (1 - (1 - opacity) ** counts)[..., None]
    base = (
        np.asarray(background.convert("RGB").resize((width, height)), dtype=np.float32)
        if background is not None
        else np.full((height, width, 3), 255, dtype=np.float32)
    )
    blended = base * (1 - alpha) + painted.astype(np.float32) * alpha
    return Image.fromarray(blended.round().astype(np.uint8), "RGB")


def background_image(
    frame: Frame,
    image: Image.Image,
    extent: tuple[float, float, float, float],
    dpi: float,
) -> Image.Image:
    """The part of the image inside the data window, resampled to the plotting area."""
    scale = dpi / 72
    width = max(1, round(frame.plot_width * scale))
    height = max(1, round(frame.plot_height * scale))
    (x0, x1), (y0, y1) = frame.x_domain, frame.y_domain
    left, right, top, bottom = extent
    per_column = image.width / (right - left)
    per_row = image.height / (bottom - top)
    # Output pixel (i, j) samples image position (a·i + c, e·j + f).
    a = (x1 - x0) / width * per_column
    c = (x0 - left) * per_column
    if frame.y_down:
        e, f = (y1 - y0) / height * per_row, (y0 - top) * per_row
    else:
        e, f = -(y1 - y0) / height * per_row, (y1 - top) * per_row
    return image.convert("RGB").transform(
        (width, height),
        Image.Transform.AFFINE,
        (a, 0, c, 0, e, f),
        resample=Image.Resampling.BILINEAR,
        fillcolor=(255, 255, 255),
    )


def encode_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=6)
    return buffer.getvalue()


def _text(parent: ET.Element, x: float, y: float, text: str, size: float, **extra: str) -> None:
    element = ET.SubElement(
        parent,
        f"{{{SVG}}}text",
        {"x": f"{x:.2f}", "y": f"{y:.2f}", "font-size": f"{size:g}", "font-family": FONT, **extra},
    )
    element.text = text


def svg(
    frame: Frame,
    png: bytes,
    *,
    title: str | None,
    x_title: str,
    y_title: str,
    legend: dict[str, Any] | None,
) -> bytes:
    ET.register_namespace("", SVG)
    ET.register_namespace("xlink", XLINK)
    root = ET.Element(
        f"{{{SVG}}}svg",
        {
            "width": f"{frame.width:g}pt",
            "height": f"{frame.height:g}pt",
            "viewBox": f"0 0 {frame.width:g} {frame.height:g}",
            "version": "1.1",
        },
    )
    ET.SubElement(
        root,
        f"{{{SVG}}}rect",
        {"width": f"{frame.width:g}", "height": f"{frame.height:g}", "fill": "white"},
    )
    box = {
        "x": f"{frame.left:.2f}",
        "y": f"{frame.top:.2f}",
        "width": f"{frame.plot_width:.2f}",
        "height": f"{frame.plot_height:.2f}",
    }
    ET.SubElement(
        root,
        f"{{{SVG}}}image",
        {
            **box,
            "preserveAspectRatio": "none",
            f"{{{XLINK}}}href": "data:image/png;base64," + base64.b64encode(png).decode(),
        },
    )
    ET.SubElement(
        root, f"{{{SVG}}}rect", {**box, "fill": "none", "stroke": "#333", "stroke-width": "0.6"}
    )
    axes = ET.SubElement(root, f"{{{SVG}}}g", {"stroke": "#333", "stroke-width": "0.6"})
    labels = ET.SubElement(root, f"{{{SVG}}}g", {"fill": "#222"})
    (x0, x1), (y0, y1) = frame.x_domain, frame.y_domain
    bottom = frame.top + frame.plot_height
    x_ticks = nice_ticks(x0, x1)
    for tick in x_ticks:
        position = frame.left + (tick - x0) / (x1 - x0) * frame.plot_width
        ET.SubElement(
            axes,
            f"{{{SVG}}}line",
            {"x1": f"{position:.2f}", "x2": f"{position:.2f}", "y1": f"{bottom:.2f}",
             "y2": f"{bottom + 3:.2f}"},
        )  # fmt: skip
        _text(
            labels, position, bottom + 11, tick_label(tick, x_ticks), 7, **{"text-anchor": "middle"}
        )
    y_ticks = nice_ticks(y0, y1)
    for tick in y_ticks:
        share = (tick - y0) / (y1 - y0)
        position = frame.top + (share if frame.y_down else 1 - share) * frame.plot_height
        ET.SubElement(
            axes,
            f"{{{SVG}}}line",
            {"x1": f"{frame.left - 3:.2f}", "x2": f"{frame.left:.2f}", "y1": f"{position:.2f}",
             "y2": f"{position:.2f}"},
        )  # fmt: skip
        _text(
            labels, frame.left - 5, position + 2.5, tick_label(tick, y_ticks), 7,
            **{"text-anchor": "end"},
        )  # fmt: skip
    _text(
        labels, frame.left + frame.plot_width / 2, bottom + 25, x_title, 8,
        **{"text-anchor": "middle"},
    )  # fmt: skip
    middle = frame.top + frame.plot_height / 2
    _text(
        labels, 12, middle, y_title, 8,
        **{"text-anchor": "middle", "transform": f"rotate(-90 12 {middle:.2f})"},
    )  # fmt: skip
    if title:
        _text(
            labels, frame.left + frame.plot_width / 2, min(14.0, frame.top - 6), title, 9,
            **{"text-anchor": "middle", "font-weight": "bold"},
        )  # fmt: skip
    if legend:
        _legend(root, frame, legend)
    return bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))


def legend_width(legend: dict[str, Any] | None) -> float:
    if legend is None:
        return 0.0
    if legend["type"] == "continuous":
        return 58.0
    longest = max([len(legend["title"])] + [len(item["value"]) for item in legend["categories"]])
    return min(150.0, 26 + longest * 4.2)


def _legend(root: ET.Element, frame: Frame, legend: dict[str, Any]) -> None:
    group = ET.SubElement(root, f"{{{SVG}}}g", {"fill": "#222"})
    left = frame.left + frame.plot_width + 12
    _text(group, left, frame.top + 7, legend["title"], 8, **{"font-weight": "bold"})
    if legend["type"] == "continuous":
        definitions = ET.SubElement(root, f"{{{SVG}}}defs")
        gradient = ET.SubElement(
            definitions,
            f"{{{SVG}}}linearGradient",
            {"id": "point-map-colors", "x1": "0", "x2": "0", "y1": "1", "y2": "0"},
        )
        for index, color in enumerate(VIRIDIS):
            ET.SubElement(
                gradient,
                f"{{{SVG}}}stop",
                {"offset": f"{index / (len(VIRIDIS) - 1):.3f}", "stop-color": color},
            )
        height = min(110.0, frame.plot_height - 16)
        ET.SubElement(
            group,
            f"{{{SVG}}}rect",
            {"x": f"{left:.2f}", "y": f"{frame.top + 14:.2f}", "width": "8",
             "height": f"{height:.2f}", "fill": "url(#point-map-colors)"},
        )  # fmt: skip
        low, high = legend["domain"]
        ticks = nice_ticks(low, high, 3) or [low, high]
        for tick in ticks:
            share = (tick - low) / (high - low) if high > low else 0
            y = frame.top + 14 + (1 - share) * height
            _text(group, left + 11, y + 2.5, tick_label(tick, ticks), 7)
        return
    row = 10.0
    fits = max(1, int((frame.plot_height - 12) // row))
    shown = (
        legend["categories"]
        if len(legend["categories"]) <= fits
        else legend["categories"][: fits - 1]
    )
    for index, item in enumerate(shown):
        y = frame.top + 17 + index * row
        ET.SubElement(
            group,
            f"{{{SVG}}}circle",
            {"cx": f"{left + 3:.2f}", "cy": f"{y - 2.5:.2f}", "r": "2.8", "fill": item["color"]},
        )
        _text(group, left + 10, y, item["value"], 7)
    hidden = len(legend["categories"]) - len(shown)
    if hidden:
        _text(group, left, frame.top + 17 + len(shown) * row, f"+{hidden} more", 7)
