"""Compose saved panel drawings and images into one page SVG in millimetre units."""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping
from xml.etree import ElementTree as ET

from vis_platform_backend.contracts.figure_composition_content import FigureCompositionContent
from vis_platform_backend.contracts.figure_compositions import PanelFrame
from vis_platform_backend.domain.figure_compositions import MM_PER_INCH

SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
MM_PER_POINT = MM_PER_INCH / 72
CSS_PX_PER_MM = 96 / MM_PER_INCH
# Label baseline below the panel's top edge, as a fraction of the label size.
LABEL_BASELINE = 0.8
_PLACEMENT = frozenset({"id", "x", "y", "width", "height", "viewBox", "preserveAspectRatio"})
_LOCAL_URL = re.compile(r"url\(\s*(['\"]?)#([^'\")\s]+)\1\s*\)")

# A plot's validated SVG root, or PNG bytes for an uploaded image.
PanelSource = ET.Element | bytes


def _number(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _isolate_ids(root: ET.Element, prefix: str) -> None:
    """Prefix IDs so identical clip paths or glyphs from different panels cannot collide."""
    for node in root.iter():
        for key, value in list(node.attrib.items()):
            if key == "id":
                node.set(key, prefix + value)
            elif key.split("}")[-1] == "href" and value.startswith("#"):
                node.set(key, "#" + prefix + value[1:])
            elif "url(" in value:
                node.set(key, _LOCAL_URL.sub(lambda match: f"url(#{prefix}{match[2]})", value))


def compose_page(
    content: FigureCompositionContent,
    page_height_mm: float,
    frames: Mapping[str, PanelFrame],
    labels: Mapping[str, str | None],
    sources: Mapping[str, PanelSource],
) -> bytes:
    """Panels without a source, such as empty slots, are left out with their labels."""
    width = _number(content.page.width_mm)
    height = _number(page_height_mm)
    page = ET.Element(
        f"{{{SVG}}}svg",
        {"width": f"{width}mm", "height": f"{height}mm", "viewBox": f"0 0 {width} {height}"},
    )
    ET.SubElement(page, f"{{{SVG}}}rect", {"width": width, "height": height, "fill": "white"})
    for index, panel in enumerate(content.panels):
        if panel.id not in sources:
            continue
        frame = frames[panel.id]
        placement = {
            "x": _number(frame.x_mm),
            "y": _number(frame.y_mm),
            "width": _number(frame.width_mm),
            "height": _number(frame.height_mm),
        }
        source = sources[panel.id]
        if isinstance(source, bytes):
            encoded = base64.b64encode(source).decode("ascii")
            ET.SubElement(
                page,
                f"{{{SVG}}}image",
                {
                    **placement,
                    "preserveAspectRatio": "none",
                    f"{{{XLINK}}}href": "data:image/png;base64," + encoded,
                },
            )
            continue
        _isolate_ids(source, f"panel{index}-")
        view_box = source.get("viewBox") or (
            f"0 0 {_number(frame.width_mm / panel.scale * CSS_PX_PER_MM)} "
            f"{_number(frame.height_mm / panel.scale * CSS_PX_PER_MM)}"
        )
        inherited = {key: value for key, value in source.attrib.items() if key not in _PLACEMENT}
        nested = ET.SubElement(
            page, f"{{{SVG}}}svg", {**inherited, **placement, "viewBox": view_box}
        )
        nested.extend(list(source))
    style = content.labels
    size = style.size_pt * MM_PER_POINT
    for panel in content.panels:
        label = labels[panel.id]
        if label is None or panel.id not in sources:
            continue
        frame = frames[panel.id]
        text = ET.SubElement(
            page,
            f"{{{SVG}}}text",
            {
                "x": _number(frame.x_mm),
                "y": _number(frame.y_mm + size * LABEL_BASELINE),
                "font-family": f"{style.font_family}, Helvetica, sans-serif",
                "font-size": _number(size),
                "font-weight": "bold" if style.bold else "normal",
                "fill": "#000000",
            },
        )
        text.text = label
    ET.register_namespace("", SVG)
    ET.register_namespace("xlink", XLINK)
    data: bytes = ET.tostring(page, encoding="utf-8", xml_declaration=True)
    return data
