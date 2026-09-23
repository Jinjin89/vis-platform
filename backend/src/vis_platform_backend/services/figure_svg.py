import re
from pathlib import Path
from xml.etree import ElementTree

from vis_platform_backend.contracts.figures import FigureSize
from vis_platform_backend.execution.runner import RExecutionError

EMBEDDED_PNG = "data:image/png;base64,"


def read_svg(path: Path) -> ElementTree.Element:
    if path.stat().st_size > 10 * 1024 * 1024:
        raise RExecutionError("The figure exceeds the preview size limit.")
    raw = path.read_bytes()
    if b"<!ENTITY" in raw.upper() or b"<!DOCTYPE" in raw.upper():
        raise RExecutionError("The figure contains unsupported SVG content.")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as error:
        raise RExecutionError("The renderer did not produce a valid SVG figure.") from error
    if root.tag.split("}")[-1] != "svg" or len(list(root.iter())) < 3:
        raise RExecutionError("The renderer produced an empty or invalid figure.")
    for node in root.iter():
        if node.tag.split("}")[-1] in {"script", "style", "foreignObject", "iframe"}:
            raise RExecutionError("The figure contains unsupported active content.")
        for key, value in node.attrib.items():
            if any(
                not target.strip(" \"'").startswith("#")
                for target in re.findall(r"url\(([^)]*)\)", value, flags=re.IGNORECASE)
            ):
                raise RExecutionError(
                    "The figure contains an unsupported external style reference."
                )
            if key.lower().startswith("on") or (
                key.split("}")[-1] == "href"
                and not value.startswith("#")
                # Embedded PNG data, as in point maps' raster layers, loads nothing external.
                and not value.startswith(EMBEDDED_PNG)
            ):
                raise RExecutionError("The figure contains an unsupported external reference.")
    return root


def validate_svg(path: Path, size: FigureSize | None = None) -> None:
    root = read_svg(path)
    if size is not None:
        root.set("width", f"{size.width:g}in")
        root.set("height", f"{size.height:g}in")
        ElementTree.register_namespace("", "http://www.w3.org/2000/svg")
        ElementTree.register_namespace("xlink", "http://www.w3.org/1999/xlink")
        path.write_bytes(ElementTree.tostring(root, encoding="utf-8", xml_declaration=True))


# R's SVG device draws text as outlines, which cannot be measured. Its smallest default
# text (axis annotation) is close to this size at the drawing's natural size.
ASSUMED_SMALLEST_TEXT_PT = 8.0
_FONT_SIZE = re.compile(r"font-size\s*:\s*([0-9.]+)\s*(px|pt)?", re.IGNORECASE)
_LENGTH = re.compile(r"\s*([0-9.]+)\s*(px|pt)?\s*$", re.IGNORECASE)


def _font_size(node: ElementTree.Element) -> tuple[float, str] | None:
    style = _FONT_SIZE.search(node.get("style", ""))
    match = style or _LENGTH.match(node.get("font-size", ""))
    return (float(match[1]), (match[2] or "px").lower()) if match else None


def smallest_text_pt(root: ElementTree.Element, width_in: float) -> tuple[float, bool]:
    """The smallest text size in points at the drawing's natural size.

    The flag is false when the drawing has no measurable text and the size is assumed.
    """
    box = root.get("viewBox", "").replace(",", " ").split()
    units_per_inch = float(box[2]) / width_in if len(box) == 4 else 96.0
    sizes: list[float] = []

    def walk(node: ElementTree.Element, inherited: tuple[float, str] | None) -> None:
        size = _font_size(node) or inherited
        if node.tag.split("}")[-1] == "text" and "".join(node.itertext()).strip() and size:
            # CSS points are 4/3 of a user-space pixel; user units map to inches by the viewBox.
            units = size[0] * (4 / 3 if size[1] == "pt" else 1)
            sizes.append(units * 72 / units_per_inch)
        for child in node:
            walk(child, size)

    walk(root, None)
    return (min(sizes), True) if sizes else (ASSUMED_SMALLEST_TEXT_PT, False)
