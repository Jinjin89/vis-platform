from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vis_platform_backend.app import create_app
from vis_platform_backend.config import Settings
from vis_platform_backend.contracts.research import (
    DataAnswer,
    DatasetInterpretation,
    ResearchDecision,
)
from vis_platform_backend.execution.runner import RExecutionError, RWorker

RUNTIME = Path(__file__).resolve().parents[1] / ".runtime"


class ProfileOnlyAgent:
    async def answer(self, context):
        return DataAnswer(message=f"There are {len(context['datasets'])} datasets in this scope.")

    async def interpret(self, context):
        return DatasetInterpretation(description="Related uploaded measurement tables.")

    async def plan(self, context):
        return ResearchDecision.model_validate(
            {
                "action": "execute",
                "summary": "Compare the uploaded measurements.",
                "plan": research_plan(context["objects"]),
            }
        )


def wait_dataset(client, project, dataset):
    for _ in range(200):
        response = client.get(f"/api/v1/data-bundles/{dataset}", params={"project_id": project})
        assert response.status_code == 200, response.text
        result = response.json()
        if result["state"] != "processing":
            return result
        time.sleep(0.02)
    raise AssertionError("Dataset inspection did not finish")


def upload_collection(client, project):
    created = client.post(
        "/api/v1/data-bundles", json={"project_id": project, "name": "Treatment study"}
    )
    assert created.status_code == 201, created.text
    dataset = created.json()["dataset_id"]
    for name, contents in [
        ("observations.csv", "sample_id,value\ns1,1\ns2,3\ns3,5\ns4,7\n"),
        ("samples.csv", "sample_id,group\ns1,A\ns2,A\ns3,B\ns4,B\n"),
    ]:
        response = client.post(
            f"/api/v1/data-bundles/{dataset}/files",
            params={"project_id": project, "name": name},
            content=contents,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 201, response.text
    response = client.post(
        f"/api/v1/data-bundles/{dataset}/finalize", params={"project_id": project}
    )
    assert response.status_code == 202, response.text
    return wait_dataset(client, project, dataset)


def research_plan(objects, *, render=True):
    refs = {
        item["name"]: {"object_id": item["object_id"], "revision_id": item["revision_id"]}
        for item in objects
    }
    return {
        "title": "Treatment comparison",
        "figure_size": {"width": 6.5, "height": 4.5} if render else None,
        "description": "Mean observed value by treatment group.",
        "inputs": [{"alias": name, "reference": ref} for name, ref in refs.items()],
        "relationships": [
            {
                "relationship_id": "samples",
                "left_object_id": refs["observations"]["object_id"],
                "right_object_id": refs["samples"]["object_id"],
                "left_key": "sample_id",
                "right_key": "sample_id",
                "kind": "join",
                "cardinality": "one_to_one",
            }
        ],
        "analysis_code": (
            "joined <- merge(inputs$observations, inputs$samples, "
            'by="sample_id", sort=FALSE); list(comparison=aggregate(value ~ '
            "group, joined, mean))"
        ),
        "outputs": [
            {
                "key": "comparison",
                "name": "Group means",
                "description": "Mean measured value for each group.",
            }
        ],
        "render_code": (
            "barplot(results$comparison$value, "
            "names.arg=results$comparison$group, main=params$title, "
            'col=params$color, ylab="Mean value")'
        )
        if render
        else None,
        "controls": [
            {"type": "text", "id": "title", "label": "Title", "value": "Treatment comparison"},
            {
                "type": "choice",
                "id": "color",
                "label": "Color",
                "value": "purple",
                "options": [
                    {"value": "purple", "label": "Purple"},
                    {"value": "steelblue", "label": "Blue"},
                ],
            },
        ]
        if render
        else [],
    }


def wait_run(client, accepted):
    for _ in range(400):
        response = client.get(accepted["links"]["status"])
        assert response.status_code == 200, response.text
        result = response.json()
        if result["status"] in {"completed", "failed", "cancelled"}:
            return result
        time.sleep(0.025)
    raise AssertionError("Research execution did not finish")


@pytest.fixture
def data_client(tmp_path):
    settings = Settings(
        database_path=tmp_path / "data.sqlite",
        artifact_root=tmp_path / "artifacts",
        r_home=RUNTIME / "usr/lib/R",
        r_sandbox=RUNTIME / "vis-r-sandbox",
    )
    with TestClient(create_app(settings, data_agent=ProfileOnlyAgent())) as client:
        yield client


def project(client):
    return client.post("/api/v1/projects", json={"name": "Research test"}).json()["project_id"]


def test_uploads_are_discoverable_before_any_figure_and_preserve_revisions(data_client):
    client = data_client
    owner = project(client)
    dataset = upload_collection(client, owner)
    assert dataset["state"] == "ready", dataset
    assert len(dataset["objects"]) == 2
    assert dataset["objects"][0]["dimensions"] == [4, 2]
    assert dataset["objects"][0]["columns"][1]["numeric"]["mean"] == 4
    listed = client.get(f"/api/v1/projects/{owner}/datasets").json()
    assert listed["total"] == 1 and listed["complete"]
    assert not any("path" in key for obj in dataset["objects"] for key in obj)
    original = dataset["revision_id"]
    edited = client.patch(
        f"/api/v1/data-bundles/{dataset['dataset_id']}",
        json={
            "project_id": owner,
            "base_revision_id": original,
            "description": "Corrected study description",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["revision_id"] != original
    previous = client.get(
        f"/api/v1/data-bundles/{dataset['dataset_id']}",
        params={"project_id": owner, "revision_id": original},
    ).json()
    assert previous["description"] == dataset["description"]
    outsider = project(client)
    assert (
        client.get(
            f"/api/v1/data-bundles/{dataset['dataset_id']}", params={"project_id": outsider}
        ).status_code
        == 404
    )
    obj = dataset["objects"][0]
    assert (
        client.get(
            f"/api/v1/objects/{obj['object_id']}",
            params={"project_id": outsider, "revision_id": original},
        ).status_code
        == 404
    )


def test_real_join_analysis_plot_controls_and_history_reuse_results(data_client):
    client = data_client
    owner = project(client)
    dataset = upload_collection(client, owner)
    response = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Compare treatment group means"},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
            "research_plan": research_plan(dataset["objects"]),
        },
    )
    assert response.status_code == 202, response.text
    completed = wait_run(client, response.json())
    assert completed["status"] == "completed", completed
    result = completed["result"]
    assert result["execution_mode"] == "r"
    analysis = result["analysis_results"][0]
    csv_artifact = next(item for item in analysis["artifacts"] if item["media_type"] == "text/csv")
    actual = client.get(csv_artifact["href"])
    assert actual.status_code == 200, actual.text
    assert '"A",2' in actual.text and '"B",6' in actual.text
    assert client.get(result["preview"]["href"]).status_code == 200
    changed = client.post(
        f"/api/v1/plots/{result['plot_id']}/parameters",
        json={
            "project_id": owner,
            "base_version_id": result["version_id"],
            "changes": {"color": "steelblue"},
        },
    )
    assert changed.status_code == 202, changed.text
    updated = wait_run(client, changed.json())
    assert updated["status"] == "completed", updated
    assert updated["result"]["analysis_results"][0]["result_id"] == analysis["result_id"]
    assert client.get(f"/api/v1/projects/{owner}/analysis-results").json()["total"] == 1
    assert client.get(f"/api/v1/projects/{owner}/datasets").json()["total"] == 1
    restored = client.post(
        f"/api/v1/plots/{result['plot_id']}/restore",
        json={"project_id": owner, "source_version_id": result["version_id"]},
    )
    assert restored.status_code == 202, restored.text
    saved = wait_run(client, restored.json())
    assert saved["status"] == "completed", saved
    assert saved["result"]["analysis_results"][0]["result_id"] == analysis["result_id"]
    assert (
        next(item["value"] for item in saved["result"]["controls"] if item["id"] == "color")
        == "purple"
    )


def test_analysis_only_creates_results_without_a_figure_or_dataset(data_client):
    client = data_client
    owner = project(client)
    dataset = upload_collection(client, owner)
    created = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Calculate group means only"},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
            "research_plan": research_plan(dataset["objects"], render=False),
        },
    )
    assert created.status_code == 202, created.text
    result = wait_run(client, created.json())
    assert result["status"] == "completed", result
    assert result["result"] is None
    assert len(result["analysis_results"]) == 1
    assert client.get(f"/api/v1/projects/{owner}/datasets").json()["total"] == 1


