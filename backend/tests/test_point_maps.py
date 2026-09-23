from __future__ import annotations

import io
import json
import time

import numpy as np
import pyarrow as pa
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from spatial_data import cells, parquet_bytes, png_bytes, tissue_image
from test_agent_context import RecordingAgent
from test_datasets import RUNTIME, ProfileOnlyAgent, wait_run
from test_reference_images import project

from vis_platform_backend.app import create_app
from vis_platform_backend.config import Settings
from vis_platform_backend.contracts.research import ResearchDecision
from vis_platform_backend.data import columnar
from vis_platform_backend.execution.runner import RExecutionError
from vis_platform_backend.services import point_map_render as render
from vis_platform_backend.services.figure_svg import read_svg
from vis_platform_backend.services.plot_marks import MARKED_IMAGE_ID

requires_r = pytest.mark.skipif(
    not (RUNTIME / "usr/lib/R").is_dir(), reason="Restricted R runtime is unavailable"
)
WIDTH, HEIGHT = 400, 300


def settings(tmp_path):
    return Settings(
        database_path=tmp_path / "data.sqlite",
        artifact_root=tmp_path / "artifacts",
        r_home=RUNTIME / "usr/lib/R",
        r_sandbox=RUNTIME / "vis-r-sandbox",
    )


def upload(client, owner, files):
    dataset = client.post(
        "/api/v1/data-bundles", json={"project_id": owner, "name": "Section"}
    ).json()["dataset_id"]
    for name, content in files:
        response = client.post(
            f"/api/v1/data-bundles/{dataset}/files",
            params={"project_id": owner, "name": name},
            content=content,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 201, response.text
    client.post(f"/api/v1/data-bundles/{dataset}/finalize", params={"project_id": owner})
    for _ in range(300):
        found = client.get(f"/api/v1/data-bundles/{dataset}", params={"project_id": owner}).json()
        if found["state"] != "processing":
            return found
        time.sleep(0.02)
    raise AssertionError("Inspection did not finish")


def reference(item):
    return {"object_id": item["object_id"], "revision_id": item["revision_id"]}


def section(client, owner, count=3000):
    """A dataset with a cell table and the section image the cells lie on."""
    dataset = upload(
        client,
        owner,
        [
            ("cells.parquet", parquet_bytes(cells(count, WIDTH, HEIGHT))),
            ("section.png", png_bytes(tissue_image(WIDTH, HEIGHT))),
        ],
    )
    assert dataset["state"] == "ready", dataset
    return dataset, {item["name"]: item for item in dataset["objects"]}


def point_plan(objects, **point_map):
    return {
        "title": "Tissue domains",
        "description": "Cells coloured by domain over the section.",
        "figure_size": {"width": 6, "height": 4.5},
        "inputs": [
            {"alias": "cells", "reference": reference(objects["cells"])},
            {"alias": "section", "reference": reference(objects["section"])},
        ],
        "point_map": {
            "table": "cells",
            "x": "x_px",
            "y": "y_px",
            "color": "domain",
            "y_axis": "down",
            "image": {"input": "section"},
            **point_map,
        },
    }


def run_plan(client, owner, dataset, plan):
    response = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Map the domains"},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
            "research_plan": plan,
        },
    )
    assert response.status_code == 202, response.text
    return wait_run(client, response.json())


def view_path(owner, result):
    return (
        f"/api/v1/projects/{owner}/plots/{result['plot_id']}/versions/"
        f"{result['version_id']}/point-view"
    )


# Uploads


