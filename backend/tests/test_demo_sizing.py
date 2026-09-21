import json
from copy import deepcopy
from xml.etree import ElementTree as ET

import httpx
import pytest
from test_parameters import create, history, update, wait

from vis_platform_backend.agents.figure_size import LlmFigureSizeAgent
from vis_platform_backend.agents.structured import StructuredAgentError
from vis_platform_backend.config import LlmSettings
from vis_platform_backend.contracts.figures import FigureSize


class RecordingSizeAgent:
    def __init__(self, *sizes):
        self.sizes = sizes
        self.contexts = []

    async def recommend(self, context):
        self.contexts.append(context)
        return self.sizes[len(self.contexts) - 1]


def assert_size(client, snapshot, width, height):
    result = snapshot["result"]
    assert result["figure_size"] == {"width": width, "height": height, "unit": "in"}
    controls = {item["id"]: item["value"] for item in result["controls"]}
    assert controls["figure_width"] == width
    assert controls["figure_height"] == height
    image = ET.fromstring(client.get(result["preview"]["href"]).content)
    assert image.get("width") == f"{width:g}in"
    assert image.get("height") == f"{height:g}in"


def test_new_demos_use_the_recommendation_and_edits_and_history_reuse_it(client):
    agent = RecordingSizeAgent(
        FigureSize(width=7.25, height=4.5), FigureSize(width=11, height=6.25)
    )
    client.app.state.coordinator._figure_size_agent = agent
    first = create(client, "Make a compact violin plot using demo data")
    second = create(client, "Make a wide scatter relationship using demo data")
    assert_size(client, first, 7.25, 4.5)
    assert_size(client, second, 11, 6.25)
    assert agent.contexts[0]["figure"]["kind"] != agent.contexts[1]["figure"]["kind"]
    assert "compact" in agent.contexts[0]["user_request"]
    changed = wait(client, update(client, first, {"figure_width": 12.75, "label_size": 13}).json())
    assert_size(client, changed, 12.75, 4.5)
    restored = client.post(
        f"/api/v1/plots/{first['result']['plot_id']}/restore",
        json={
            "project_id": first["project_id"],
            "source_version_id": first["result"]["version_id"],
        },
    )
    assert_size(client, wait(client, restored.json()), 7.25, 4.5)
    assert len(agent.contexts) == 2
    assert (
        history(client, first)["versions"][-1]["result"]["figure_size"]
        == first["result"]["figure_size"]
    )


def test_failed_recommendation_cannot_fall_back_to_the_old_demo_size(client):
    first = create(client)

    class FailingSizeAgent:
        async def recommend(self, context):
            raise StructuredAgentError("Size recommendation is unavailable.")

    client.app.state.coordinator._figure_size_agent = FailingSizeAgent()
    response = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": first["project_id"],
            "request": {"text": "Create another violin plot"},
            "data_scope": {"mode": "demo"},
        },
    )
    assert response.status_code == 202
    failed = wait(client, response.json(), expected="failed")
    assert failed["result"] is None
    assert "Size recommendation is unavailable" in failed["failure"]["message"]
    assert history(client, first)["current_version_id"] == first["result"]["version_id"]
    # Existing figures remain editable without another recommendation.
    changed = wait(client, update(client, first, {"label_size": 12}).json())
    assert_size(client, changed, 8, 5.5)


def test_legacy_specs_keep_recorded_dimensions_without_a_new_recommendation(client):
    first = create(client)
    repository = client.app.state.repository
    interaction = deepcopy(repository.get_run(first["run_id"])["interaction"])
    interaction["render_spec"].pop("figure_size")
    repository.update_interaction(first["run_id"], interaction)
    agent = RecordingSizeAgent()
    client.app.state.coordinator._figure_size_agent = agent
    changed = wait(client, update(client, first, {"label_size": 13}).json())
    assert_size(client, changed, 8, 5.5)
    assert agent.contexts == []


@pytest.mark.asyncio
async def test_size_model_receives_the_request_and_repairs_incomplete_dimensions(monkeypatch):
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        dimensions = {"width": 12.25} if len(calls) == 1 else {"width": 12.25, "height": 4.75}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(dimensions)},
                    }
                ]
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(respond),
            **kwargs,
        ),
    )
    size = await LlmFigureSizeAgent(LlmSettings(api_key="test")).recommend(
        {
            "user_request": "Use 12.25 inches wide and 4.75 inches high",
            "figure": {"kind": "distribution", "title": "Treatment comparison"},
        }
    )
    assert size == FigureSize(width=12.25, height=4.75)
    assert len(calls) == 2
    supplied = json.loads(calls[0]["messages"][1]["content"])
    assert "12.25 inches" in supplied["context"]["user_request"]
    assert set(supplied["response_schema"]["required"]) == {"width", "height"}
    assert "height" in calls[1]["messages"][-1]["content"]


def test_size_recommendation_uses_original_user_constraints_after_intent_routing(client):
    from vis_platform_backend.agents.intent import IntentAgentExecution
    from vis_platform_backend.contracts.intent import IntentDecision

    class DemoIntentAgent:
        async def analyze(self, input):
            return IntentAgentExecution(
                decision=IntentDecision.model_validate(
                    {
                        "kind": "plot_create",
                        "subtype": "distribution",
                        "normalized_request": "Create a demonstration violin plot",
                        "confidence": 1,
                        "next_action": "build_context",
                        "mode_requests": {"data": "demo"},
                        "plot": {"goal": "Compare expression distributions"},
                        "decision_summary": "Render the requested demonstration.",
                    }
                ),
                turns=(),
            )

    agent = RecordingSizeAgent(FigureSize(width=12.25, height=4.75))
    client.app.state.coordinator._figure_size_agent = agent
    client.app.state.assistant_turn_service._intent_agent = DemoIntentAgent()
    owner = client.post("/api/v1/projects", json={"name": "Size constraints"}).json()["project_id"]
    original = "Use demo data for a violin plot, 12.25 inches wide and 4.75 inches high."
    response = client.post(
        "/api/v1/assistant-turns",
        json={
            "project_id": owner,
            "request": {"text": original},
            "data_scope": {"mode": "auto"},
        },
    )
    assert response.status_code == 200, response.text
    assert_size(client, wait(client, response.json()["plot_run"]), 12.25, 4.75)
    assert agent.contexts[0]["user_request"] == original
    assert agent.contexts[0]["request"] != original


def test_cancellation_during_recommendation_does_not_save_a_figure(client):
    import asyncio
    import threading

    entered = threading.Event()

    class SlowSizeAgent:
        async def recommend(self, context):
            entered.set()
            await asyncio.sleep(30)
            return FigureSize(width=8, height=5)

    client.app.state.coordinator._figure_size_agent = SlowSizeAgent()
    owner = client.post("/api/v1/projects", json={"name": "Cancelled sizing"}).json()["project_id"]
    accepted = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Create a violin plot"},
            "data_scope": {"mode": "demo"},
        },
    ).json()
    assert entered.wait(timeout=2)
    assert client.post(accepted["links"]["cancel"]).status_code == 200
    cancelled = client.get(accepted["links"]["status"]).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["result"] is None
