from __future__ import annotations

import time
from xml.etree import ElementTree as ET

import pytest
from test_figure_compositions import content, create, new_project, operate, panel, plot, plot_panel
from test_reference_images import png, upload

from vis_platform_backend.contracts.figure_arrangement import ArrangedGroup, ArrangedPanel
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.domain.figure_checks import figure_checks
from vis_platform_backend.domain.figure_compositions import (
    panel_frames,
    panel_labels,
    reading_rows,
)
from vis_platform_backend.domain.figure_layout import rows_arrangement, solve_arrangement
from vis_platform_backend.services.figure_svg import ASSUMED_SMALLEST_TEXT_PT, smallest_text_pt

PLOT_MM = (8 * 25.4, 5.5 * 25.4)


def leaf(panel_id, aspect=None):
    return ArrangedPanel(panel_id=panel_id, aspect=aspect)


def group(kind, *children):
    return ArrangedGroup(type=kind, children=list(children))


def solve(node, aspects, *, width=200, max_height=500, gutter=4):
    return solve_arrangement(
        node, aspects, left=5, top=5, width=width, max_height=max_height, gutter=gutter
    )


def test_rows_share_height_and_fill_the_width():
    frames = solve(group("row", leaf("wide"), leaf("square")), {"wide": 2, "square": 1})
    wide, square = frames["wide"], frames["square"]
    assert wide.height_mm == pytest.approx(square.height_mm)
    assert wide.width_mm == pytest.approx(2 * square.width_mm)
    assert wide.width_mm + 4 + square.width_mm == pytest.approx(200)
    assert square.x_mm == pytest.approx(5 + wide.width_mm + 4)


def test_nested_groups_are_not_a_grid():
    # A square UMAP beside a column of two small plots, above a wide heatmap and a curve.
    node = group(
        "column",
        group("row", leaf("umap"), group("column", leaf("dots"), leaf("bars"))),
        group("row", leaf("heatmap"), leaf("survival")),
    )
    aspects = {"umap": 1, "dots": 1.5, "bars": 1.5, "heatmap": 2.5, "survival": 1.3}
    frames = solve(node, aspects)
    umap, dots, bars = frames["umap"], frames["dots"], frames["bars"]
    # The right column is exactly as tall as the UMAP it sits beside.
    assert dots.height_mm + 4 + bars.height_mm == pytest.approx(umap.height_mm)
    assert dots.x_mm == pytest.approx(bars.x_mm)
    assert umap.width_mm + 4 + dots.width_mm == pytest.approx(200)
    # Every panel keeps its proportions.
    for key, frame in frames.items():
        assert frame.width_mm / frame.height_mm == pytest.approx(aspects[key])
    heatmap, survival = frames["heatmap"], frames["survival"]
    assert heatmap.y_mm == pytest.approx(umap.y_mm + umap.height_mm + 4)
    assert heatmap.height_mm == pytest.approx(survival.height_mm)


def test_tall_arrangements_shrink_to_the_page_and_stay_centred():
    frames = solve(group("column", leaf("a"), leaf("b")), {"a": 1, "b": 1}, max_height=104)
    a = frames["a"]
    assert a.height_mm * 2 + 4 == pytest.approx(104)
    assert a.x_mm == pytest.approx(5 + (200 - a.width_mm) / 2)


def test_invalid_arrangements_are_rejected():
    with pytest.raises(DataError, match="only once"):
        solve(group("row", leaf("a"), leaf("a")), {"a": 1})
    many = group("row", *[leaf(str(i)) for i in range(30)])
    with pytest.raises(DataError, match="no room"):
        solve(many, {str(i): 0.2 for i in range(30)}, width=60, gutter=4)