def test_large_tables_are_read_by_column_and_images_become_image_objects(tmp_path, monkeypatch):
    # Beyond the row-by-row size, delimited tables take the columnar path too.
    monkeypatch.setattr(columnar, "SMALL_TABLE_BYTES", 100)
    with TestClient(create_app(settings(tmp_path), data_agent=ProfileOnlyAgent())) as client:
        owner = project(client)
        table = cells(500, WIDTH, HEIGHT)
        csv = io.BytesIO()
        pa.csv.write_csv(table, csv)
        dataset = upload(
            client,
            owner,
            [
                ("cells.csv", csv.getvalue()),
                ("small.csv", b"a,b\n1,2\n"),
                ("section.png", png_bytes(tissue_image(WIDTH, HEIGHT))),
            ],
        )
        assert dataset["state"] == "ready", dataset
        objects = {item["name"]: item for item in dataset["objects"]}
        large = objects["cells"]
        assert (large["format"], large["kind"], large["dimensions"]) == (
            "parquet",
            "table",
            [500, 6],
        )
        profile = {column["name"]: column for column in large["columns"]}
        assert profile["x_px"]["data_type"] == "number"
        assert 0 <= profile["x_px"]["numeric"]["minimum"] < profile["x_px"]["numeric"]["maximum"]
        assert profile["domain"]["data_type"] == "string"
        assert profile["domain"]["unique_count"] == 4
        assert any("point map" in note for note in large["limitations"])
        # Files the row-by-row path accepted before keep it.
        assert objects["small"]["format"] == "csv"
        image = objects["section"]
        assert (image["kind"], image["format"], image["dimensions"]) == ("image", "png", [300, 400])
        assert image["extensions"] == {"pixel_width": 400, "pixel_height": 300, "stored_scale": 1.0}


def test_large_formats_have_their_own_upload_limit(tmp_path):
    config = settings(tmp_path)
    object.__setattr__(config, "upload_limit_bytes", 10)
    object.__setattr__(config, "large_upload_limit_bytes", 1000)
    with TestClient(create_app(config, data_agent=ProfileOnlyAgent())) as client:
        owner = project(client)
        dataset = client.post(
            "/api/v1/data-bundles", json={"project_id": owner, "name": "Limits"}
        ).json()["dataset_id"]

        def send(name, size):
            return client.post(
                f"/api/v1/data-bundles/{dataset}/files",
                params={"project_id": owner, "name": name},
                content=b"x" * size,
                headers={"Content-Type": "application/octet-stream"},
            ).status_code

        assert send("notes.json", 20) == 413
        assert send("cells.parquet", 500) == 201
        assert send("cells.csv", 500) == 201
        assert send("big.parquet", 2000) == 413


def test_embedded_png_data_is_the_only_external_looking_reference_allowed(tmp_path):
    def svg(href):
        path = tmp_path / "figure.svg"
        path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 10 10"><g><image xlink:href="{href}"/><rect/></g></svg>'
        )
        return path

    read_svg(svg("data:image/png;base64,iVBORw0KGgo="))
    for href in ("https://example.com/x.png", "data:image/svg+xml;base64,PHN2Zz4=", "file:///x"):
        with pytest.raises(RExecutionError):
            read_svg(svg(href))


# Drawing


def test_ticks_and_labels_are_round_numbers():
    assert render.nice_ticks(-40, 2040) == [0, 500, 1000, 1500, 2000]
    assert render.nice_ticks(0.013, 0.087, 4) == pytest.approx([0.02, 0.04, 0.06, 0.08])
    assert render.tick_label(0.04, [0.02, 0.04]) == "0.04"
    assert render.tick_label(-0.0, [0, 500]) == "0"


def frame(y_down):
    return render.layout(
        2, 2, (0, 10), (0, 10), y_down=y_down, equal_aspect=True, titled=False, legend_width=0
    )


def test_points_land_where_their_axis_says_and_stack_by_opacity():
    red = np.array([[255, 0, 0]], dtype=np.uint8)
    for y_down in (False, True):
        image = render.raster(
            frame(y_down),
            np.array([0.5], dtype=np.float32),
            np.array([9.5], dtype=np.float32),
            red,
            point_size=0.1,
            opacity=1,
            background=None,
            dpi=72,
        )
        pixels = np.asarray(image)
        row, column = np.argwhere((pixels == [255, 0, 0]).all(axis=2))[0] / pixels.shape[:2]
        # High y is near the top when y goes up, and near the bottom when it goes down.
        assert row == pytest.approx(0.95 if y_down else 0.05, abs=0.02)
        assert column == pytest.approx(0.05, abs=0.02)
    twice = render.raster(
        frame(False),
        np.array([5, 5], dtype=np.float32),
        np.array([5, 5], dtype=np.float32),
        np.array([[0, 0, 0], [0, 0, 0]], dtype=np.uint8),
        point_size=0.1,
        opacity=0.5,
        background=None,
        dpi=72,
    )
    # Two half-opaque black points: 1 - 0.5² = 75% black over white.
    assert np.asarray(twice).min() == round(255 * 0.25)