def test_unknown_files_remain_visible_without_claiming_execution_support(data_client):
    client = data_client
    owner = project(client)
    dataset = client.post(
        "/api/v1/data-bundles", json={"project_id": owner, "name": "Unknown collection"}
    ).json()["dataset_id"]
    assert (
        client.post(
            f"/api/v1/data-bundles/{dataset}/files",
            params={"project_id": owner, "name": "unknown.bin"},
            content=b"opaque file",
        ).status_code
        == 201
    )
    client.post(f"/api/v1/data-bundles/{dataset}/finalize", params={"project_id": owner})
    result = wait_dataset(client, owner, dataset)
    assert result["state"] == "ready"
    assert result["objects"][0]["readiness"] == "unsupported"
    assert result["objects"][0]["capabilities"] == []


def test_worker_denies_host_reads_network_and_subprocesses(tmp_path):
    sentinel = tmp_path / "private.txt"
    sentinel.write_text("private-test-sentinel")
    worker = RWorker(RUNTIME / "usr/lib/R", RUNTIME / "vis-r-sandbox", tmp_path / "jobs")
    assert worker.available

    async def run():
        for code in [
            f"readLines({json.dumps(str(sentinel))})",
            'socketConnection("127.0.0.1", port=80, open="r+")',
            'system("echo escaped", intern=TRUE)',
        ]:
            with pytest.raises(RExecutionError):
                await worker.execute(
                    {
                        "mode": "analyze",
                        "params": {},
                        "random_seed": 1,
                        "output_names": ["x"],
                        "code": code,
                    },
                    {},
                )

    asyncio.run(run())


