from __future__ import annotations

import io
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from PIL import Image
from pydantic import ValidationError
from pypdf import PdfReader
from test_parameters import update, wait
from test_reference_images import png, upload

from vis_platform_backend.contracts.figure_composition_content import FigureCompositionContent
from vis_platform_backend.contracts.figure_compositions import PanelFrame
from vis_platform_backend.contracts.figures import FigureSize
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.domain.figure_compositions import (
    apply_figure_operations,
    check_bounds,
    page_height,
    panel_frames,
    panel_labels,
)

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
SVG = "{http://www.w3.org/2000/svg}"
# The fixture size agent renders every demonstration plot at 8 × 5.5 in.
PLOT_MM = (8 * 25.4, 5.5 * 25.4)


def content(panels=(), **changes):
    return FigureCompositionContent.model_validate(
        {
            "title": "Figure 1",
            "page": {"width_mm": 210, "height_mm": 297, "height_mode": "auto", "margin_mm": 5},
            "panels": list(panels),
            **changes,
        }
    )


def panel(panel_id, x, y, *, scale=1, **options):
    return {
        "id": panel_id,
        "content": {"type": "plot", "version_id": f"version_{panel_id}"},
        "x_mm": x,
        "y_mm": y,
        "scale": scale,
        **options,
    }


def geometry(value, sizes):
    frames = panel_frames(value, sizes)
    return frames, panel_labels(value, frames)


def new_project(client):
    return client.post("/api/v1/projects", json={"name": "Figure study"}).json()["project_id"]


def plot(client, owner, text="Make a violin distribution of expression"):
    response = client.post(
        "/api/v1/plot-runs",
        json={"project_id": owner, "request": {"text": text}, "data_scope": {"mode": "demo"}},
    )
    assert response.status_code == 202, response.text
    return wait(client, response.json())


def plot_panel(panel_id, snapshot, x, y, scale=0.45, **options):
    return {
        "id": panel_id,
        "content": {"type": "plot", "version_id": snapshot["result"]["version_id"]},
        "x_mm": x,
        "y_mm": y,
        "scale": scale,
        **options,
    }


def create(client, owner, panels, *, request_id="figure-create", **changes):
    return client.post(
        f"/api/v1/projects/{owner}/figure-compositions",
        json={
            "request_id": request_id,
            "content": {
                "title": "Figure 1",
                "page": {"width_mm": 210, "height_mm": 297, "height_mode": "auto"},
                "panels": panels,
                **changes,
            },
        },
    )


def operate(client, document, operations, request_id="edit", base=None):
    return client.post(
        f"/api/v1/projects/{document['project_id']}/figure-compositions/"
        f"{document['composition_id']}/operations",
        json={
            "request_id": request_id,
            "base_revision": base or document["revision"],
            "operations": operations,
        },
    )


def test_contract_rejects_inconsistent_content_and_accepts_the_example():
    FigureCompositionContent.model_validate(
        json.loads((CONTRACTS / "figure-composition-v1.example.json").read_text())
    )
    with pytest.raises(ValidationError, match="Panel IDs"):
        content([panel("a", 0, 0), panel("a", 50, 0)])
    with pytest.raises(ValidationError, match="Custom panel labels"):
        content([panel("a", 0, 0, label="A"), panel("b", 50, 0, label="a")])
    with pytest.raises(ValidationError, match="Legend entries"):
        content([panel("a", 0, 0)], legend={"entries": {"missing": "Text"}})
    with pytest.raises(ValidationError, match="margins"):
        content(page={"width_mm": 40, "height_mm": 40, "margin_mm": 20})
    with pytest.raises(ValidationError):
        content([panel("a", 0, 0, scale=0)])
    # Hidden panels may reuse a label because it is never displayed.
    content([panel("a", 0, 0, label="A"), panel("b", 50, 0, label="A", show_label=False)])


def test_plot_sizes_accept_one_inch_panels():
    assert FigureSize(width=1, height=1).width == 1
    with pytest.raises(ValidationError):
        FigureSize(width=0.99, height=2)


