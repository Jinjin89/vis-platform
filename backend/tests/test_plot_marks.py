from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
from test_agent_context import RecordingAgent, plot
from test_datasets import RUNTIME, research_plan, upload_collection, wait_run
from test_reference_images import ReferenceDataAgent, project

from vis_platform_backend.app import create_app
from vis_platform_backend.config import Settings
from vis_platform_backend.contracts.assistant_turns import AssistantTurnRequest
from vis_platform_backend.contracts.plot_marks import ImageMark
from vis_platform_backend.domain.plot_marks import PlotPanel, describe_marks, parse_plot_map
from vis_platform_backend.services.plot_marks import MARK, MARKED_IMAGE_ID, draw_marks

TWO_PANELS = """
par(mfrow = c(1, 2))
plot(c(1, 10), c(0, 100), main = params$title, col = params$color, xlab = "Dose", ylab = "Response")
plot(c(1, 10), c(1, 1000), log = "y", col = params$color, xlab = "Dose", ylab = "Count")
"""


def turn(owner, **options):
    return {
        "project_id": owner,
        "request": {"text": "Label 1 and 2"},
        "data_scope": {"mode": "auto"},
        **options,
    }


def test_marks_belong_to_the_version_they_were_placed_on():
    point = {"number": 1, "kind": "point", "x": 0.5, "y": 0.5}
    with pytest.raises(ValidationError, match="plot version"):
        AssistantTurnRequest.model_validate(turn("p", plot_marks=[point]))
    with pytest.raises(ValidationError, match="once"):
        AssistantTurnRequest.model_validate(
            turn("p", base_version_id="v", plot_marks=[point, point])
        )
    with pytest.raises(ValidationError, match="no width"):
        ImageMark.model_validate({**point, "width": 0.1})
    with pytest.raises(ValidationError, match="inside"):
        ImageMark.model_validate(
            {"number": 2, "kind": "area", "x": 0.8, "y": 0, "width": 0.3, "height": 0.1}
        )
    with pytest.raises(ValidationError, match="width and a height"):
        ImageMark.model_validate({"number": 2, "kind": "area", "x": 0.1, "y": 0.1})
    request = AssistantTurnRequest.model_validate(turn("p", base_version_id="v"))
    assert request.plot_marks == []


def test_marks_are_read_in_each_regions_data_units():
    panels = (
        PlotPanel(0.1, 0.5, 0.2, 0.9, (0, 10), (0, 100), x_log=False, y_log=False),
        PlotPanel(0.6, 0.9, 0.2, 0.9, (0, 1), (0, 3), x_log=False, y_log=True),
    )
    marks = [
        ImageMark(number=1, kind="point", x=0.3, y=1 - 0.55),
        ImageMark(number=2, kind="point", x=0.75, y=1 - 0.55),
        ImageMark(number=3, kind="point", x=0.02, y=0.02),
        ImageMark(number=4, kind="area", x=0.4, y=0.1, width=0.3, height=0.3),
    ]
    described = describe_marks(marks, panels)
    assert described[0] == {
        "number": 1,
        "kind": "point",
        "image_position": {"x": 0.3, "y": 0.45},
        "plot_regions": [{"region": 1, "x": 5.0, "y": 50.0}],
    }
    # A log axis records powers of ten; the midpoint of 10^0..10^3 is about 31.6.
    assert described[1]["plot_regions"] == [{"region": 2, "x": 0.5, "y": 31.62}]
    assert described[2]["plot_regions"] == []
    area = described[3]
    assert area["image_area"] == {"left": 0.4, "top": 0.1, "right": 0.7, "bottom": 0.4}
    assert [region["region"] for region in area["plot_regions"]] == [1, 2]
    assert area["plot_regions"][0] == {
        "region": 1,
        "x_from": 7.5,
        "x_to": 10.0,
        "y_from": 57.14,
        "y_to": 100.0,
    }
    # Without a recorded drawing only the place on the image is known.
    assert "plot_regions" not in describe_marks(marks[:1], None)[0]


def test_malformed_plot_regions_are_left_out():
    good = {"x": [0.1, 0.5], "y": [0.2, 0.9], "usr": [0, 1, 0, 1], "xlog": False, "ylog": False}
    parsed = parse_plot_map(
        {
            "panels": [
                good,
                {**good, "x": [0.5, 0.1]},
                {**good, "usr": [0, 1, 0]},
                {**good, "usr": [0, 1, 0, "NaN"]},
                {**good, "xlog": "yes"},
                {"x": 1},
            ]
        }
    )
    assert len(parsed) == 1
    assert parse_plot_map({"panels": "none"}) == ()
    assert parse_plot_map([]) == ()