def test_the_image_is_placed_by_its_data_extent():
    source = Image.new("RGB", (10, 10), "white")
    source.putpixel((2, 7), (255, 0, 0))
    placed = frame(True)
    background = render.background_image(placed, source, (0, 10, 0, 10), dpi=72)
    pixels = np.asarray(background)
    ys, xs = np.nonzero(pixels[..., 1] < 128)
    # Image column 2, row 7 covers data x 2–3, y 7–8; with y down that is 70–80% down.
    assert 0.18 <= xs.mean() / pixels.shape[1] <= 0.32
    assert 0.68 <= ys.mean() / pixels.shape[0] <= 0.82


# Plot runs


@requires_r
def test_a_point_map_renders_without_r_and_serves_its_interactive_view(tmp_path):
    with TestClient(create_app(settings(tmp_path), data_agent=ProfileOnlyAgent())) as client:
        owner = project(client)
        dataset, objects = section(client, owner)
        completed = run_plan(client, owner, dataset, point_plan(objects))
        assert completed["status"] == "completed", completed
        result = completed["result"]
        assert result["interactive_view"] == "points"
        assert {control["id"] for control in result["controls"]} == {
            "figure_width",
            "figure_height",
            "point_size",
            "point_opacity",
            "show_image",
        }
        svg = client.get(result["preview"]["href"]).content
        assert b"data:image/png;base64," in svg
        path = tmp_path / "preview.svg"
        path.write_bytes(svg)
        read_svg(path)
        # The saved result keeps positions and source rows, not a copy of the table.
        saved = result["analysis_results"][0]
        assert saved["objects"][0]["format"] == "parquet"
        assert {item["object_id"] for item in saved["inputs"]} == {
            objects["cells"]["object_id"],
            objects["section"]["object_id"],
        }

        view = client.get(view_path(owner, result)).json()
        assert view["count"] == 3000 and view["dropped"] == 0
        assert view["y"]["direction"] == "down"
        assert view["columns"] == ["x", "y", "color"]
        assert [item["value"] for item in view["color"]["categories"]] == [
            "Capsule",
            "Cortex",
            "Medulla",
            "Vessel",
        ]
        assert view["image"] == {"extent": [0, WIDTH, 0, HEIGHT], "visible": True}
        columns = client.get(view["links"]["columns"])
        assert columns.headers["content-type"] == "application/octet-stream"
        values = np.frombuffer(columns.content, dtype="<f4").reshape(3, 3000)
        source = cells(3000, WIDTH, HEIGHT)
        assert values[0] == pytest.approx(source.column("x_px").to_numpy(), abs=1e-3)
        image = client.get(view["links"]["image"])
        assert Image.open(io.BytesIO(image.content)).size == (WIDTH, HEIGHT)
        wrong = view_path(owner, {**result, "plot_id": "plot_other"})
        assert client.get(wrong).status_code == 404
        # Every other interface uses the saved figure, and its exports, as for any plot.
        exports = (
            f"/api/v1/projects/{owner}/plots/{result['plot_id']}/versions/"
            f"{result['version_id']}/exports"
        )
        for format, signature in (("pdf", b"%PDF"), ("png", b"\x89PNG"), ("svg", b"<?xml")):
            exported = client.get(f"{exports}/{format}")
            assert exported.status_code == 200, exported.text
            assert exported.content.startswith(signature)

        # Presentation changes re-render the saved positions without the model or R.
        changed = client.post(
            f"/api/v1/plots/{result['plot_id']}/parameters",
            json={
                "project_id": owner,
                "base_version_id": result["version_id"],
                "changes": {"point_size": 2.0, "show_image": False},
            },
        )
        assert changed.status_code == 202, changed.text
        edited = wait_run(client, changed.json())
        assert edited["status"] == "completed", edited
        assert edited["result"]["analysis_results"][0]["result_id"] == saved["result_id"]
        edited_view = client.get(view_path(owner, edited["result"])).json()
        assert edited_view["point_size"] == 2.0
        assert edited_view["image"]["visible"] is False

        restored = client.post(
            f"/api/v1/plots/{result['plot_id']}/restore",
            json={"project_id": owner, "source_version_id": result["version_id"]},
        )
        again = wait_run(client, restored.json())
        assert again["status"] == "completed", again
        assert (
            client.get(view_path(owner, again["result"])).json()["point_size"] == view["point_size"]
        )