def test_platform_preserves_metadata_and_uses_the_same_object_contract(data_client):
    import httpx

    from vis_platform_backend.data.providers import AnalysisPlatformProvider

    client = data_client
    owner = project(client)
    service = client.app.state.dataset_service
    object_bytes = {
        "observations": b"sample_id,value\ns1,1\ns2,3\ns3,5\ns4,7\n",
        "samples": b"sample_id,group\ns1,A\ns2,A\ns3,B\ns4,B\n",
    }
    current_revision = ["v1"]
    fetched_objects = []

    def response(request):
        if request.url.path == "/api/datasets":
            return httpx.Response(
                200,
                json={
                    "datasets": [
                        {
                            "source_id": "study-1",
                            "revision": current_revision[0],
                            "name": "Platform study",
                            "object_count": 2,
                        }
                    ]
                },
            )
        if request.url.path == "/api/datasets/study-1":
            return httpx.Response(
                200,
                json={
                    "source_id": "study-1",
                    "revision": current_revision[0],
                    "name": "Platform study",
                    "description": "Authoritative platform description.",
                    "objects": [
                        {
                            "source_object_id": key,
                            "description": {
                                "name": key,
                                "format": "csv",
                                "kind": "table",
                                "description": f"Platform {key}",
                                "columns": [
                                    {"name": "sample_id", "data_type": "string"},
                                    {"name": "value", "data_type": "number", "unit": "mg"},
                                ]
                                if key == "observations"
                                else [
                                    {"name": "sample_id", "data_type": "string"},
                                    {"name": "group", "data_type": "string"},
                                ],
                            },
                            "content_path": f"objects/{key}",
                        }
                        for key in object_bytes
                    ],
                    "relationships": [
                        {
                            "relationship_id": "sample-map",
                            "left_object_id": "observations",
                            "right_object_id": "samples",
                            "kind": "join",
                            "left_key": "sample_id",
                            "right_key": "sample_id",
                            "cardinality": "one_to_one",
                        }
                    ],
                },
            )
        key = request.url.path.split("/")[-1]
        fetched_objects.append(key)
        return httpx.Response(200, content=object_bytes[key])

    provider = AnalysisPlatformProvider(
        "https://analysis.test/api/", "private-platform-key", 1024 * 1024
    )
    provider._client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(response))
    service.platform = provider
    service.ingestion.platform = provider
    # Provider configuration is an application concern; no client-supplied URL is accepted.
    object.__setattr__(service.settings, "analysis_platform_url", "https://analysis.test/api/")
    created = client.post(
        "/api/v1/data-bundles",
        json={
            "project_id": owner,
            "name": "Study",
            "source_kind": "analysis_platform",
            "source_id": "study-1",
        },
    )
    assert created.status_code == 201, created.text
    dataset_id = created.json()["dataset_id"]
    client.post(f"/api/v1/data-bundles/{dataset_id}/finalize", params={"project_id": owner})
    imported = wait_dataset(client, owner, dataset_id)
    assert imported["state"] == "ready", imported
    assert imported["description"] == "Authoritative platform description."
    assert imported["interpretation_status"] == "source_provided"
    assert imported["relationships"][0]["validation"] == "declared"
    assert fetched_objects == []
    for item in imported["objects"]:
        inspected = client.get(
            f"/api/v1/objects/{item['object_id']}",
            params={"project_id": owner, "revision_id": imported["revision_id"], "profile": True},
        )
        assert inspected.status_code == 200, inspected.text
        if item["name"] == "observations":
            assert inspected.json()["columns"][1]["unit"] == "mg"
            assert inspected.json()["columns"][1]["numeric"]["mean"] == 4
    assert fetched_objects == ["observations", "samples"]
    serialized = json.dumps(imported)
    assert (
        "private-platform-key" not in serialized
        and "content_path" not in serialized
        and "storage_path" not in serialized
    )
    duplicate = client.post(
        "/api/v1/data-bundles",
        json={
            "project_id": owner,
            "name": "Study",
            "source_kind": "analysis_platform",
            "source_id": "study-1",
        },
    ).json()
    assert duplicate["dataset_id"] == dataset_id
    current_revision[0] = "v2"
    client.post(f"/api/v1/data-bundles/{dataset_id}/refresh", params={"project_id": owner})
    refreshed = wait_dataset(client, owner, dataset_id)
    assert refreshed["revision_id"] != imported["revision_id"]
    assert refreshed["objects"][0]["object_id"] == imported["objects"][0]["object_id"]
    previous = client.get(
        f"/api/v1/data-bundles/{dataset_id}",
        params={"project_id": owner, "revision_id": imported["revision_id"]},
    ).json()
    assert previous["source_revision"] == "v1"
    run = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Compare the imported study"},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset_id]},
            "research_plan": research_plan(imported["objects"]),
        },
    )
    assert run.status_code == 202, run.text
    assert wait_run(client, run.json())["status"] == "completed"