def test_marks_are_numbered_on_the_image():
    image = Image.new("RGB", (400, 200), "white")
    marked = draw_marks(
        image,
        [
            ImageMark(number=1, kind="point", x=0.25, y=0.5),
            ImageMark(number=2, kind="area", x=0.6, y=0.3, width=0.3, height=0.4),
        ],
    )
    pixels = marked.load()
    assert pixels[round(0.6 * 400) + 1, round(0.5 * 200)] == MARK
    # The marked place itself stays visible inside the ring.
    assert pixels[100, 100] == (255, 255, 255)


def position(panel, x, y):
    """Where a data value appears on the image, from the top-left corner."""
    left, right = panel["x"]
    bottom, top = panel["y"]
    x0, x1, y0, y1 = panel["usr"]
    if panel["ylog"]:
        import math

        y = math.log10(y)
    return (
        left + (x - x0) / (x1 - x0) * (right - left),
        1 - (bottom + (y - y0) / (y1 - y0) * (top - bottom)),
    )


@pytest.mark.skipif(
    not (RUNTIME / "usr/lib/R").is_dir(), reason="Restricted R runtime is unavailable"
)
def test_marks_reach_both_planners_as_an_image_and_data_values(tmp_path):
    refinement = {
        "kind": "plot_refine",
        "subtype": "visual",
        "normalized_request": "Label the marked points.",
        "confidence": 1,
        "next_action": "refine_context",
        "decision_summary": "Label the points the user marked.",
        "refinement": {
            "reuse_data": True,
            "execution_strategy": "regenerate_render",
            "changes": [{"target": "labels", "value": "marked points", "change_class": "visual"}],
        },
    }
    agent = RecordingAgent([plot(), refinement])
    data_agent = ReferenceDataAgent()
    config = Settings(
        database_path=tmp_path / "data.sqlite",
        artifact_root=tmp_path / "artifacts",
        r_home=RUNTIME / "usr/lib/R",
        r_sandbox=RUNTIME / "vis-r-sandbox",
    )
    with TestClient(create_app(config, intent_agent=agent, data_agent=data_agent)) as client:
        owner = project(client)
        dataset = upload_collection(client, owner)
        plan = research_plan(dataset["objects"])
        plan["render_code"] = TWO_PANELS
        original_plan = data_agent.plan

        async def two_panels(context):
            decision = await original_plan(context)
            if not context.get("render_only"):
                decision.plan = decision.plan.model_copy(update={"render_code": TWO_PANELS})
            return decision

        data_agent.plan = two_panels
        scope = {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]}
        response = client.post("/api/v1/assistant-turns", json=turn(owner, data_scope=scope))
        assert response.status_code == 200, response.text
        created = wait_run(client, response.json()["plot_run"])
        assert created["status"] == "completed", created
        # Turns without marks are planned exactly as before.
        assert "plot_marks" not in data_agent.contexts[0]
        assert "plot_marks" not in agent.inputs[0].workspace_context
        recorded = json.loads(
            (config.artifact_root / created["run_id"] / "plot-map.json").read_text()
        )["panels"]
        assert len(recorded) == 2
        assert [panel["ylog"] for panel in recorded] == [False, True]

        first = position(recorded[0], 5.5, 50)
        second = position(recorded[1], 5.5, 100)
        base = created["result"]
        response = client.post(
            "/api/v1/assistant-turns",
            json=turn(
                owner,
                data_scope=scope,
                base_version_id=base["version_id"],
                plot_marks=[
                    {"number": 1, "kind": "point", "x": first[0], "y": first[1]},
                    {"number": 2, "kind": "point", "x": second[0], "y": second[1]},
                    {"number": 3, "kind": "area", "x": 0, "y": 0, "width": 0.04, "height": 0.04},
                ],
            ),
        )
        assert response.status_code == 200, response.text
        changed = wait_run(client, response.json()["plot_run"])
        assert changed["status"] == "completed", changed

        marks = agent.inputs[1].workspace_context["plot_marks"]
        assert marks[0]["plot_regions"] == [
            {"region": 1, "x": pytest.approx(5.5, rel=1e-3), "y": pytest.approx(50, rel=1e-3)}
        ]
        assert marks[1]["plot_regions"] == [
            {"region": 2, "x": pytest.approx(5.5, rel=1e-3), "y": pytest.approx(100, rel=1e-3)}
        ]
        assert marks[2]["plot_regions"] == []
        image = agent.inputs[1].reference_images[-1]
        assert image.image_id == MARKED_IMAGE_ID
        with Image.open(io.BytesIO(image.data)) as raster:
            assert max(raster.size) == 1600
        planned = data_agent.contexts[-1]
        assert planned["plot_marks"] == marks
        assert planned.images[-1].image_id == MARKED_IMAGE_ID
        assert planned["render_only"] is True

        # A restored version keeps the drawing's regions, so it can be marked again.
        restored = client.post(
            f"/api/v1/plots/{base['plot_id']}/restore",
            json={"project_id": owner, "source_version_id": base["version_id"]},
        )
        saved = wait_run(client, restored.json())
        assert saved["status"] == "completed", saved
        assert (config.artifact_root / saved["run_id"] / "plot-map.json").is_file()
