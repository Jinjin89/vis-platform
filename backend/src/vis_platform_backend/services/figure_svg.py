import re
from pathlib import Path
from xml.etree import ElementTree

from vis_platform_backend.contracts.figures import FigureSize
from vis_platform_backend.execution.runner import RExecutionError


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
                key.split("}")[-1] == "href" and not value.startswith("#")
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
