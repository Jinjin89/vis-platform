import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from test_datasets import data_client as data_client
from test_datasets import project, research_plan, upload_collection, wait_run

from vis_platform_backend.agents.data_agent import LlmDataAgent
from vis_platform_backend.agents.intent import IntentAgentExecution
from vis_platform_backend.config import LlmSettings
from vis_platform_backend.contracts.figures import FigureSize
from vis_platform_backend.contracts.intent import IntentDecision
from vis_platform_backend.contracts.research import ResearchDecision, ResearchPlan
from vis_platform_backend.execution.runner import RExecutionError


def render_plan():
    return {
        "title": "Observation positions",
        "description": "The measured coordinates.",
        "reuse_result_id": "result_saved",
        "render_code": "plot(results$points$x, results$points$y, cex=params$point_size)",
        "controls": [
            {
                "type": "number",
                "id": "point_size",
                "label": "Point size",
                "value": 0.8,
                "minimum": 0.2,
                "maximum": 2,
                "step": 0.1,
            }
        ],
    }


@pytest.mark.parametrize("size", [None, {}, {"width": 7}, {"height": 5}])
def test_new_rendering_plans_cannot_silently_default_dimensions(size):
    with pytest.raises(ValueError):
        ResearchPlan.model_validate({**render_plan(), "figure_size": size})
    assert set(FigureSize.model_json_schema()["required"]) == {"width", "height"}


def test_analysis_only_plans_do_not_need_figure_configuration():
    plan = ResearchPlan.model_validate({**render_plan(), "render_code": None, "controls": []})
    assert plan.figure_size is None


@pytest.mark.asyncio
async def test_model_repairs_missing_size_and_preserves_chosen_parameter_defaults(monkeypatch):
    calls = []
    chosen_size = {"width": 7.25, "height": 4.75, "unit": "in"}

    def respond(request):
        calls.append(json.loads(request.content))
        plan = render_plan()
        if len(calls) > 1:
            plan["figure_size"] = chosen_size
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "action": "execute",
                                    "summary": "Plot the measured positions.",
                                    "plan": plan,
                                }
                            )
                        },
                    }
                ]
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    decision = await LlmDataAgent(LlmSettings(api_key="test")).plan(
        {"user_request": "Plot the measured positions.", "results": []}
    )
    assert len(calls) == 2
    assert "figure_size" in calls[1]["messages"][-1]["content"]
    assert decision.plan.figure_size.model_dump() == chosen_size
    assert decision.plan.controls[0].value == 0.8


def test_worker_refuses_to_render_without_explicit_geometry(data_client):
    worker = data_client.app.state.dataset_service.worker
    with pytest.raises(RExecutionError) as failure:
        asyncio.run(
            worker.execute(
                {
                    "mode": "render",
                    "params": {},
                    "random_seed": 1,
                    "code": "plot(1:3)",
                },
                {},
            )
        )
    assert "Figure dimensions must be provided" in failure.value.diagnostic


def test_new_requests_require_size_while_legacy_saved_versions_remain_editable(data_client):
    client = data_client
    owner = project(client)
    dataset = upload_collection(client, owner)
    plan = research_plan(dataset["objects"])
    plan.pop("figure_size")
    request = {
        "project_id": owner,
        "request": {"text": "Plot group means"},
        "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
        "research_plan": plan,
    }
    response = client.post("/api/v1/plot-runs", json=request)
    assert response.status_code == 422
    plan["figure_size"] = {"width": 9, "height": 6}
    accepted = client.post("/api/v1/plot-runs", json=request).json()
    saved = wait_run(client, accepted)
    assert saved["status"] == "completed", saved
    repository = client.app.state.repository
    interaction = deepcopy(repository.get_run(accepted["run_id"])["interaction"])
    # Simulate an r-v1 spec saved before output dimensions were recorded.
    spec = interaction["render_spec"]
    spec.pop("figure_size")
    spec["plan"].pop("figure_size")
    repository.update_interaction(accepted["run_id"], interaction)
    result = saved["result"]
    response = client.post(
        f"/api/v1/plots/{result['plot_id']}/parameters",
        json={
            "project_id": owner,
            "base_version_id": result["version_id"],
            "changes": {"title": "Updated comparison"},
        },
    )
    assert response.status_code == 202, response.text
    changed = wait_run(client, response.json())
    assert changed["status"] == "completed", changed
    assert changed["result"]["figure_size"] == {"width": 9, "height": 6, "unit": "in"}
    assert (
        changed["result"]["analysis_results"][0]["result_id"]
        == result["analysis_results"][0]["result_id"]
    )


def test_data_planner_receives_original_request_and_current_presentation(data_client):
    class PlotAgent:
        async def analyze(self, input):
            return IntentAgentExecution(
                decision=IntentDecision.model_validate(
                    {
                        "kind": "plot_create",
                        "subtype": "comparison",
                        "normalized_request": "Compare treatment means",
                        "confidence": 1,
                        "next_action": "build_context",
                        "plot": {"goal": "Compare treatment means"},
                        "decision_summary": "Plan the requested comparison.",
                    }
                ),
                turns=(),
            )

    class RecordingPlanner:
        contexts = []

        async def plan(self, context):
            self.contexts.append(context)
            plan = research_plan(context["objects"])
            plan["figure_size"] = {"width": 11.25, "height": 4.25}
            return ResearchDecision.model_validate(
                {
                    "action": "execute",
                    "summary": "Render the requested layout.",
                    "plan": plan,
                }
            )

    client = data_client
    owner = project(client)
    dataset = upload_collection(client, owner)
    accepted = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Compare treatment means"},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
            "research_plan": research_plan(dataset["objects"]),
        },
    ).json()
    result = wait_run(client, accepted)["result"]
    service = client.app.state.assistant_turn_service
    service._intent_agent = PlotAgent()
    planner = RecordingPlanner()
    service._data_agent = planner
    original = "Create another comparison, 11.25 inches wide and 4.25 inches high."
    response = client.post(
        "/api/v1/assistant-turns",
        json={
            "project_id": owner,
            "base_version_id": result["version_id"],
            "request": {"text": original},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
        },
    )
    assert response.status_code == 200, response.text
    context = planner.contexts[0]
    assert context["user_request"] == original
    assert context["request"] != original
    assert context["active_figure"]["figure_size"] == result["figure_size"]
    assert list(context["active_figure"]["controls"]) == result["controls"]
    assert list(context["active_figure"]["control_groups"]) == result["control_groups"]
    rendered = wait_run(client, response.json()["plot_run"])
    assert rendered["status"] == "completed", rendered
    assert rendered["result"]["figure_size"] == {"width": 11.25, "height": 4.25, "unit": "in"}