@requires_r
def test_numeric_colours_become_a_scale_and_rows_without_positions_are_counted(tmp_path):
    with TestClient(create_app(settings(tmp_path), data_agent=ProfileOnlyAgent())) as client:
        owner = project(client)
        table = cells(200, WIDTH, HEIGHT)
        x = table.column("x_px").to_numpy().copy()
        x[:5] = np.nan
        table = table.set_column(1, "x_px", pa.array(x))
        dataset = upload(client, owner, [("cells.parquet", parquet_bytes(table))])
        objects = {item["name"]: item for item in dataset["objects"]}
        plan = point_plan({**objects, "section": objects["cells"]}, color="marker_a", image=None)
        plan["inputs"] = plan["inputs"][:1]
        completed = run_plan(client, owner, dataset, plan)
        assert completed["status"] == "completed", completed
        view = client.get(view_path(owner, completed["result"])).json()
        assert view["count"] == 195 and view["dropped"] == 5
        assert view["color"]["type"] == "continuous"
        assert view["color"]["domain"][0] < view["color"]["domain"][1]
        assert view["image"] is None and view["links"]["image"] is None

        bad = run_plan(
            client, owner, dataset, {**plan, "point_map": {**plan["point_map"], "x": "domain"}}
        )
        assert bad["status"] == "failed"
        assert "not numeric" in bad["failure"]["message"]