def test_invalid_joins_fail_before_saving_a_result(data_client):
    client = data_client
    owner = project(client)
    dataset = upload_collection(client, owner)
    plan = research_plan(dataset["objects"], render=False)
    plan["relationships"][0]["right_key"] = "missing_key"
    response = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Compare group means"},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
            "research_plan": plan,
        },
    )
    assert response.status_code == 202, response.text
    completed = wait_run(client, response.json())
    assert completed["status"] == "failed"
    assert client.get(f"/api/v1/projects/{owner}/analysis-results").json()["total"] == 0


def test_render_failure_preserves_valid_analysis_outputs(data_client):
    client = data_client
    owner = project(client)
    dataset = upload_collection(client, owner)
    plan = research_plan(dataset["objects"])
    plan["render_code"] = 'stop("Rendering test failure")'
    response = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Compare group means"},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
            "research_plan": plan,
        },
    )
    completed = wait_run(client, response.json())
    assert completed["status"] == "failed"
    assert len(completed["analysis_results"]) == 1
    assert client.get(f"/api/v1/projects/{owner}/analysis-results").json()["total"] == 1


def test_selected_data_scope_cannot_be_bypassed_by_result_reuse(data_client):
    client = data_client
    owner = project(client)
    first = upload_collection(client, owner)
    second = upload_collection(client, owner)
    run = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Analyze first dataset"},
            "data_scope": {"mode": "selected", "bundle_ids": [first["dataset_id"]]},
            "research_plan": research_plan(first["objects"], render=False),
        },
    )
    result = wait_run(client, run.json())["analysis_results"][0]
    invalid = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Use second dataset"},
            "data_scope": {"mode": "selected", "bundle_ids": [second["dataset_id"]]},
            "research_plan": {
                "title": "Other figure",
                "figure_size": {"width": 6.5, "height": 4.5},
                "description": "Reuse outside selection",
                "reuse_result_id": result["result_id"],
                "render_code": "plot(results$comparison$value)",
            },
        },
    )
    assert invalid.status_code == 422, invalid.text
    other_project = project(client)
    assert (
        client.get(
            f"/api/v1/analysis-results/{result['result_id']}", params={"project_id": other_project}
        ).status_code
        == 404
    )