def test_labels_follow_rows_and_skip_custom_letters():
    # A tall left panel spans two rows; the right column is read top to bottom.
    value = content(
        [
            panel("heatmap", 110, 60),
            panel("umap", 5, 5),
            panel("inset", 110, 5),
            panel("legend_key", 5, 150, show_label=False),
            panel("survival", 60, 150, label="A"),
        ]
    )
    sizes = {
        "umap": (100, 140),
        "inset": (90, 50),
        "heatmap": (90, 80),
        "legend_key": (40, 20),
        "survival": (60, 40),
    }
    _, labels = geometry(value, sizes)
    assert labels == {
        "umap": "B",
        "inset": "C",
        "heatmap": "D",
        "legend_key": None,
        "survival": "A",
    }
    lower = value.model_copy(update={"labels": value.labels.model_copy(update={"case": "lower"})})
    assert geometry(lower, sizes)[1]["umap"] == "b"


def test_panels_in_one_row_read_left_to_right_despite_small_offsets():
    value = content([panel("right", 110, 5), panel("left", 5, 8)])
    _, labels = geometry(value, {"right": (90, 60), "left": (90, 60)})
    assert labels == {"left": "A", "right": "B"}


def test_labels_extend_beyond_the_alphabet():
    value = content([panel(f"p{index}", index * 7, 0) for index in range(28)])
    _, labels = geometry(value, {f"p{index}": (5, 5) for index in range(28)})
    assert [labels["p0"], labels["p25"], labels["p26"], labels["p27"]] == ["A", "Z", "AA", "AB"]


def test_page_height_follows_content_and_bounds_are_enforced():
    value = content([panel("a", 5, 5, scale=0.5)])
    frames = panel_frames(value, {"a": (200, 100)})
    assert frames["a"] == PanelFrame(x_mm=5, y_mm=5, width_mm=100, height_mm=50)
    assert page_height(value, frames) == 60
    fixed = content(
        [panel("a", 5, 5, scale=0.5)],
        page={"width_mm": 210, "height_mm": 297, "height_mode": "fixed"},
    )
    assert page_height(fixed, frames) == 297
    assert page_height(content(), {}) == 20
    wide = panel_frames(value, {"a": (420, 100)})
    with pytest.raises(DataError, match="extends beyond the page"):
        check_bounds(value, wide)


def test_operations_edit_an_isolated_copy():
    from vis_platform_backend.contracts.figure_composition_operations import (
        FigureOperationsRequest,
    )

    original = content(
        [panel("a", 0, 0), panel("b", 50, 0)], legend={"entries": {"a": "First", "b": "Second"}}
    )

    def apply(*operations):
        request = FigureOperationsRequest.model_validate(
            {"request_id": "r", "base_revision": 1, "operations": list(operations)}
        )
        return apply_figure_operations(original, request.operations)

    changed = apply(
        {"op": "add_panel", "panel": panel("c", 10, 10), "before_id": "b"},
        {"op": "remove_panel", "panel_id": "a"},
        {"op": "set_panel_geometry", "panels": {"b": {"x_mm": 1, "y_mm": 2, "scale": 0.5}}},
        {"op": "set_title", "title": "Figure 2"},
    )
    assert [item.id for item in changed.panels] == ["c", "b"]
    assert (changed.panels[1].x_mm, changed.panels[1].y_mm, changed.panels[1].scale) == (1, 2, 0.5)
    assert changed.legend.entries == {"b": "Second"}
    assert changed.title == "Figure 2"
    assert [item.id for item in original.panels] == ["a", "b"]
    with pytest.raises(DataError, match="not found") as missing:
        apply({"op": "remove_panel", "panel_id": "missing"})
    assert missing.value.status == 404
    with pytest.raises(DataError, match="Panel IDs") as duplicate:
        apply({"op": "add_panel", "panel": panel("a", 0, 0)})
    assert duplicate.value.code == "INVALID_FIGURE_OPERATION"


