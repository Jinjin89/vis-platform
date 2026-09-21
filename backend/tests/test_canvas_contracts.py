from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_datasets import (
    RUNTIME,
    ProfileOnlyAgent,
    project,
    research_plan,
    upload_collection,
    wait_run,
)
from test_parameters import ParameterAgent, create, history, values, wait

from vis_platform_backend.app import create_app
from vis_platform_backend.config import Settings


def test_language_and_parameter_drafts_commit_one_child_and_preserve_parent(tmp_path):
    config = Settings(
        database_path=tmp_path / "test.sqlite",
        artifact_root=tmp_path / "artifacts",
        fake_step_delay_seconds=0.001,
    )
    agent = ParameterAgent()
    with TestClient(create_app(config, intent_agent=agent)) as client:
        base = create(client)
        original = client.get(base["result"]["preview"]["href"]).content
        payload = {
            "project_id": base["project_id"],
            "base_version_id": base["result"]["version_id"],
            "data_scope": {"mode": "auto"},
            "request": {"text": "Make labels larger"},
            "parameter_changes": {"label_size": 14, "palette": "plum"},
        }
        response = client.post(
            "/api/v1/assistant-turns", json=payload, headers={"Idempotency-Key": "draft-refinement"}
        )
        assert response.status_code == 200, response.text
        completed = wait(client, response.json()["plot_run"])
        assert values(completed)["label_size"] == 14
        assert values(completed)["palette"] == "plum"
        assert agent.input.workspace_context["parameter_drafts"] == payload["parameter_changes"]
        assert values(base)["label_size"] == 11
        assert client.get(base["result"]["preview"]["href"]).content == original
        versions = history(client, base)["versions"]
        assert len(versions) == 2
        assert versions[0]["parent_version_id"] == base["result"]["version_id"]
        repeated = client.post(
            "/api/v1/assistant-turns", json=payload, headers={"Idempotency-Key": "draft-refinement"}
        )
        assert repeated.json()["plot_run"]["run_id"] == completed["run_id"]


@pytest.mark.parametrize("changes", [{"label_size": 900}, {"unknown": 1}, {"label_size": True}])
def test_invalid_drafts_are_rejected_before_planning(tmp_path, changes):
    agent = ParameterAgent()
    config = Settings(
        database_path=tmp_path / "test.sqlite",
        artifact_root=tmp_path / "artifacts",
        fake_step_delay_seconds=0.001,
    )
    with TestClient(create_app(config, intent_agent=agent)) as client:
        base = create(client)
        response = client.post(
            "/api/v1/assistant-turns",
            json={
                "project_id": base["project_id"],
                "base_version_id": base["result"]["version_id"],
                "data_scope": {"mode": "auto"},
                "request": {"text": "Make labels larger"},
                "parameter_changes": changes,
            },
        )
        assert response.status_code == 422, response.text
        assert agent.input is None
        assert len(history(client, base)["versions"]) == 1


def test_drafts_require_a_parent_version(client):
    response = client.post(
        "/api/v1/assistant-turns",
        json={
            "project_id": project(client),
            "data_scope": {"mode": "auto"},
            "request": {"text": "Make a plot"},
            "parameter_changes": {"title": "A title"},
        },
    )
    assert response.status_code == 422


def test_r_source_is_version_scoped_and_children_reuse_analysis(tmp_path):
    config = Settings(
        database_path=tmp_path / "source.sqlite",
        artifact_root=tmp_path / "artifacts",
        r_home=RUNTIME / "usr/lib/R",
        r_sandbox=RUNTIME / "vis-r-sandbox",
    )
    with TestClient(create_app(config, data_agent=ProfileOnlyAgent())) as client:
        owner = project(client)
        dataset = upload_collection(client, owner)
        accepted = client.post(
            "/api/v1/plot-runs",
            json={
                "project_id": owner,
                "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
                "request": {"text": "Compare treatments"},
                "research_plan": research_plan(dataset["objects"]),
            },
        )
        base = wait_run(client, accepted.json())
        assert base["status"] == "completed", base
        result = base["result"]
        path = (
            f"/api/v1/projects/{owner}/plots/{result['plot_id']}"
            f"/versions/{result['version_id']}/source"
        )
        source = client.get(path)
        assert source.status_code == 200, source.text
        saved = source.json()
        assert saved["render_code"] == research_plan(dataset["objects"])["render_code"]
        assert "plot_main <- function" in saved["code"]
        assert "grDevices::svg" in saved["code"]
        assert saved["parameters"]["color"] == "purple"
        assert "comparison" in saved["result_bindings"]
        assert saved["input_objects"] == result["input_objects"]
        assert "storage_path" not in source.text and str(tmp_path) not in source.text
        outsider = project(client)
        assert client.get(path.replace(owner, outsider)).status_code == 404
        assert client.get(path.replace(result["plot_id"], "missing")).status_code == 404
        child = client.post(
            f"/api/v1/plots/{result['plot_id']}/parameters",
            json={
                "project_id": owner,
                "base_version_id": result["version_id"],
                "changes": {"color": "steelblue"},
            },
        )
        completed = wait_run(client, child.json())
        assert completed["status"] == "completed", completed
        child_source = client.get(
            path.replace(result["version_id"], completed["result"]["version_id"])
        ).json()
        assert child_source["render_code"] == saved["render_code"]
        assert child_source["parameters"]["color"] == "steelblue"
        assert (
            completed["result"]["analysis_results"][0]["result_id"]
            == result["analysis_results"][0]["result_id"]
        )
        assert client.get(f"/api/v1/projects/{owner}/analysis-results").json()["total"] == 1
        assert client.get(path).json() == saved