def test_cancellation_stops_research_without_publishing_partial_results(data_client):
    client = data_client
    owner = project(client)
    dataset = upload_collection(client, owner)
    plan = research_plan(dataset["objects"], render=False)
    plan["analysis_code"] = "Sys.sleep(20); " + plan["analysis_code"]
    accepted = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Long analysis"},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
            "research_plan": plan,
        },
    ).json()
    time.sleep(0.1)
    cancelled = client.post(accepted["links"]["cancel"])
    assert cancelled.status_code == 200
    assert wait_run(client, accepted)["status"] == "cancelled"
    assert client.get(f"/api/v1/projects/{owner}/analysis-results").json()["total"] == 0


def test_bad_interpretation_does_not_hide_parsed_objects(data_client):
    class BadInterpretation(ProfileOnlyAgent):
        async def interpret(self, context):
            return DatasetInterpretation.model_validate(
                {
                    "description": "Unsupported inference",
                    "relationships": [
                        {
                            "relationship_id": "bad",
                            "left_object_id": "invented",
                            "right_object_id": "missing",
                        }
                    ],
                }
            )

    data_client.app.state.dataset_service.ingestion.agent = BadInterpretation()
    dataset = upload_collection(data_client, project(data_client))
    assert dataset["state"] == "ready"
    assert all(item["readiness"] == "ready" for item in dataset["objects"])
    assert dataset["interpretation_status"] == "unavailable"
    assert dataset["relationships"] == []