def test_figure_lifecycle_resolves_geometry_and_stays_in_its_project(client):
    owner = new_project(client)
    first, second = plot(client, owner), plot(client, owner, "Make a scatter relationship")
    image = upload(client, owner, content=png(size=(600, 300))).json()
    panels = [
        plot_panel("distribution", first, 5, 5),
        plot_panel("relationship", second, 105, 5),
        {
            "id": "micrograph",
            "content": {"type": "image", "image_id": image["image_id"]},
            "x_mm": 5,
            "y_mm": 75,
        },
    ]
    response = create(client, owner, panels, legend={"entries": {"micrograph": "Sample."}})
    assert response.status_code == 201, response.text
    document = response.json()
    assert document["revision"] == 1
    assert document["panels"]["distribution"]["frame"] == {
        "x_mm": 5,
        "y_mm": 5,
        "width_mm": pytest.approx(PLOT_MM[0] * 0.45, abs=0.001),
        "height_mm": pytest.approx(PLOT_MM[1] * 0.45, abs=0.001),
    }
    micrograph = document["panels"]["micrograph"]
    assert (micrograph["natural_width_mm"], micrograph["natural_height_mm"]) == (50.8, 25.4)
    assert {key: value["label"] for key, value in document["panels"].items()} == {
        "distribution": "A",
        "relationship": "B",
        "micrograph": "C",
    }
    assert document["page_height_mm"] == pytest.approx(75 + 25.4 + 5)
    assert set(document["figures"]) == {
        first["result"]["version_id"],
        second["result"]["version_id"],
    }
    assert set(document["images"]) == {image["image_id"]}
    assert document["updates"] == {}
    assert "storage_path" not in json.dumps(document)

    base = f"/api/v1/projects/{owner}/figure-compositions"
    assert (
        create(client, owner, panels, legend={"entries": {"micrograph": "Sample."}}).json()[
            "composition_id"
        ]
        == document["composition_id"]
    )
    assert create(client, owner, panels[:1]).status_code == 409
    listing = client.get(base).json()
    assert listing["total"] == 1
    assert listing["compositions"][0]["title"] == "Figure 1"
    # Figures are separate from Report and Slides libraries.
    assert client.get(f"/api/v1/projects/{owner}/reports").json()["total"] == 0
    assert client.get(f"/api/v1/projects/{owner}/slides").json()["total"] == 0

    # An image used by a figure is retained.
    deleted = client.delete(f"/api/v1/projects/{owner}/plot-reference-images/{image['image_id']}")
    assert deleted.status_code == 409

    outsider = new_project(client)
    assert client.get(f"/api/v1/projects/{outsider}/figure-compositions").json()["total"] == 0
    assert (
        client.get(
            f"/api/v1/projects/{outsider}/figure-compositions/{document['composition_id']}"
        ).status_code
        == 404
    )
    foreign = create(client, outsider, panels[:1], request_id="foreign")
    assert foreign.status_code == 404

    beyond = create(client, owner, [plot_panel("large", first, 10, 5, scale=1)], request_id="big")
    assert beyond.status_code == 422
    assert beyond.json()["error"]["code"] == "INVALID_FIGURE_LAYOUT"


