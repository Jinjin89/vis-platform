from __future__ import annotations

import hashlib
import io
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from cairosvg.surface import PDFSurface, PNGSurface  # type: ignore[import-untyped]
from PIL import Image

from vis_platform_backend.contracts.figures import FigureExportFormat, FigureSize
from vis_platform_backend.contracts.plot_runs import PlotResultSummary
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.execution.runner import RExecutionError
from vis_platform_backend.infrastructure.database import Repository
from vis_platform_backend.services.figure_svg import read_svg

SVG = "http://www.w3.org/2000/svg"
PNG_DPI = 300
MEDIA_TYPES = {
    FigureExportFormat.PNG: "image/png",
    FigureExportFormat.PDF: "application/pdf",
    FigureExportFormat.SVG: "image/svg+xml",
}


@dataclass(frozen=True)
class FigureDownload:
    path: Path
    media_type: str
    filename: str


def _no_external_resources(_url: str, _resource_type: str) -> bytes:
    raise ValueError("Figure export cannot load external resources.")


def _legacy_size(root: ET.Element) -> FigureSize:
    def inches(value: str) -> float:
        match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(in|pt|px|mm|cm|pc)?\s*", value)
        if match is None:
            raise ValueError("The saved figure has no usable dimensions.")
        scale = {"in": 1, "pt": 72, "px": 96, "mm": 25.4, "cm": 2.54, "pc": 6}
        return round(float(match[1]) / scale[match[2] or "px"], 2)

    if root.get("width") and root.get("height"):
        return FigureSize(width=inches(root.attrib["width"]), height=inches(root.attrib["height"]))
    box = [float(value) for value in root.attrib["viewBox"].replace(",", " ").split()]
    if len(box) != 4:
        raise ValueError("The saved figure has no usable dimensions.")
    return FigureSize(width=round(box[2] / 96, 2), height=round(box[3] / 96, 2))


def _remove_legacy_demo_frame(root: ET.Element) -> None:
    """Remove presentation chrome from our old illustration template, outside the plot body."""
    if root.get("data-demo") != "true" or root.find(".//*[@data-role='plot-body']") is None:
        return
    for child in list(root):
        if child.tag == f"{{{SVG}}}rect" and child.get("data-role") != "figure-background":
            root.remove(child)
    frame = root.find(f"{{{SVG}}}g")
    if frame is not None:
        for child in list(frame):
            if child.tag in {f"{{{SVG}}}{tag}" for tag in ("rect", "circle", "line")} or (
                child.tag == f"{{{SVG}}}text"
                and (child.text or "").strip() == "VIS PLATFORM · DEMO FIGURE"
            ):
                frame.remove(child)
    if root.find("./*[@data-role='figure-background']") is None:
        box = root.get("viewBox", "0 0 960 560").replace(",", " ").split()
        root.insert(
            0,
            ET.Element(
                f"{{{SVG}}}rect",
                {
                    "data-role": "figure-background",
                    "x": box[0],
                    "y": box[1],
                    "width": box[2],
                    "height": box[3],
                    "fill": "white",
                },
            ),
        )


class FigureExporter:
    def __init__(self, repository: Repository, artifact_root: Path) -> None:
        self.repository = repository
        self.artifact_root = artifact_root.resolve()
        self._slots = threading.BoundedSemaphore(2)

    def export(
        self, project_id: str, plot_id: str, version_id: str, format: FigureExportFormat
    ) -> FigureDownload:
        run_id = self.repository.run_id_for_version(project_id, plot_id, version_id)
        record = self.repository.get_run(run_id) if run_id else None
        if record is None or record["result"] is None:
            raise DataError("The selected figure version was not found.", "NOT_FOUND", 404)
        result = PlotResultSummary.model_validate(record["result"])
        artifact = self.repository.get_artifact(result.preview.artifact_id)
        if artifact is None:
            raise DataError("The saved figure was not found.", "NOT_FOUND", 404)
        source = Path(artifact["storage_path"]).resolve()
        if not source.is_relative_to(self.artifact_root) or not source.is_file():
            raise DataError("The saved figure is unavailable.", "NOT_FOUND", 404)
        try:
            root = read_svg(source)
            size = result.figure_size or _legacy_size(root)
            if result.execution_mode == "demo":
                _remove_legacy_demo_frame(root)
            root.set("width", f"{size.width:g}in")
            root.set("height", f"{size.height:g}in")
            ET.register_namespace("", SVG)
            ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
            data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            # Content addressing keeps exports aligned with this immutable figure and export policy.
            key = hashlib.sha256(b"figure-export-v1:300:white:" + data).hexdigest()
            directory = self.artifact_root / "exports" / key
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / f"figure.{format.value}"
            with self._slots:
                if not destination.is_file():
                    with tempfile.TemporaryDirectory(dir=directory) as temporary:
                        target = Path(temporary) / "figure.tmp"
                        if format is FigureExportFormat.SVG:
                            target.write_bytes(data)
                        elif format is FigureExportFormat.PDF:
                            PDFSurface.convert(
                                bytestring=data,
                                write_to=str(target),
                                background_color="white",
                                url_fetcher=_no_external_resources,
                            )
                        else:
                            png = PNGSurface.convert(
                                bytestring=data,
                                dpi=PNG_DPI,
                                output_width=round(size.width * PNG_DPI),
                                output_height=round(size.height * PNG_DPI),
                                background_color="white",
                                url_fetcher=_no_external_resources,
                            )
                            with Image.open(io.BytesIO(png)) as raster:
                                raster.save(target, format="PNG", dpi=(PNG_DPI, PNG_DPI))
                        if target.stat().st_size > 64 * 1024 * 1024:
                            raise ValueError("The figure exceeds the export size limit.")
                        target.replace(destination)
        except (RExecutionError, ValueError, KeyError, OSError) as error:
            raise DataError(
                "This figure could not be exported. Please retry or choose another format.",
                "FIGURE_EXPORT_FAILED",
                422,
            ) from error
        stem = re.sub(r"[^a-zA-Z0-9]+", "-", result.title or "figure").strip("-")[:70] or "figure"
        return FigureDownload(
            path=destination,
            media_type=MEDIA_TYPES[format],
            filename=f"{stem}-{version_id.removeprefix('version_')[:8]}.{format.value}",
        )
