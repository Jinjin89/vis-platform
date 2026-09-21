import asyncio
import csv
import math
from xml.etree import ElementTree as ET

import pytest
from test_datasets import data_client as data_client
from test_datasets import project, wait_dataset, wait_run
from transcriptomic_plans import transcriptomic_plan

from vis_platform_backend.contracts.figures import FigureSize
from vis_platform_backend.data.demo_transcriptomics import (
    DEMO_SOURCE_IDS,
    SINGLE_CELL_ID,
    SPATIAL_ID,
    DemoTranscriptomicsProvider,
)


def test_demo_collections_are_deterministic_and_objects_align(tmp_path):
    async def check():
        first = DemoTranscriptomicsProvider(tmp_path / "one")
        second = DemoTranscriptomicsProvider(tmp_path / "two")
        for source_id, key in [(SINGLE_CELL_ID, "cell_id"), (SPATIAL_ID, "spot_id")]:
            manifest = await first.describe(source_id)
            repeated = await second.describe(source_id)
            assert manifest.contains_demo_data
            assert len(manifest.objects) == 5
            assert [item.sha256 for item in manifest.objects] == [
                item.sha256 for item in repeated.objects
            ]
            tables = {}
            for item in manifest.objects:
                destination = tmp_path / f"{source_id}-{item.source_object_id}.csv"
                await first.materialize(item, destination)
                with destination.open() as stream:
                    tables[item.source_object_id] = list(csv.DictReader(stream))
                assert len(tables[item.source_object_id]) == item.description.dimensions[0]
            count_rows, expression_rows = tables["counts"], tables["expression"]
            assert len(tables["genes"]) == 24
            assert [row[key] for row in count_rows] == [row[key] for row in expression_rows]
            assert len({row[key] for row in count_rows}) == len(count_rows)
            for counts, expression in zip(count_rows, expression_rows, strict=True):
                total = sum(int(value) for column, value in counts.items() if column != key)
                assert total > 0
                for gene, value in counts.items():
                    if gene != key:
                        assert int(value) >= 0
                        assert float(expression[gene]) == pytest.approx(
                            math.log1p(int(value) / total * 10_000), abs=1e-6
                        )
            if source_id == SINGLE_CELL_ID:
                assert len(tables["cells"]) == 360
                assert len({row["cell_type"] for row in tables["cells"]}) == 4
                assert "not a computed UMAP" in next(
                    item.description.description
                    for item in manifest.objects
                    if item.source_object_id == "embedding"
                )
            else:
                assert len(tables["spots"]) > 300
                assert len({row["tissue_domain"] for row in tables["spots"]}) == 4
                assert {row["spot_id"] for row in tables["positions"]} == {
                    row["spot_id"] for row in tables["spots"]
                }

    asyncio.run(check())