def test_metadata_corrections_change_revision_without_changing_values(data_client):
    client = data_client
    owner = project(client)
    dataset = upload_collection(client, owner)
    original_object = dataset["objects"][0]
    response = client.patch(
        f"/api/v1/data-bundles/{dataset['dataset_id']}",
        json={
            "project_id": owner,
            "base_revision_id": dataset["revision_id"],
            "objects": [
                {
                    "object_id": original_object["object_id"],
                    "observation_unit": "sample",
                    "columns": [
                        {"name": "value", "unit": "mg", "description": "Measured concentration"}
                    ],
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    changed = response.json()
    assert changed["revision_id"] != dataset["revision_id"]
    assert changed["objects"][0]["content_hash"] == original_object["content_hash"]
    assert changed["objects"][0]["columns"][1]["unit"] == "mg"
    previous = client.get(
        f"/api/v1/objects/{original_object['object_id']}",
        params={"project_id": owner, "revision_id": dataset["revision_id"]},
    ).json()
    assert previous["columns"][1]["unit"] is None


def test_r_collection_exposes_related_matrix_and_annotation_objects(data_client, tmp_path):
    client = data_client
    owner = project(client)
    worker = client.app.state.dataset_service.worker
    output = asyncio.run(
        worker.execute(
            {
                "mode": "analyze",
                "params": {},
                "random_seed": 1,
                "output_names": ["bundle"],
                "code": (
                    'list(bundle=list(counts=matrix(c(1,3,5,7),nrow=2,dimnames=list(c("feature1","feature2"),c("s1","s2"))),'
                    ' samples=data.frame(sample_id=c("s1","s2"),group=c("A","B"))))'
                ),
            },
            {},
        )
    )
    raw = (output.directory / "output-1.rds").read_bytes()
    created = client.post(
        "/api/v1/data-bundles", json={"project_id": owner, "name": "Matrix study"}
    ).json()
    dataset_id = created["dataset_id"]
    client.post(
        f"/api/v1/data-bundles/{dataset_id}/files",
        params={"project_id": owner, "name": "study.rds"},
        content=raw,
    )
    client.post(f"/api/v1/data-bundles/{dataset_id}/finalize", params={"project_id": owner})
    dataset = wait_dataset(client, owner, dataset_id)
    objects = {item["name"]: item for item in dataset["objects"]}
    assert set(objects) == {"counts", "samples"}, dataset
    assert objects["counts"]["kind"] == "matrix"
    assert objects["counts"]["dimensions"] == [2, 2]
    assert "s1" not in json.dumps(objects["counts"])
    plan = {
        "title": "Matrix means",
        "description": "Average value per sample.",
        "inputs": [
            {
                "alias": key,
                "reference": {"object_id": item["object_id"], "revision_id": item["revision_id"]},
            }
            for key, item in objects.items()
        ],
        "relationships": [
            {
                "relationship_id": "annotations",
                "left_object_id": objects["counts"]["object_id"],
                "right_object_id": objects["samples"]["object_id"],
                "kind": "annotates",
                "left_axis": "columns",
                "right_key": "sample_id",
                "cardinality": "one_to_one",
            }
        ],
        "analysis_code": (
            "list(summary=data.frame(sample=colnames(inputs$counts),mean=colMeans(inputs$counts)))"
        ),
        "outputs": [
            {"key": "summary", "name": "Sample means", "description": "Mean value across features."}
        ],
    }
    response = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Calculate sample means"},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset_id]},
            "research_plan": plan,
        },
    )
    assert response.status_code == 202, response.text
    assert wait_run(client, response.json())["status"] == "completed"


def test_fitted_models_are_reusable_typed_result_objects(data_client):
    client = data_client
    owner = project(client)
    dataset = upload_collection(client, owner)
    plan = research_plan(dataset["objects"], render=False)
    plan["analysis_code"] = (
        "joined <- merge(inputs$observations, inputs$samples, "
        'by="sample_id"); list(fit=lm(value ~ group, joined))'
    )
    plan["outputs"] = [
        {
            "key": "fit",
            "name": "Treatment model",
            "description": "Linear model of value by treatment group.",
        }
    ]
    created = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Fit a treatment model"},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
            "research_plan": plan,
        },
    )
    assert created.status_code == 202, created.text
    snapshot = wait_run(client, created.json())
    assert snapshot["status"] == "completed", snapshot
    result = snapshot["analysis_results"][0]
    assert result["objects"][0]["kind"] == "model"
    assert result["objects"][0]["extensions"]["r_class"] == ["lm"]
    assert any(item["role"] == "model" for item in result["artifacts"])


def test_saved_input_changes_are_detected_without_substituting_current_data(data_client):
    from vis_platform_backend.contracts.datasets import ObjectReference
    from vis_platform_backend.data.errors import DataError

    owner = project(data_client)
    dataset = upload_collection(data_client, owner)
    item = dataset["objects"][0]
    service = data_client.app.state.dataset_service
    reference = ObjectReference(object_id=item["object_id"], revision_id=item["revision_id"])
    _, path, _ = service.resolve(owner, reference)
    path.write_text("sample_id,value\ns1,999\n")
    with pytest.raises(DataError, match="changed"):
        service.resolve(owner, reference)


def test_scalar_statistics_are_visible_without_opening_an_artifact(data_client):
    client = data_client
    owner = project(client)
    dataset = upload_collection(client, owner)
    plan = research_plan(dataset["objects"], render=False)
    plan["analysis_code"] = "list(mean=mean(inputs$observations$value))"
    plan["outputs"] = [
        {"key": "mean", "name": "Mean value", "description": "Mean across the four observations."}
    ]
    created = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Calculate the mean"},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
            "research_plan": plan,
        },
    )
    completed = wait_run(client, created.json())
    assert completed["status"] == "completed", completed
    assert completed["analysis_results"][0]["objects"][0]["kind"] == "scalar"
    assert completed["analysis_results"][0]["objects"][0]["scalar"] == 4