def test_operations_are_revisioned_idempotent_and_conflict_checked(client):
    owner = new_project(client)
    first = plot(client, owner)
    document = create(client, owner, [plot_panel("a", first, 5, 5)]).json()
    move = [{"op": "set_panel_geometry", "panels": {"a": {"x_mm": 20, "y_mm": 10, "scale": 0.3}}}]
    moved = operate(client, document, move)
    assert moved.status_code == 200, moved.text
    moved = moved.json()
    assert moved["revision"] == 2
    assert moved["panels"]["a"]["frame"]["x_mm"] == 20
    assert operate(client, document, move).json()["revision"] == 2
    changed_key = operate(client, document, [{"op": "set_title", "title": "Other"}])
    assert changed_key.status_code == 409
    stale = operate(client, document, [{"op": "set_title", "title": "Other"}], "stale")
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "FIGURE_CONFLICT"
    outside = operate(
        client,
        moved,
        [{"op": "set_panel_geometry", "panels": {"a": {"x_mm": 200, "y_mm": 0, "scale": 1}}}],
        "outside",
    )
    assert outside.status_code == 422
    missing = operate(client, moved, [{"op": "remove_panel", "panel_id": "missing"}], "missing")
    assert missing.status_code == 404

    base = f"/api/v1/projects/{owner}/figure-compositions/{document['composition_id']}"
    content = moved["content"] | {"title": "Saved title"}
    saved = client.put(base, json={"base_revision": 2, "content": content, "summary": "Renamed"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 3
    assert client.put(base, json={"base_revision": 2, "content": content}).status_code == 409
    history = client.get(base + "/history").json()
    assert [item["revision"] for item in history["revisions"]] == [3, 2, 1]
    assert history["revisions"][0]["summary"] == "Renamed"
    assert client.get(base + "/revisions/1").json()["panels"][0]["x_mm"] == 5
    assert client.get(base + "/revisions/9").status_code == 404
    assert client.get(base + "/content").json()["title"] == "Saved title"


def test_newer_plot_versions_are_offered_but_never_applied(client):
    owner = new_project(client)
    first = plot(client, owner)
    document = create(client, owner, [plot_panel("a", first, 5, 5)]).json()
    newer = wait(client, update(client, first, {"figure_width": 6, "figure_height": 4}).json())
    newer_id = newer["result"]["version_id"]
    base = f"/api/v1/projects/{owner}/figure-compositions/{document['composition_id']}"
    current = client.get(base).json()
    assert current["updates"] == {"a": newer_id}
    assert newer_id in current["figures"]
    assert current["content"]["panels"][0]["content"]["version_id"] == first["result"]["version_id"]
    assert current["revision"] == 1

    ignored = current["content"]["panels"][0]
    ignored["content"]["ignored_version_id"] = newer_id
    replaced = operate(client, current, [{"op": "replace_panel", "panel": ignored}], "ignore")
    assert replaced.json()["updates"] == {}

    # An explicit shared selection is the newest version documents should follow.
    plot_id = first["result"]["plot_id"]
    selected = client.post(
        f"/api/v1/projects/{owner}/shared-figures/{plot_id}",
        json={"version_id": first["result"]["version_id"]},
    )
    assert selected.status_code == 200, selected.text
    other = create(client, owner, [plot_panel("a", newer, 5, 5)], request_id="second").json()
    assert other["updates"] == {"a": first["result"]["version_id"]}


@pytest.mark.parametrize("format", ["svg", "pdf", "png", "tiff"])
def test_export_composes_one_page_at_physical_size(client, format):
    owner = new_project(client)
    first, second = plot(client, owner), plot(client, owner)
    image = upload(client, owner, content=png("teal", size=(600, 300))).json()
    document = create(
        client,
        owner,
        [
            plot_panel("a", first, 5, 5, scale=0.4),
            plot_panel("b", second, 97, 5, scale=0.4),
            {
                "id": "c",
                "content": {"type": "image", "image_id": image["image_id"]},
                "x_mm": 5,
                "y_mm": 70,
            },
        ],
        page={"width_mm": 183, "height_mm": 297, "height_mode": "auto"},
    ).json()
    assert document["revision"] == 1, document
    height = document["page_height_mm"]
    url = (
        f"/api/v1/projects/{owner}/figure-compositions/{document['composition_id']}"
        f"/exports/{format}"
    )
    response = client.get(url)
    assert response.status_code == 200, response.text[:300]
    assert "attachment;" in response.headers["content-disposition"]
    assert "Figure-1-r1." + format in response.headers["content-disposition"]
    if format == "svg":
        root = ET.fromstring(response.content)
        assert root.get("width") == "183mm"
        assert root.get("viewBox") == f"0 0 183 {height:g}"
        assert [text.text for text in root.iter(SVG + "text")][-3:] == ["A", "B", "C"]
        ids = [node.get("id") for node in root.iter() if node.get("id")]
        assert len(ids) == len(set(ids))
        references = [
            value[1:]
            for node in root.iter()
            for key, value in node.attrib.items()
            if key.endswith("href") and value.startswith("#")
        ]
        assert set(references).issubset(ids)
        nested = [node for node in root if node.tag == SVG + "svg"]
        assert [node.get("x") for node in nested] == ["5", "97"]
        assert (
            root.find(SVG + "image")
            .get("{http://www.w3.org/1999/xlink}href")
            .startswith("data:image/png;base64,")
        )
    elif format == "pdf":
        page = PdfReader(io.BytesIO(response.content)).pages[0]
        assert float(page.mediabox.width) == pytest.approx(183 / 25.4 * 72, abs=0.05)
        assert float(page.mediabox.height) == pytest.approx(height / 25.4 * 72, abs=0.05)
    else:
        with Image.open(io.BytesIO(response.content)) as raster:
            assert raster.format == format.upper()
            assert raster.size == (round(183 / 25.4 * 300), round(height / 25.4 * 300))
            assert raster.info["dpi"] == pytest.approx((300, 300), abs=0.1)
            # The embedded image is drawn inside panel C.
            x = round(20 / 25.4 * 300)
            y = round(80 / 25.4 * 300)
            assert raster.convert("RGB").getpixel((x, y)) == (0, 128, 128)