@pytest.mark.parametrize("source_id", [SINGLE_CELL_ID, SPATIAL_ID])
def test_demo_import_and_render_use_the_real_versioned_data_path(data_client, source_id):
    client = data_client
    owner = project(client)
    catalog = client.get(f"/api/v1/projects/{owner}/data-sources/analysis-platform").json()
    assert catalog["connected"] is False
    assert {item["source_id"] for item in catalog["datasets"]} == DEMO_SOURCE_IDS
    assert all(item["contains_demo_data"] for item in catalog["datasets"])
    assert client.get(f"/api/v1/projects/{owner}/datasets").json()["total"] == 0
    created = client.post(
        "/api/v1/data-bundles",
        json={
            "project_id": owner,
            "name": "Demo",
            "source_kind": "analysis_platform",
            "source_id": source_id,
        },
    )
    assert created.status_code == 201, created.text
    dataset_id = created.json()["dataset_id"]
    client.post(f"/api/v1/data-bundles/{dataset_id}/finalize", params={"project_id": owner})
    dataset = wait_dataset(client, owner, dataset_id)
    assert dataset["state"] == "ready" and dataset["contains_demo_data"]
    assert dataset["interpretation_status"] == "source_provided"
    plan = transcriptomic_plan(dataset["objects"], spatial=source_id == SPATIAL_ID)
    response = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": plan.title},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset_id]},
            "research_plan": plan.model_dump(mode="json"),
        },
    )
    assert response.status_code == 202, response.text
    completed = wait_run(client, response.json())
    assert completed["status"] == "completed", completed
    result = completed["result"]
    assert result["execution_mode"] == "r" and result["contains_demo_data"]
    assert result["analysis_results"][0]["contains_demo_data"]
    assert result["figure_size"] == plan.figure_size.model_dump(mode="json")
    controls = {item["id"]: item for item in result["controls"]}
    assert controls["figure_width"]["input_mode"] == "number"
    assert controls["figure_height"]["input_mode"] == "number"
    svg = ET.fromstring(client.get(result["preview"]["href"]).content)
    assert svg.get("width") == f"{plan.figure_size.width:g}in"
    assert svg.get("height") == f"{plan.figure_size.height:g}in"
    assert controls["figure_width"]["value"] == plan.figure_size.width
    assert controls["figure_height"]["value"] == plan.figure_size.height
    assert [float(value) for value in svg.get("viewBox").split()][2:] == [
        plan.figure_size.width * 72,
        plan.figure_size.height * 72,
    ]
    change = client.post(
        f"/api/v1/plots/{result['plot_id']}/parameters",
        json={
            "project_id": owner,
            "base_version_id": result["version_id"],
            "changes": {"figure_width": 12, "figure_height": 4},
        },
    )
    assert change.status_code == 202, change.text
    changed = wait_run(client, change.json())
    assert changed["status"] == "completed", changed
    assert changed["result"]["figure_size"] == {"width": 12, "height": 4, "unit": "in"}
    assert (
        changed["result"]["analysis_results"][0]["result_id"]
        == result["analysis_results"][0]["result_id"]
    )
    assert changed["result"]["contains_demo_data"] is True
    svg = ET.fromstring(client.get(changed["result"]["preview"]["href"]).content)
    assert svg.get("width") == "12in" and svg.get("height") == "4in"
    assert [float(value) for value in svg.get("viewBox").split()][2:] == [864, 288]
    restore = client.post(
        f"/api/v1/plots/{result['plot_id']}/restore",
        json={"project_id": owner, "source_version_id": result["version_id"]},
    )
    restored = wait_run(client, restore.json())
    assert restored["result"]["figure_size"] == result["figure_size"]
    assert client.get(f"/api/v1/projects/{owner}/analysis-results").json()["total"] == 1
    assert client.get(f"/api/v1/projects/{owner}/datasets").json()["total"] == 1


def test_figure_size_rejects_invalid_or_unbounded_values():
    for size in [
        {"width": 0},
        {"height": 31},
        {"width": float("nan")},
        {"width": 6.005},
        {"unit": "px"},
    ]:
        with pytest.raises(ValueError):
            FigureSize.model_validate({"width": 6, "height": 4, **size})


def test_rendering_plan_schema_only_offers_supported_update_modes():
    from vis_platform_backend.contracts.research import ResearchPlan

    schema = ResearchPlan.model_json_schema()
    for name in (
        "RenderNumberControl",
        "RenderChoiceControl",
        "RenderTextControl",
        "RenderBooleanControl",
    ):
        strategy = schema["$defs"][name]["properties"]["update_strategy"]
        assert strategy["const"] == "rerun"


def test_backend_dimensions_are_available_when_model_returns_no_controls(data_client):
    from test_datasets import research_plan, upload_collection

    client = data_client
    owner = project(client)
    dataset = upload_collection(client, owner)
    plan = research_plan(dataset["objects"])
    plan["controls"] = []
    plan["analysis_parameters"] = {"offset": 2}
    plan["analysis_code"] = (
        "list(values=data.frame(value=inputs$observations$value + analysis_parameters$offset))"
    )
    plan["outputs"] = [
        {
            "key": "values",
            "name": "Shifted values",
            "description": "Values with the requested offset.",
        }
    ]
    plan["render_code"] = "plot(results$values$value)"
    response = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Plot shifted values"},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
            "research_plan": plan,
        },
    )
    completed = wait_run(client, response.json())
    assert completed["status"] == "completed", completed
    assert {control["id"] for control in completed["result"]["controls"]} == {
        "figure_width",
        "figure_height",
    }
    assert (
        completed["result"]["analysis_results"][0]["objects"][0]["columns"][0]["numeric"]["mean"]
        == 6
    )