def test_tidy_arrangement_keeps_reading_rows():
    value = content([panel("a", 5, 5), panel("b", 80, 8), panel("c", 5, 90)])
    frames = panel_frames(value, {"a": (70, 60), "b": (70, 60), "c": (70, 60)})
    node = rows_arrangement(reading_rows(value.panels, frames))
    assert node.model_dump() == {
        "type": "column",
        "children": [
            {
                "type": "row",
                "children": [
                    {"type": "panel", "panel_id": "a", "aspect": None},
                    {"type": "panel", "panel_id": "b", "aspect": None},
                ],
            },
            {"type": "panel", "panel_id": "c", "aspect": None},
        ],
    }


def test_checks_report_margins_overlaps_text_resolution_order_and_space():
    value = content(
        [
            panel("a", 2, 5, scale=0.5),
            panel("b", 60, 5, scale=0.5, label="A"),
            panel("inset", 70, 10, scale=0.1),
            {
                "id": "photo",
                "content": {"type": "image", "image_id": "ref"},
                "x_mm": 5,
                "y_mm": 70,
                "scale": 2,
            },
        ]
    )
    natural = {"a": (100, 100), "b": (100, 100), "inset": (100, 100), "photo": (20, 20)}
    frames = panel_frames(value, natural)
    labels = panel_labels(value, frames)
    checks = figure_checks(
        value,
        frames,
        labels,
        120,
        {"a": (8, True), "b": (12, True), "inset": (8, False)},
    )
    by_code = {check.code: check for check in checks}
    assert by_code["outside_margin"].panel_ids == ["a"]
    # The inset lies entirely inside panel b, so it is not reported as an overlap.
    assert [c.panel_ids for c in checks if c.code == "overlap"] == []
    small = [c for c in checks if c.code == "small_text"]
    assert [c.panel_ids for c in small] == [["a"], ["inset"]]
    assert "prints at 4.0 pt" in small[0].message
    assert "may print at about 0.8 pt" in small[1].message
    assert by_code["low_resolution"].panel_ids == ["photo"]
    assert "150 dpi" in by_code["low_resolution"].message
    assert by_code["label_order"].severity == "info"
    assert by_code["unused_space"].severity == "info"
    overlapping = content([panel("a", 5, 5), panel("b", 30, 30)])
    frames = panel_frames(overlapping, {"a": (50, 50), "b": (50, 50)})
    checks = figure_checks(overlapping, frames, panel_labels(overlapping, frames), 297, {})
    assert [c.panel_ids for c in checks if c.code == "overlap"] == [["a", "b"]]


def test_text_sizes_are_measured_in_points():
    root = ET.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 560">'
        '<g font-size="10.5"><text>tick</text></g>'
        '<text style="font-size: 25px">Title</text><text font-size="4"> </text></svg>'
    )
    # 960 units across 10 inches: 96 units per inch, so 10.5 units print at 7.875 pt.
    assert smallest_text_pt(root, 10) == (pytest.approx(7.875), True)
    outlines = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 72 72"/>')
    assert smallest_text_pt(outlines, 1) == (ASSUMED_SMALLEST_TEXT_PT, False)