@requires_r
def test_r_analysis_refuses_tables_too_large_for_it(tmp_path):
    with TestClient(create_app(settings(tmp_path), data_agent=ProfileOnlyAgent())) as client:
        owner = project(client)
        dataset, objects = section(client, owner, count=50)
        plan = {
            "title": "Domain counts",
            "description": "Cells per domain.",
            "inputs": [{"alias": "cells", "reference": reference(objects["cells"])}],
            "analysis_code": "list(counts=table(inputs$cells$domain))",
            "outputs": [{"key": "counts", "name": "Counts", "description": "Cells per domain."}],
        }
        response = client.post(
            "/api/v1/plot-runs",
            json={
                "project_id": owner,
                "request": {"text": "Compare"},
                "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
                "research_plan": plan,
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "INPUT_NOT_SUPPORTED"


# The assistant


def refine(summary="Label the marked cells."):
    return {
        "kind": "plot_refine",
        "subtype": "visual",
        "normalized_request": summary,
        "confidence": 1,
        "next_action": "refine_context",
        "decision_summary": summary,
        "refinement": {
            "reuse_data": True,
            "execution_strategy": "regenerate_render",
            "changes": [{"target": "labels", "value": "marked", "change_class": "visual"}],
        },
    }


def create(**extra):
    return {
        "kind": "plot_create",
        "subtype": "spatial",
        "normalized_request": "Map the tissue domains",
        "confidence": 1,
        "next_action": "build_context",
        "plot": {"goal": "Map the tissue domains"},
        "decision_summary": "Map the cells.",
        **extra,
    }


class PointMapAgent(ProfileOnlyAgent):
    """Plans point maps from the uploaded section, as the model would when offered one."""

    def __init__(self):
        self.contexts = []

    async def plan(self, context):
        self.contexts.append(context)
        objects = {item["name"]: item for item in context["objects"]}
        return ResearchDecision.model_validate(
            {"action": "execute", "summary": "Map the cells.", "plan": point_plan(objects)}
        )


@requires_r
def test_point_maps_are_offered_only_to_interactive_requests(tmp_path):
    agent = RecordingAgent([create(), create()])
    planner = PointMapAgent()
    with TestClient(
        create_app(settings(tmp_path), intent_agent=agent, data_agent=planner)
    ) as client:
        owner = project(client)
        dataset, _ = section(client, owner, count=100)
        scope = {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]}
        elsewhere = client.post(
            "/api/v1/assistant-turns",
            json={"project_id": owner, "request": {"text": "Map it"}, "data_scope": scope},
        ).json()
        assert elsewhere["outcome"] == "message"
        assert "Pinpoint" in elsewhere["message"]
        assert planner.contexts[0]["interactive_view"] is False
        pinpoint = client.post(
            "/api/v1/assistant-turns",
            json={
                "project_id": owner,
                "request": {"text": "Map it", "interactive": True},
                "data_scope": scope,
            },
        ).json()
        assert pinpoint["outcome"] == "plot_run", pinpoint
        assert planner.contexts[1]["interactive_view"] is True
        made = wait_run(client, pinpoint["plot_run"])
        assert made["status"] == "completed", made
        assert made["result"]["interactive_view"] == "points"


@requires_r
def test_clicked_and_dragged_marks_reach_the_planners_with_what_they_hold(tmp_path):
    agent = RecordingAgent([refine()])
    planner = PointMapAgent()
    with TestClient(
        create_app(settings(tmp_path), intent_agent=agent, data_agent=planner)
    ) as client:
        owner = project(client)
        dataset, objects = section(client, owner)
        made = run_plan(client, owner, dataset, point_plan(objects))["result"]
        source = cells(3000, WIDTH, HEIGHT)
        x, y = source.column("x_px").to_numpy(), source.column("y_px").to_numpy()
        # Drag across the middle: the medulla, and nothing outside the drag.
        box = {"x_from": 150.0, "x_to": 250.0, "y_from": 110.0, "y_to": 190.0}
        inside = (x >= 150) & (x <= 250) & (y >= 110) & (y <= 190)
        response = client.post(
            "/api/v1/assistant-turns",
            json={
                "project_id": owner,
                "request": {"text": "What are 1 and 2?", "interactive": True},
                "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
                "base_version_id": made["version_id"],
                "plot_marks": [
                    {"number": 1, "kind": "element", "index": 42},
                    {"number": 2, "kind": "selection", **box},
                ],
            },
        )
        assert response.status_code == 200, response.text
        marks = agent.inputs[0].workspace_context["plot_marks"]
        clicked = marks[0]
        assert clicked["kind"] == "element"
        assert clicked["data"]["source_row"] == 42
        assert clicked["data"]["values"]["cell_id"] == "cell_42"
        assert clicked["data"]["values"]["x_px"] == pytest.approx(x[42], rel=1e-3)
        # It is drawn where the point is, inside the one plotting region.
        region = clicked["plot_regions"][0]
        assert region["x"] == pytest.approx(x[42], abs=2)
        assert region["y"] == pytest.approx(y[42], abs=2)
        dragged = marks[1]
        assert dragged["kind"] == "selection"
        assert dragged["data"]["count"] == int(inside.sum())
        by_domain = {item["value"]: item["count"] for item in dragged["data"]["by_domain"]}
        assert by_domain["Medulla"] == int(
            (inside & (source.column("domain").to_numpy(zero_copy_only=False) == "Medulla")).sum()
        )
        different = {item["column"] for item in dragged["data"]["most_different_columns"]}
        assert "marker_a" in different
        assert len(dragged["data"]["example_rows"]) == 5
        assert agent.inputs[0].reference_images[-1].image_id == MARKED_IMAGE_ID

        missing = client.post(
            "/api/v1/assistant-turns",
            json={
                "project_id": owner,
                "request": {"text": "What is 1?", "interactive": True},
                "data_scope": {"mode": "auto"},
                "base_version_id": made["version_id"],
                "plot_marks": [{"number": 1, "kind": "element", "index": 99_999}],
            },
        )
        assert missing.status_code == 422
        assert missing.json()["error"]["code"] == "INVALID_PLOT_MARK"
        # Point-view marks need a point view; R plots take image marks.
        assert len(agent.inputs) == 1


def test_selections_run_from_low_to_high(tmp_path):
    from pydantic import ValidationError

    from vis_platform_backend.contracts.plot_marks import SelectionMark

    with pytest.raises(ValidationError, match="lower to its higher"):
        SelectionMark(number=1, kind="selection", x_from=2, x_to=1, y_from=0, y_to=1)
    with pytest.raises(ValidationError):
        SelectionMark.model_validate(
            {"number": 1, "kind": "selection", "x_from": 0, "x_to": 1, "y_from": 0, "y_to": "inf"}
        )
    assert (
        json.loads(
            SelectionMark(
                number=1, kind="selection", x_from=0, x_to=1, y_from=0, y_to=1
            ).model_dump_json()
        )["kind"]
        == "selection"
    )