def test_agent_data_queries_read_the_registry_before_a_figure_exists(data_client):
    from vis_platform_backend.agents.intent import IntentAgentExecution
    from vis_platform_backend.contracts.intent import IntentDecision

    class QueryAgent:
        async def analyze(self, input):
            assert input.workspace_context["get_current_data"]["datasets"]
            return IntentAgentExecution(
                decision=IntentDecision.model_validate(
                    {
                        "kind": "data_query",
                        "subtype": "inspect",
                        "normalized_request": input.text,
                        "confidence": 1,
                        "next_action": "call_data_tools",
                        "user_reply": "Inspect the available data.",
                        "decision_summary": "Read registered objects and measured profiles.",
                    }
                ),
                turns=(),
            )

    owner = project(data_client)
    dataset = upload_collection(data_client, owner)
    data_client.app.state.assistant_turn_service._intent_agent = QueryAgent()
    response = data_client.post(
        "/api/v1/assistant-turns",
        json={
            "project_id": owner,
            "request": {"text": "What data do I have?"},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "message"
    assert response.json()["message"] == "There are 1 datasets in this scope."
    assert data_client.get(f"/api/v1/projects/{owner}/analysis-results").json()["total"] == 0


def test_data_planner_questions_resume_into_the_same_real_request(data_client):
    from vis_platform_backend.agents.intent import IntentAgentExecution
    from vis_platform_backend.contracts.intent import IntentDecision

    class PlotAgent:
        async def analyze(self, input):
            return IntentAgentExecution(
                decision=IntentDecision.model_validate(
                    {
                        "kind": "plot_create",
                        "subtype": "comparison",
                        "normalized_request": input.text,
                        "confidence": 1,
                        "next_action": "build_context",
                        "plot": {"goal": input.text},
                        "decision_summary": "Plan against the selected dataset.",
                    }
                ),
                turns=(),
            )

    class QuestioningDataAgent(ProfileOnlyAgent):
        async def plan(self, context):
            if context["previous_answers"]:
                return await super().plan(context)
            return ResearchDecision.model_validate(
                {
                    "action": "ask_user",
                    "summary": "Choose the comparison scope.",
                    "questions": [
                        {
                            "question_id": "groups",
                            "header": "Comparison",
                            "prompt": "Which groups should be compared?",
                            "reason": "This fixes the analysis scope.",
                            "selection": "single",
                            "choices": [
                                {
                                    "choice_id": "all",
                                    "label": "All groups",
                                    "description": "Include all available groups.",
                                },
                                {
                                    "choice_id": "first",
                                    "label": "First group",
                                    "description": "Inspect the first group only.",
                                },
                            ],
                        }
                    ],
                }
            )

    owner = project(data_client)
    dataset = upload_collection(data_client, owner)
    service = data_client.app.state.assistant_turn_service
    service._intent_agent = PlotAgent()
    service._data_agent = QuestioningDataAgent()
    response = data_client.post(
        "/api/v1/assistant-turns",
        json={
            "project_id": owner,
            "request": {"text": "Compare treatment means"},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
        },
    )
    assert response.status_code == 200, response.text
    waiting = response.json()
    assert waiting["outcome"] == "question"
    resumed = data_client.post(
        f"/api/v1/assistant-turns/{waiting['turn_id']}/answer",
        json={
            "project_id": owner,
            "interaction_id": waiting["question"]["interaction_id"],
            "answers": [{"question_id": "groups", "choice_ids": ["all"]}],
        },
    )
    assert resumed.status_code == 202, resumed.text
    accepted = resumed.json()
    for _ in range(100):
        state = data_client.get(accepted["links"]["status"]).json()
        if state["status"] == "completed":
            break
        time.sleep(0.025)
    assert state["status"] == "completed", state
    result = wait_run(data_client, state["response"]["plot_run"])
    assert result["status"] == "completed", result
    assert result["result"]["execution_mode"] == "r"