def test_non_r_versions_explain_code_availability(client):
    base = create(client)
    result = base["result"]
    response = client.get(
        f"/api/v1/projects/{base['project_id']}/plots/{result['plot_id']}/versions/{result['version_id']}/source"
    )
    assert response.status_code == 200
    assert response.json()["code"] is None
    assert "without R code" in response.json()["message"]


class RegenerateIntentAgent(ParameterAgent):
    async def analyze(self, input):
        execution = await super().analyze(input)
        execution.decision.refinement.execution_strategy = "regenerate_render"
        execution.decision.refinement.changes[0].target = "color"
        execution.decision.refinement.changes[0].value = "steelblue"
        return execution


class RegenerateDataAgent(ProfileOnlyAgent):
    def __init__(self, *, omit_color=False):
        self.context = None
        self.omit_color = omit_color

    async def plan(self, context):
        from vis_platform_backend.contracts.research import ResearchDecision

        self.context = context
        figure = context["active_figure"]
        controls = [
            item
            for item in figure["controls"]
            if item["id"] not in {"figure_width", "figure_height"}
            and not (self.omit_color and item["id"] == "color")
        ]
        return ResearchDecision.model_validate(
            {
                "action": "execute",
                "summary": "Regenerate plotting code over saved analysis.",
                "plan": {
                    "title": "Refined treatment comparison",
                    "description": "Use saved measurements with a new rendering.",
                    "figure_size": figure["figure_size"],
                    "reuse_result_id": figure["results"][0]["result_id"],
                    "render_code": figure["render_code"],
                    "controls": controls,
                },
            }
        )


@pytest.mark.parametrize("omit_color", [False, True])
def test_regenerated_r_plan_applies_drafts_and_rejects_incompatible_controls(tmp_path, omit_color):
    data_agent = RegenerateDataAgent(omit_color=omit_color)
    config = Settings(
        database_path=tmp_path / "regenerate.sqlite",
        artifact_root=tmp_path / "artifacts",
        r_home=RUNTIME / "usr/lib/R",
        r_sandbox=RUNTIME / "vis-r-sandbox",
    )
    with TestClient(
        create_app(config, data_agent=data_agent, intent_agent=RegenerateIntentAgent())
    ) as client:
        owner = project(client)
        dataset = upload_collection(client, owner)
        accepted = client.post(
            "/api/v1/plot-runs",
            json={
                "project_id": owner,
                "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
                "request": {"text": "Compare treatments"},
                "research_plan": research_plan(dataset["objects"]),
            },
        )
        base = wait_run(client, accepted.json())
        assert base["status"] == "completed", base
        response = client.post(
            "/api/v1/assistant-turns",
            json={
                "project_id": owner,
                "base_version_id": base["result"]["version_id"],
                "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
                "request": {"text": "Regenerate the plotting code"},
                "parameter_changes": {"color": "steelblue", "figure_width": 8},
            },
        )
        assert response.status_code == 200, response.text
        turn = response.json()
        assert data_agent.context["parameter_drafts"] == {"color": "steelblue", "figure_width": 8}
        if omit_color:
            assert turn["outcome"] == "message"
            assert "Unknown plot parameter" in turn["message"]
            assert len(history(client, base)["versions"]) == 1
        else:
            child = wait_run(client, turn["plot_run"])
            assert child["status"] == "completed", child
            assert values(child)["color"] == "steelblue"
            assert child["result"]["figure_size"]["width"] == 8
            assert values(base)["color"] == "purple"
            assert len(history(client, base)["versions"]) == 2
            assert (
                child["result"]["analysis_results"][0]["result_id"]
                == base["result"]["analysis_results"][0]["result_id"]
            )