def wait_jobs(client, document, expected=("completed",)):
    url = (
        f"/api/v1/projects/{document['project_id']}/figure-compositions/"
        f"{document['composition_id']}"
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        current = client.get(url).json()
        if current["jobs"] and all(job["status"] != "running" for job in current["jobs"]):
            assert {job["status"] for job in current["jobs"]} <= set(expected), current["jobs"]
            return current
        time.sleep(0.05)
    raise AssertionError("Renders did not finish")


def arrange(client, document, request_id="arrange", **body):
    return client.post(
        f"/api/v1/projects/{document['project_id']}/figure-compositions/"
        f"{document['composition_id']}/arrange",
        json={"request_id": request_id, "base_revision": document["revision"], **body},
    )


def test_tidy_and_explicit_arrangements_save_exact_geometry(client):
    owner = new_project(client)
    first, second, third = plot(client, owner), plot(client, owner), plot(client, owner)
    image = upload(client, owner, content=png(size=(600, 600))).json()
    document = create(
        client,
        owner,
        [
            plot_panel("a", first, 5, 5, scale=0.3),
            plot_panel("b", second, 90, 12, scale=0.4),
            plot_panel("c", third, 20, 80, scale=0.3),
            {
                "id": "photo",
                "content": {"type": "image", "image_id": image["image_id"]},
                "x_mm": 150,
                "y_mm": 150,
                "locked": True,
            },
        ],
    ).json()
    tidy = arrange(client, document)
    assert tidy.status_code == 200, tidy.text
    tidy = tidy.json()
    frames = tidy["panels"]
    photo_bottom = 150 + 50.8
    # Locked content keeps its place; the rows start below it.
    assert frames["photo"]["frame"]["y_mm"] == 150
    assert frames["a"]["frame"]["y_mm"] == pytest.approx(photo_bottom + 4)
    assert frames["a"]["frame"]["height_mm"] == pytest.approx(frames["b"]["frame"]["height_mm"])
    assert frames["c"]["frame"]["y_mm"] > frames["a"]["frame"]["y_mm"]
    assert tidy["revision"] == 2
    assert arrange(client, document).json()["revision"] == 2
    locked = arrange(client, tidy, "locked", arrangement={"type": "panel", "panel_id": "photo"})
    assert locked.status_code == 422
    assert "locked" in locked.json()["error"]["message"]
    explicit = arrange(
        client,
        tidy,
        "explicit",
        arrangement={
            "type": "row",
            "children": [
                {"type": "panel", "panel_id": "c"},
                {
                    "type": "column",
                    "children": [
                        {"type": "panel", "panel_id": "a"},
                        {"type": "panel", "panel_id": "b"},
                    ],
                },
            ],
        },
    ).json()
    a, b, c = (explicit["panels"][key]["frame"] for key in "abc")
    assert a["x_mm"] == pytest.approx(b["x_mm"])
    assert a["height_mm"] + 4 + b["height_mm"] == pytest.approx(c["height_mm"], abs=0.2)
    assert c["x_mm"] + c["width_mm"] + 4 == pytest.approx(a["x_mm"], abs=0.1)


def test_rendering_at_panel_size_replaces_the_version_without_publishing_it(client):
    owner = new_project(client)
    first = plot(client, owner)
    document = create(client, owner, [plot_panel("a", first, 5, 5, scale=0.25)]).json()
    small = [check for check in document["checks"] if check["code"] == "small_text"]
    assert small and "prints at" in small[0]["message"]
    url = f"/api/v1/projects/{owner}/figure-compositions/{document['composition_id']}"
    response = client.post(
        url + "/renders",
        json={"request_id": "fit", "panels": {"a": {"width_mm": 80, "height_mm": 60}}},
    )
    assert response.status_code == 202, response.text
    assert response.json()["jobs"][0]["status"] in {"running", "completed"}
    rendered = wait_jobs(client, document)
    panel = rendered["content"]["panels"][0]
    assert panel["scale"] == 1
    assert panel["content"]["source_version_id"] == first["result"]["version_id"]
    assert panel["content"]["version_id"] != first["result"]["version_id"]
    # Sizes are rendered in 0.01 in steps, rounded down.
    assert rendered["panels"]["a"]["frame"]["width_mm"] == pytest.approx(80, abs=0.26)
    assert rendered["panels"]["a"]["frame"]["height_mm"] == pytest.approx(60, abs=0.26)
    # Demonstration drawings scale their text with the canvas, so the check now measures the
    # rendered version at scale 1 (R drawings keep their point sizes when rendered smaller).
    remaining = [check for check in rendered["checks"] if check["code"] == "small_text"]
    assert "prints at 2.5 pt" in remaining[0]["message"]
    assert rendered["updates"] == {}
    # The figure-sized version never becomes the plot's current version.
    versions = client.get(
        f"/api/v1/projects/{owner}/plots/{first['result']['plot_id']}/versions"
    ).json()
    assert versions["current_version_id"] == first["result"]["version_id"]
    assert (
        client.post(
            url + "/renders",
            json={"request_id": "fit", "panels": {"a": {"width_mm": 70, "height_mm": 60}}},
        ).status_code
        == 409
    )
    beyond = client.post(
        url + "/renders",
        json={"request_id": "big", "panels": {"a": {"width_mm": 300, "height_mm": 60}}},
    )
    assert beyond.status_code == 422


def test_arranging_with_render_uses_preferred_shapes(client):
    owner = new_project(client)
    first, second = plot(client, owner), plot(client, owner)
    image = upload(client, owner, content=png(size=(600, 300))).json()
    document = create(
        client,
        owner,
        [
            plot_panel("a", first, 5, 5),
            plot_panel("b", second, 5, 90, scale=0.3),
            {
                "id": "photo",
                "content": {"type": "image", "image_id": image["image_id"]},
                "x_mm": 120,
                "y_mm": 200,
            },
        ],
    ).json()
    arranged = arrange(
        client,
        document,
        render=True,
        arrangement={
            "type": "column",
            "children": [
                {
                    "type": "row",
                    "children": [
                        {"type": "panel", "panel_id": "a", "aspect": 1},
                        {"type": "panel", "panel_id": "b", "aspect": 1},
                    ],
                },
                {"type": "panel", "panel_id": "photo", "aspect": 1},
            ],
        },
    )
    assert arranged.status_code == 200, arranged.text
    rendered = wait_jobs(client, arranged.json())
    a, b = rendered["panels"]["a"]["frame"], rendered["panels"]["b"]["frame"]
    assert a["width_mm"] == pytest.approx(a["height_mm"], abs=0.3)
    assert a["width_mm"] + 4 + b["width_mm"] == pytest.approx(200, abs=0.6)
    photo = rendered["panels"]["photo"]
    # Images keep their proportions; a preferred shape only applies to rendered plots.
    assert photo["frame"]["width_mm"] / photo["frame"]["height_mm"] == pytest.approx(2)
    assert len(rendered["jobs"]) == 2


def test_a_render_is_not_applied_after_the_panel_changes(slow_client):
    client = slow_client
    owner = new_project(client)
    first, second = plot_slow(client, owner), plot_slow(client, owner)
    document = create(client, owner, [plot_panel("a", first, 5, 5, scale=0.3)]).json()
    url = f"/api/v1/projects/{owner}/figure-compositions/{document['composition_id']}"
    client.post(
        url + "/renders",
        json={"request_id": "fit", "panels": {"a": {"width_mm": 80, "height_mm": 60}}},
    )
    replaced = document["content"]["panels"][0] | {
        "content": {"type": "plot", "version_id": second["result"]["version_id"]}
    }
    assert (
        operate(client, document, [{"op": "replace_panel", "panel": replaced}]).status_code == 200
    )
    finished = wait_jobs(client, document, ("discarded",))
    assert (
        finished["content"]["panels"][0]["content"]["version_id"]
        == (second["result"]["version_id"])
    )
    assert "changed" in finished["jobs"][0]["error"]


def test_only_resizable_plots_can_be_rendered(client):
    owner = new_project(client)
    image = upload(client, owner).json()
    document = create(
        client,
        owner,
        [
            {
                "id": "photo",
                "content": {"type": "image", "image_id": image["image_id"]},
                "x_mm": 5,
                "y_mm": 5,
            }
        ],
    ).json()
    response = client.post(
        f"/api/v1/projects/{owner}/figure-compositions/{document['composition_id']}/renders",
        json={"request_id": "fit", "panels": {"photo": {"width_mm": 40, "height_mm": 30}}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FIGURE_RENDER_UNAVAILABLE"


def plot_slow(client, owner):
    from test_parameters import wait as wait_run

    response = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Make a violin distribution of expression"},
            "data_scope": {"mode": "demo"},
        },
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            return wait_run(client, response.json())
        except AssertionError as error:
            if "did not finish" not in str(error):
                raise
    raise AssertionError("Plot did not finish")
