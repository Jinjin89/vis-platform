"""Point maps: a table's rows drawn at two coordinates, at any size, without R.

The platform reads the named columns (no generated code runs), saves them as the analysis
result, and draws the saved figure in Python. Beside the drawing it keeps what an interactive
view needs: the positions and colours as binary columns, the image under them, and the view's
description.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pv
import pyarrow.parquet as pq
from PIL import Image

from vis_platform_backend.contracts.artifacts import ArtifactReference
from vis_platform_backend.contracts.datasets import (
    AnalysisResult,
    ObjectDescription,
    ObjectReference,
)
from vis_platform_backend.contracts.figures import FigureSize
from vis_platform_backend.contracts.parameters import ParameterValue
from vis_platform_backend.contracts.point_maps import PointMapPlan
from vis_platform_backend.contracts.render_controls import (
    RenderBooleanControl,
    RenderNumberControl,
)
from vis_platform_backend.contracts.research import ResearchPlan
from vis_platform_backend.data.columnar import profile_table
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.data.profiling import content_hash
from vis_platform_backend.data.service import DatasetService
from vis_platform_backend.domain.plot_marks import PLOT_MAP
from vis_platform_backend.infrastructure.database import Repository, utc_now
from vis_platform_backend.services import point_map_render as render
from vis_platform_backend.services.figure_controls import figure_controls, resolve_figure_size

RENDERER = "point-map-v1"
POINT_VIEW = "point-view.json"
POINT_COLUMNS = "points.bin"
VIEW_IMAGE = "view-image.png"
# Everything a saved version keeps beside its drawing; restores copy them with it.
VIEW_FILES = (PLOT_MAP, POINT_VIEW, POINT_COLUMNS, VIEW_IMAGE)
MAX_CATEGORIES = 200
AUTO_CONTINUOUS = 30
VIEW_IMAGE_LONG_SIDE = 4096
# Cells read to compare a selection with the whole table (rows × columns).
SUMMARY_BUDGET = 20_000_000


@dataclass(frozen=True)
class Points:
    rows: np.ndarray  # row index in the source table
    x: np.ndarray
    y: np.ndarray
    color: np.ndarray | None  # category code or value; NaN when missing
    meta: dict[str, Any]


@dataclass(frozen=True)
class PointMapExecution:
    result: AnalysisResult
    preview: Path
    spec: dict[str, Any]


def default_point_size(count: int) -> float:
    return 3.0 if count <= 5_000 else 1.5 if count <= 50_000 else 0.8 if count <= 500_000 else 0.4


def point_map_controls(count: int, has_image: bool) -> list[Any]:
    controls: list[Any] = [
        RenderNumberControl(
            id="point_size",
            label="Point size",
            group="points",
            value=default_point_size(count),
            minimum=0.1,
            maximum=8,
            step=0.1,
            unit="pt",
            input_mode="slider",
        ),
        RenderNumberControl(
            id="point_opacity",
            label="Point opacity",
            group="points",
            value=1.0 if count <= 50_000 else 0.7,
            minimum=0.05,
            maximum=1,
            step=0.05,
            input_mode="slider",
        ),
    ]
    if has_image:
        controls.append(
            RenderBooleanControl(id="show_image", label="Show image", group="points", value=True)
        )
    return controls


class PointMapService:
    def __init__(self, data: DatasetService, repository: Repository, artifact_root: Path) -> None:
        self.data, self.repository = data, repository
        self.artifact_root = artifact_root.resolve()

    # Execution

    async def execute(
        self,
        project_id: str,
        run_id: str,
        plan: ResearchPlan,
        parameters: dict[str, ParameterValue] | None = None,
    ) -> PointMapExecution:
        assert plan.point_map is not None and plan.figure_size is not None
        if plan.reuse_result_id:
            result = self.data.store.get_result(project_id, plan.reuse_result_id)
            if result is None:
                raise DataError("The saved point positions were not found.", "NOT_FOUND", 404)
        else:
            result = await self._project(project_id, run_id, plan)
        points = self._points(project_id, result)
        if not plan.controls:
            controls, groups = figure_controls(
                point_map_controls(len(points.x), points.meta["image"] is not None),
                plan.control_groups,
                plan.figure_size,
            )
            plan = ResearchPlan.model_validate(
                {
                    **plan.model_dump(),
                    "controls": [control.model_dump() for control in controls],
                    "control_groups": [group.model_dump() for group in groups],
                }
            )
        values: dict[str, Any] = {control.id: control.value for control in plan.controls}
        values.update(parameters or {})
        assert plan.figure_size is not None
        size = resolve_figure_size(values, plan.figure_size)
        plan = plan.model_copy(update={"figure_size": size})
        directory = self.artifact_root / run_id
        directory.mkdir(parents=True, exist_ok=True)
        image = await self._image(project_id, points.meta["image"])
        spec = plan.point_map
        assert spec is not None
        preview = self._draw(directory, plan, spec, points, size, values, image)
        return PointMapExecution(
            result=result,
            preview=preview,
            spec={
                "figure_size": size.model_dump(mode="json"),
                "renderer": RENDERER,
                "result_id": result.result_id,
                "plan": plan.model_dump(mode="json"),
                "parameters": values,
            },
        )

    async def _project(self, project_id: str, run_id: str, plan: ResearchPlan) -> AnalysisResult:
        spec = plan.point_map
        assert spec is not None
        aliases = {item.alias: item.reference for item in plan.inputs}
        source, path, format_name = await self.data.materialize(project_id, aliases[spec.table])
        if source.kind != "table" or format_name not in {"csv", "parquet"}:
            raise DataError(
                "A point map draws a table stored as CSV or Parquet.", "INVALID_POINT_MAP", 422
            )
        names = list(dict.fromkeys([spec.x, spec.y, *([spec.color] if spec.color else [])]))
        known = {column.name for column in source.columns}
        if missing := [name for name in names if name not in known]:
            raise DataError(
                f"The table has no column {', '.join(repr(name) for name in missing)}.",
                "INVALID_POINT_MAP",
                422,
            )
        image_reference = aliases[spec.image.input] if spec.image else None
        if image_reference is not None:
            image, _, _ = await self.data.materialize(project_id, image_reference)
            if image.kind != "image":
                raise DataError(
                    "A point map's image must be an image object.", "INVALID_POINT_MAP", 422
                )
        table = read_columns(path, format_name, names)
        x, y = numeric(table, spec.x), numeric(table, spec.y)
        kept = np.flatnonzero(np.isfinite(x) & np.isfinite(y))
        if not len(kept):
            raise DataError("No rows have numeric x and y values.", "INVALID_POINT_MAP", 422)
        color, color_meta = colors(table, spec) if spec.color else (None, None)
        x_kept, y_kept = x[kept], y[kept]
        meta = {
            "source": aliases[spec.table].model_dump(mode="json"),
            "image": image_reference.model_dump(mode="json") if image_reference else None,
            "plan": spec.model_dump(mode="json"),
            "count": len(kept),
            "dropped": table.num_rows - len(kept),
            "x_range": [float(x_kept.min()), float(x_kept.max())],
            "y_range": [float(y_kept.min()), float(y_kept.max())],
            "color": color_meta,
        }
        result_id = f"result_{uuid4().hex}"
        directory = self.artifact_root / run_id / result_id
        directory.mkdir(parents=True)
        positions = pa.table(
            {
                "source_row": pa.array(kept, pa.int64()),
                "x": pa.array(x_kept.astype(np.float32)),
                "y": pa.array(y_kept.astype(np.float32)),
                **(
                    {"color": pa.array(color[kept].astype(np.float32))} if color is not None else {}
                ),
            }
        )
        target = directory / "points.parquet"
        pq.write_table(positions, target, compression="zstd")
        artifact_id = f"artifact_{uuid4().hex}"
        self.repository.create_artifact(
            artifact_id=artifact_id,
            run_id=run_id,
            media_type="application/vnd.apache.parquet",
            filename=target.name,
            storage_path=target,
        )
        artifact = ArtifactReference(
            artifact_id=artifact_id,
            role="data",
            media_type="application/vnd.apache.parquet",
            href=f"/api/v1/artifacts/{artifact_id}",
            description="Drawn positions and colours, with each point's source row.",
        )
        digest = content_hash(target)
        descriptor = ObjectDescription(
            object_id=f"object_{uuid4().hex}",
            revision_id=result_id,
            owner_id=result_id,
            owner_kind="analysis_result",
            name="Point map positions",
            description=(
                f"{len(kept):,} points from {source.name}"
                + (
                    f"; {table.num_rows - len(kept):,} rows lacked numeric positions."
                    if len(kept) < table.num_rows
                    else "."
                )
            ),
            description_origin="parser",
            format="parquet",
            dimensions=[positions.num_rows, positions.num_columns],
            columns=profile_table(positions),
            capabilities=["inspect", "materialize"],
            content_hash=digest,
            artifact=artifact,
            extensions={"output_key": "points", "point_map": meta},
        )
        owner = self.data.store.object_owner(project_id, source.revision_id)
        result = AnalysisResult(
            contains_demo_data=bool(getattr(owner, "contains_demo_data", False)),
            result_id=result_id,
            project_id=project_id,
            run_id=run_id,
            name=plan.title,
            description=plan.description,
            created_at=utc_now(),
            inputs=[aliases[spec.table], *([image_reference] if image_reference else [])],
            objects=[descriptor],
            artifacts=[artifact],
            code_hash=hashlib.sha256(spec.model_dump_json().encode()).hexdigest(),
            environment={"renderer": RENDERER, "pyarrow": pa.__version__, "numpy": np.__version__},
            random_seed=plan.random_seed,
        )
        self.data.store.save_result(
            result,
            {
                descriptor.object_id: {
                    "path": str(target),
                    "format": "parquet",
                    "hash": digest,
                    "key": "points",
                }
            },
        )
        return result

    def _points(self, project_id: str, result: AnalysisResult) -> Points:
        descriptor = result.objects[0]
        meta = descriptor.extensions.get("point_map")
        bindings = self.data.store.bindings(project_id, result.result_id) or {}
        binding = bindings.get(descriptor.object_id)
        if not isinstance(meta, dict) or not binding:
            raise DataError("The saved result is not a point map.", "INVALID_POINT_MAP", 422)
        table = pq.read_table(binding["path"])
        return Points(
            rows=table.column("source_row").to_numpy(),
            x=table.column("x").to_numpy(),
            y=table.column("y").to_numpy(),
            color=table.column("color").to_numpy() if "color" in table.column_names else None,
            meta=meta,
        )

    async def _image(
        self, project_id: str, reference: dict[str, Any] | None
    ) -> tuple[Image.Image, dict[str, Any]] | None:
        if reference is None:
            return None
        descriptor, path, _ = await self.data.materialize(
            project_id, ObjectReference.model_validate(reference)
        )
        with Image.open(path) as source:
            source.load()
            return source.convert("RGB"), dict(descriptor.extensions)

    # Drawing

    def _draw(
        self,
        directory: Path,
        plan: ResearchPlan,
        spec: PointMapPlan,
        points: Points,
        size: FigureSize,
        values: dict[str, Any],
        image: tuple[Image.Image, dict[str, Any]] | None,
    ) -> Path:
        extent = image_extent(spec, image[1]) if image else None
        x_domain = padded(points.meta["x_range"], extent[:2] if extent else None)
        y_domain = padded(points.meta["y_range"], extent[2:] if extent else None)
        legend = legend_of(spec, points.meta["color"])
        frame = render.layout(
            size.width,
            size.height,
            x_domain,
            y_domain,
            y_down=spec.y_axis == "down",
            equal_aspect=spec.equal_aspect,
            titled=bool(plan.title),
            legend_width=render.legend_width(legend),
        )
        point_colors = colors_of(points, points.meta["color"])
        show_image = bool(values.get("show_image", True)) and image is not None
        for dpi in (render.PRINT_DPI, 220, 150):
            background = (
                render.background_image(frame, image[0], extent, dpi)
                if show_image and image and extent
                else None
            )
            png = render.encode_png(
                render.raster(
                    frame,
                    points.x,
                    points.y,
                    point_colors,
                    point_size=float(values["point_size"]),
                    opacity=float(values["point_opacity"]),
                    background=background,
                    dpi=dpi,
                )
            )
            if len(png) <= render.RASTER_BUDGET:
                break
        preview = directory / "preview.svg"
        preview.write_bytes(
            render.svg(
                frame,
                png,
                title=plan.title,
                x_title=spec.x_title or spec.x,
                y_title=spec.y_title or spec.y,
                legend=legend,
            )
        )
        (directory / PLOT_MAP).write_text(json.dumps(frame.plot_map()), encoding="utf-8")
        columns = [points.x.astype("<f4"), points.y.astype("<f4")]
        if points.color is not None:
            columns.append(points.color.astype("<f4"))
        (directory / POINT_COLUMNS).write_bytes(b"".join(column.tobytes() for column in columns))
        if image and extent:
            view = image[0].copy()
            view.thumbnail((VIEW_IMAGE_LONG_SIDE, VIEW_IMAGE_LONG_SIDE), Image.Resampling.LANCZOS)
            view.save(directory / VIEW_IMAGE, format="PNG", compress_level=6)
        (directory / POINT_VIEW).write_text(
            json.dumps(
                {
                    "title": plan.title,
                    "count": len(points.x),
                    "dropped": points.meta["dropped"],
                    "x": {"field": spec.x, "title": spec.x_title or spec.x, "domain": x_domain},
                    "y": {
                        "field": spec.y,
                        "title": spec.y_title or spec.y,
                        "domain": y_domain,
                        "direction": spec.y_axis,
                    },
                    "equal_aspect": spec.equal_aspect,
                    "color": legend,
                    "columns": ["x", "y", *(["color"] if points.color is not None else [])],
                    "point_size": float(values["point_size"]),
                    "opacity": float(values["point_opacity"]),
                    "image": {"extent": list(extent), "visible": show_image}
                    if image and extent
                    else None,
                }
            ),
            encoding="utf-8",
        )
        return preview

    # Reading a saved version

    def version_directory(self, project_id: str, version_id: str) -> Path:
        result = self.repository.result_for_version(version_id, project_id)
        artifact = (
            self.repository.get_artifact(result["preview"]["artifact_id"]) if result else None
        )
        directory = Path(artifact["storage_path"]).resolve().parent if artifact else None
        if (
            directory is None
            or not directory.is_relative_to(self.artifact_root)
            or not (directory / POINT_VIEW).is_file()
        ):
            raise DataError("This plot version has no point view.", "NOT_FOUND", 404)
        return directory

    def view(self, project_id: str, version_id: str) -> dict[str, Any]:
        directory = self.version_directory(project_id, version_id)
        return dict(json.loads((directory / POINT_VIEW).read_text(encoding="utf-8")))

    def positions(self, directory: Path) -> tuple[np.ndarray, np.ndarray]:
        view = json.loads((directory / POINT_VIEW).read_text(encoding="utf-8"))
        data = np.fromfile(directory / POINT_COLUMNS, dtype="<f4")
        count = int(view["count"])
        return data[:count], data[count : 2 * count]

    async def summarize(
        self, project_id: str, version_id: str, indices: np.ndarray, *, single: bool
    ) -> dict[str, Any]:
        """What a clicked point or a dragged area holds, read from the full source table.

        Indices are positions in the drawn order. One point gives its values; an area gives a
        count, its make-up by colour, the numeric columns that differ most from the whole
        table, and a few example rows.
        """
        result = self.repository.result_for_version(version_id, project_id)
        assert result is not None
        analysis = AnalysisResult.model_validate(result["analysis_results"][0])
        points = self._points(project_id, analysis)
        meta = points.meta
        source, path, format_name = await self.data.materialize(
            project_id, ObjectReference.model_validate(meta["source"])
        )
        spec = PointMapPlan.model_validate(meta["plan"])
        rows = points.rows[indices]
        first = [spec.x, spec.y, *([spec.color] if spec.color else [])]
        names = list(dict.fromkeys([*first, *(column.name for column in source.columns)]))
        if single:
            table = read_columns(path, format_name, names[:24]).take(pa.array(rows[:1]))
            return {
                "source_row": int(rows[0]),
                "values": {
                    name: _plain(table.column(name)[0].as_py()) for name in table.column_names
                },
            }
        total = int(source.dimensions[0]) if source.dimensions else len(points.x)
        summary: dict[str, Any] = {
            "count": int(len(rows)),
            "share_of_points": round(len(rows) / max(1, len(points.x)), 4),
        }
        if not len(rows):
            return summary
        if spec.color and points.color is not None and meta["color"]:
            codes = points.color[indices]
            if meta["color"]["type"] == "categorical":
                present = codes[np.isfinite(codes)].astype(np.int64)
                counts = np.bincount(present, minlength=len(meta["color"]["categories"]))
                order = np.argsort(-counts)[:10]
                summary["by_" + spec.color] = [
                    {
                        "value": meta["color"]["categories"][index],
                        "count": int(counts[index]),
                        "share": round(float(counts[index]) / len(rows), 4),
                    }
                    for index in order
                    if counts[index]
                ]
            else:
                finite = codes[np.isfinite(codes)]
                if len(finite):
                    summary[spec.color] = {
                        "mean": _round(float(finite.mean())),
                        "median": _round(float(np.median(finite))),
                        "minimum": _round(float(finite.min())),
                        "maximum": _round(float(finite.max())),
                    }
        numeric_names = [
            column.name
            for column in source.columns
            if column.data_type == "number" and column.name not in {spec.x, spec.y}
        ]
        budget = max(2, SUMMARY_BUDGET // max(1, total))
        compared = numeric_names[:budget]
        if compared:
            table = read_columns(path, format_name, compared)
            selected = np.zeros(table.num_rows, dtype=bool)
            selected[rows] = True
            differences: list[dict[str, Any]] = []
            for name in compared:
                values = numeric(table, name)
                finite = np.isfinite(values)
                overall = values[finite]
                inside = values[selected & finite]
                if len(overall) < 2 or not len(inside) or overall.std() == 0:
                    continue
                differences.append(
                    {
                        "column": name,
                        "selection_mean": _round(float(inside.mean())),
                        "overall_mean": _round(float(overall.mean())),
                        "difference_in_sd": _round(
                            float((inside.mean() - overall.mean()) / overall.std())
                        ),
                    }
                )
            differences.sort(key=lambda item: -abs(float(item["difference_in_sd"])))
            summary["most_different_columns"] = differences[:8]
            summary["columns_compared"] = f"{len(compared)} of {len(numeric_names)}"
        examples = rows[np.linspace(0, len(rows) - 1, num=min(5, len(rows))).astype(np.int64)]
        table = read_columns(path, format_name, names[:10]).take(pa.array(examples))
        summary["example_rows"] = [
            {name: _plain(value) for name, value in row.items()} for row in table.to_pylist()
        ]
        return summary


def read_columns(path: Path, format_name: str, names: list[str]) -> pa.Table:
    if format_name == "parquet":
        return pq.read_table(path, columns=names)
    return pv.read_csv(
        path,
        convert_options=pv.ConvertOptions(include_columns=names, strings_can_be_null=True),
    )


def numeric(table: pa.Table, name: str) -> np.ndarray:
    column = table.column(name)
    if not (pa.types.is_integer(column.type) or pa.types.is_floating(column.type)):
        raise DataError(f"Column {name!r} is not numeric.", "INVALID_POINT_MAP", 422)
    return np.asarray(
        pc.cast(column, pa.float64()).to_numpy(zero_copy_only=False), dtype=np.float64
    )


def colors(table: pa.Table, spec: PointMapPlan) -> tuple[np.ndarray, dict[str, Any]]:
    """Category codes or values, and how they map to colours."""
    assert spec.color is not None
    column = table.column(spec.color)
    is_number = pa.types.is_integer(column.type) or pa.types.is_floating(column.type)
    kind = spec.color_type
    if kind == "auto":
        many = int(pc.count_distinct(column).as_py()) > AUTO_CONTINUOUS
        kind = "continuous" if is_number and many else "categorical"
    if kind == "continuous":
        if not is_number:
            raise DataError(
                f"Column {spec.color!r} is not numeric, so it cannot colour continuously.",
                "INVALID_POINT_MAP",
                422,
            )
        values = numeric(table, spec.color)
        finite = values[np.isfinite(values)]
        low, high = (float(finite.min()), float(finite.max())) if len(finite) else (0.0, 1.0)
        return values, {"type": "continuous", "domain": [low, high]}
    encoded = pc.dictionary_encode(column).combine_chunks()
    labels = [_label(value) for value in encoded.dictionary.to_pylist()]
    if len(labels) > MAX_CATEGORIES:
        raise DataError(
            f"Column {spec.color!r} has {len(labels):,} categories; colour by a column with at "
            f"most {MAX_CATEGORIES}, or by a numeric column continuously.",
            "INVALID_POINT_MAP",
            422,
        )
    order = sorted(range(len(labels)), key=lambda index: _natural(labels[index]))
    position = np.empty(len(labels), dtype=np.float64)
    position[order] = np.arange(len(labels))
    indices = encoded.indices.to_numpy(zero_copy_only=False)
    codes = np.full(len(indices), np.nan)
    valid = ~np.asarray(encoded.indices.is_null().to_numpy(zero_copy_only=False), dtype=bool)
    codes[valid] = position[indices[valid].astype(np.int64)]
    return codes, {"type": "categorical", "categories": [labels[index] for index in order]}


def colors_of(points: Points, color: dict[str, Any] | None) -> np.ndarray:
    count = len(points.x)
    if points.color is None or color is None:
        return np.tile(np.array(render.rgb(render.CATEGORICAL[0]), dtype=np.uint8), (count, 1))
    if color["type"] == "continuous":
        return render.ramp(points.color.astype(np.float64), *color["domain"])
    palette = np.array(
        [render.rgb(item) for item in render.category_colors(len(color["categories"]))]
        + [render.MISSING],
        dtype=np.uint8,
    )
    codes = np.where(np.isfinite(points.color), points.color, len(color["categories"]))
    return palette[codes.astype(np.int64)]


def legend_of(spec: PointMapPlan, color: dict[str, Any] | None) -> dict[str, Any] | None:
    if not spec.color or color is None:
        return None
    title = spec.color_title or spec.color
    if color["type"] == "continuous":
        return {
            "type": "continuous",
            "field": spec.color,
            "title": title,
            "domain": color["domain"],
            "stops": render.VIRIDIS,
        }
    return {
        "type": "categorical",
        "field": spec.color,
        "title": title,
        "categories": [
            {"value": value, "color": hue}
            for value, hue in zip(
                color["categories"],
                render.category_colors(len(color["categories"])),
                strict=True,
            )
        ],
        "missing_color": "#bdbdbd",
    }


def image_extent(
    spec: PointMapPlan, extensions: dict[str, Any]
) -> tuple[float, float, float, float]:
    """Left, right, and the y of the image's first and last rows, in data units."""
    assert spec.image is not None
    width = float(extensions["pixel_width"]) * spec.image.units_per_pixel
    height = float(extensions["pixel_height"]) * spec.image.units_per_pixel
    left, top = spec.image.origin
    return (left, left + width, top, top + height)


def padded(
    points_range: list[float], image_range: tuple[float, float] | None
) -> tuple[float, float]:
    low, high = points_range
    if image_range is not None:
        low, high = min(low, *image_range), max(high, *image_range)
    span = high - low
    margin = span * 0.02 if span > 0 else 1.0
    return (low - margin, high + margin)


def copy_view_files(source: Path, target: Path) -> None:
    for name in VIEW_FILES:
        if (source / name).is_file():
            shutil.copyfile(source / name, target / name)


def _label(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _natural(label: str) -> tuple[Any, ...]:
    try:
        return (0, float(label), label)
    except ValueError:
        return (1, 0.0, label.lower())


def _round(value: float) -> float:
    return float(f"{value:.4g}") if math.isfinite(value) else value


def _plain(value: Any) -> Any:
    return _round(value) if isinstance(value, float) else value
