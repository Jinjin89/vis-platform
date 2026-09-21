import io
from concurrent.futures import ThreadPoolExecutor
from xml.etree import ElementTree as ET

import pytest
from PIL import Image
from pypdf import PdfReader
from test_datasets import data_client as data_client
from test_datasets import project, research_plan, upload_collection, wait_run
from test_parameters import create, update


def export_url(snapshot, format):
    result = snapshot["result"]
    return (
        f"/api/v1/projects/{snapshot['project_id']}/plots/{result['plot_id']}"
        f"/versions/{result['version_id']}/exports/{format}"
    )


def check_export(response, format, width, height):
    assert response.status_code == 200, response.text[:300]
    media = {"png": "image/png", "pdf": "application/pdf", "svg": "image/svg+xml"}[format]
    assert response.headers["content-type"].split(";")[0] == media
    assert "attachment;" in response.headers["content-disposition"]
    assert f".{format}" in response.headers["content-disposition"]
    if format == "png":
        with Image.open(io.BytesIO(response.content)) as image:
            assert image.size == (round(width * 300), round(height * 300))
            assert image.info["dpi"] == pytest.approx((300, 300), abs=0.1)
            assert image.convert("RGB").getpixel((0, 0)) == (255, 255, 255)
            assert image.convert("RGB").getpixel((image.width - 1, image.height - 1)) == (
                255,
                255,
                255,
            )
    elif format == "pdf":
        reader = PdfReader(io.BytesIO(response.content))
        assert len(reader.pages) == 1
        page = reader.pages[0]
        assert float(page.mediabox.width) == pytest.approx(width * 72, abs=0.01)
        assert float(page.mediabox.height) == pytest.approx(height * 72, abs=0.01)
        # The PDF is not a screenshot wrapped in a document.
        assert len(page.images) == 0
        assert len(page.get_contents().get_data()) > 100
    else:
        root = ET.fromstring(response.content)
        assert root.get("width") == f"{width:g}in"
        assert root.get("height") == f"{height:g}in"
        assert b"#f1efe8" not in response.content
        assert all(
            node.get("fill") != "#fffefb"
            for node in root.findall("{http://www.w3.org/2000/svg}rect")
        )
        assert b"VIS PLATFORM" not in response.content


@pytest.mark.parametrize("format", ["png", "pdf", "svg"])
def test_demo_exports_have_clean_backgrounds_and_correct_dimensions(client, format):
    saved = create(client)
    response = client.get(export_url(saved, format))
    check_export(response, format, 8, 5.5)
    assert client.get(export_url(saved, format)).content == response.content
    assert (
        client.get(
            f"/api/v1/projects/{saved['project_id']}/plots/{saved['result']['plot_id']}/versions"
        ).json()["current_version_id"]
        == saved["result"]["version_id"]
    )


def test_research_exports_preserve_the_saved_plot_without_execution(data_client, monkeypatch):
    client = data_client
    owner = project(client)
    dataset = upload_collection(client, owner)
    plan = research_plan(dataset["objects"])
    plan["figure_size"] = {"width": 7.25, "height": 4.75}
    response = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Compare groups"},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
            "research_plan": plan,
        },
    )
    assert response.status_code == 202
    saved = wait_run(client, response.json())
    assert saved["status"] == "completed", saved
    before = client.get(saved["result"]["preview"]["href"]).content

    async def no_execution(*args, **kwargs):
        raise AssertionError("Export must not repeat analysis, rendering, or model calls")

    monkeypatch.setattr(client.app.state.dataset_service.worker, "execute", no_execution)
    for format in ("png", "pdf", "svg"):
        check_export(client.get(export_url(saved, format)), format, 7.25, 4.75)
    assert client.get(saved["result"]["preview"]["href"]).content == before
    assert client.get(f"/api/v1/projects/{owner}/analysis-results").json()["total"] == 1


def test_history_export_selects_the_requested_versions_size(client):
    first = create(client)
    changed = wait_run(
        client, update(client, first, {"figure_width": 12, "figure_height": 4}).json()
    )
    for snapshot, width, height in [(first, 8, 5.5), (changed, 12, 4)]:
        for format in ("pdf", "svg"):
            check_export(client.get(export_url(snapshot, format)), format, width, height)


def test_export_checks_project_plot_version_and_format(client):
    saved = create(client)
    url = export_url(saved, "svg")
    for invalid in [
        url.replace(saved["project_id"], "project_other"),
        url.replace(saved["result"]["plot_id"], "plot_other"),
        url.replace(saved["result"]["version_id"], "version_other"),
    ]:
        assert client.get(invalid).status_code == 404
    assert client.get(export_url(saved, "jpeg")).status_code == 422


def test_old_demo_frame_is_removed_from_export_without_mutating_saved_svg(client):
    saved = create(client)
    artifact = client.app.state.coordinator.get_artifact(saved["result"]["preview"]["artifact_id"])
    from pathlib import Path

    source = Path(artifact["storage_path"])
    root = ET.fromstring(source.read_bytes())
    background = root.find("./*[@data-role='figure-background']")
    background.attrib.pop("data-role")
    background.set("fill", "#f1efe8")
    root.insert(
        1,
        ET.Element(
            "{http://www.w3.org/2000/svg}rect",
            {
                "x": "24",
                "y": "20",
                "width": "912",
                "height": "520",
                "rx": "18",
                "fill": "#fffefb",
            },
        ),
    )
    original = ET.tostring(root)
    source.write_bytes(original)
    for format in ("svg", "png", "pdf"):
        check_export(client.get(export_url(saved, format)), format, 8, 5.5)
    assert source.read_bytes() == original


def test_concurrent_downloads_publish_complete_files(client):
    saved = create(client)
    url = export_url(saved, "png")
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: client.get(url), range(3)))
    for response in responses:
        check_export(response, "png", 8, 5.5)
    assert len({response.content for response in responses}) == 1


def test_export_rejects_external_svg_resources(client):
    from pathlib import Path

    saved = create(client)
    artifact = client.app.state.coordinator.get_artifact(saved["result"]["preview"]["artifact_id"])
    source = Path(artifact["storage_path"])
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="file:///etc/passwd"/>'
        '<path d="M0 0 L10 10"/></svg>'
    )
    response = client.get(export_url(saved, "png"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "FIGURE_EXPORT_FAILED"
    assert "passwd" not in response.text
