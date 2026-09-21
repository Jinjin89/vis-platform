import json
import time

import pytest
from fastapi.testclient import TestClient

from vis_platform_backend.agents.intent import IntentAgentExecution, IntentAgentInput
from vis_platform_backend.app import create_app
from vis_platform_backend.config import Settings
from vis_platform_backend.contracts.intent import (
    IntentAction,
    IntentDecision,
    IntentKind,
    RefinementChange,
    RefinementIntent,
)


class RefinementIntentAgent:
    async def analyze(self, input: IntentAgentInput) -> IntentAgentExecution:
        return IntentAgentExecution(
            decision=IntentDecision(
                kind=IntentKind.PLOT_REFINE,
                subtype="visual_refinement",
                normalized_request=input.text,
                confidence=0.99,
                next_action=IntentAction.REFINE_CONTEXT,
                refinement=RefinementIntent(
                    changes=[
                        RefinementChange(
                            target="labels",
                            value="larger",
                            change_class="visual",
                        )
                    ]
                ),
                decision_summary="The request changes an existing plot.",
            ),
            turns=(),
        )


class HallucinatingIntentAgent:
    def __init__(self, kind: IntentKind, next_action: IntentAction) -> None:
        self._kind = kind
        self._next_action = next_action

    async def analyze(self, input: IntentAgentInput) -> IntentAgentExecution:
        return IntentAgentExecution(
            decision=IntentDecision(
                kind=self._kind,
                subtype="injected_test_route",
                normalized_request=input.text,
                confidence=0.99,
                next_action=self._next_action,
                decision_summary="The injected agent selected a non-plot route.",
                user_reply=(
                    "The feature is available in the data panel on the left. "
                    "Open Show controls to use it."
                ),
            ),
            turns=(),
        )


def create_project(client: TestClient) -> str:
    response = client.post(
        "/api/v1/projects",
        json={"name": "Intent test"},
    )
    assert response.status_code == 201
    return response.json()["project_id"]


def submit_turn(client: TestClient, project_id: str, text: str) -> dict:
    response = client.post(
        "/api/v1/assistant-turns",
        json={
            "project_id": project_id,
            "request": {"text": text},
            "data_scope": {"mode": "auto"},
        },
    )
    assert response.status_code == 200
    return response.json()


def wait_for_run(client: TestClient, status_path: str) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        snapshot = client.get(status_path).json()
        if snapshot["status"] == "completed":
            return snapshot
        time.sleep(0.01)
    raise AssertionError("Plot run did not complete")


def test_greeting_returns_message_without_creating_plot(
    agent_client: TestClient,
) -> None:
    project_id = create_project(agent_client)

    turn = submit_turn(agent_client, project_id, "how are you?")

    assert turn["outcome"] == "message"
    assert turn["intent"]["kind"] == "social"
    assert turn["plot_run"] is None
    assert turn["message"]
    persisted = agent_client.app.state.repository.get_assistant_turn(turn["turn_id"])
    assert persisted["run_id"] is None


def test_abuse_without_plot_request_does_not_create_plot(
    agent_client: TestClient,
) -> None:
    project_id = create_project(agent_client)

    turn = submit_turn(agent_client, project_id, "you fucker")

    assert turn["outcome"] == "message"
    assert turn["intent"]["kind"] == "social"
    assert turn["plot_run"] is None


def test_concrete_plot_request_routes_to_plot_run(agent_client: TestClient) -> None:
    project_id = create_project(agent_client)

    turn = submit_turn(
        agent_client,
        project_id,
        "Use demonstration data to make a violin plot of expression by treatment",
    )

    assert turn["outcome"] == "plot_run"
    assert turn["intent"]["kind"] == "plot_create"
    assert turn["plot_run"]["run_id"].startswith("run_")
    wait_for_run(agent_client, turn["plot_run"]["links"]["status"])
    trace = agent_client.get(
        turn["links"]["trace"],
        headers={"X-Developer-Trace-Token": "test-trace-token"},
    ).json()
    r_entry = next(entry for entry in trace["entries"] if entry["kind"] == "r_execution")
    assert r_entry["status"] == "blocked"
    assert r_entry["output"]["demo_only"] is True


def test_data_question_does_not_render_plot(agent_client: TestClient) -> None:
    project_id = create_project(agent_client)

    turn = submit_turn(agent_client, project_id, "What datasets do I have?")

    assert turn["outcome"] == "message"
    assert turn["intent"]["kind"] == "data_query"
    assert turn["plot_run"] is None


@pytest.mark.parametrize(
    ("kind", "next_action", "text", "expected_capability", "expected_message"),
    [
        (
            IntentKind.WORKSPACE_ACTION,
            IntentAction.EXECUTE_WORKSPACE_ACTION,
            "Undo my last change",
            "workspace_actions",
            "Chat-based workspace actions are not connected",
        ),
        (
            IntentKind.PLOT_QUERY,
            IntentAction.READ_PLOT_CONTEXT,
            "What does the current plot show?",
            "plot_inspection",
            "There is no active figure to inspect",
        ),
    ],
)
def test_unavailable_tool_actions_are_blocked(
    tmp_path,
    kind: IntentKind,
    next_action: IntentAction,
    text: str,
    expected_capability: str,
    expected_message: str,
) -> None:
    settings = Settings(
        database_path=tmp_path / f"{kind.value}-capability.sqlite3",
        artifact_root=tmp_path / f"{kind.value}-capability-artifacts",
        fake_step_delay_seconds=0.001,
        developer_trace_enabled=True,
        developer_trace_token="test-trace-token",
    )
    intent_agent = HallucinatingIntentAgent(kind, next_action)

    with TestClient(create_app(settings, intent_agent=intent_agent)) as test_client:
        project_id = create_project(test_client)
        turn = submit_turn(test_client, project_id, text)
        persisted = test_client.app.state.repository.get_assistant_turn(turn["turn_id"])
        trace = test_client.get(
            turn["links"]["trace"],
            headers={"X-Developer-Trace-Token": "test-trace-token"},
        ).json()

    assert expected_message in turn["message"]
    assert "available in the data panel on the left" not in turn["message"]
    assert turn["intent"]["user_reply"] == turn["message"]
    assert persisted["message"] == turn["message"]
    assert persisted["intent"]["user_reply"] == turn["message"]
    routing = next(entry for entry in trace["entries"] if entry["kind"] == "routing")
    assert routing["name"] == "readiness_blocked"
    assert routing["status"] == "blocked"
    assert routing["output"]["route"] == "reply"
    assert routing["output"]["requested_route"] == next_action.value
    assert turn["intent"]["next_action"] == "reply"


def test_trace_requires_token_and_redacts_secrets(
    agent_client: TestClient,
) -> None:
    project_id = create_project(agent_client)
    turn = submit_turn(agent_client, project_id, "how are you?")

    denied = agent_client.get(turn["links"]["trace"])
    assert denied.status_code == 403

    response = agent_client.get(
        turn["links"]["trace"],
        headers={"X-Developer-Trace-Token": "test-trace-token"},
    )

    assert response.status_code == 200
    trace = response.json()
    serialized = json.dumps(trace)
    assert [entry["sequence"] for entry in trace["entries"]] == list(
        range(1, len(trace["entries"]) + 1)
    )
    assert "test-secret" not in serialized
    assert "private test reasoning" not in serialized
    assert trace["reasoning_content_exposed"] is False
    llm_entry = next(entry for entry in trace["entries"] if entry["kind"] == "llm_turn")
    assert llm_entry["input"]["authorization"] == "[redacted]"
    assert llm_entry["output"]["reasoning_content"] == "[redacted]"


def test_unconfigured_deepseek_returns_stable_error(client: TestClient) -> None:
    project_id = create_project(client)
    response = client.post(
        "/api/v1/assistant-turns",
        json={
            "project_id": project_id,
            "request": {"text": "Make a boxplot"},
            "data_scope": {"mode": "auto"},
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLM_NOT_CONFIGURED"
    assert response.json()["error"]["details"]["turn_id"].startswith("turn_")


def test_refinement_without_active_plot_returns_conflict(tmp_path) -> None:
    settings = Settings(
        database_path=tmp_path / "refinement-test.sqlite3",
        artifact_root=tmp_path / "refinement-artifacts",
        fake_step_delay_seconds=0.001,
    )
    with TestClient(create_app(settings, intent_agent=RefinementIntentAgent())) as client:
        project_id = create_project(client)
        response = client.post(
            "/api/v1/assistant-turns",
            json={
                "project_id": project_id,
                "request": {"text": "Make the labels larger"},
                "data_scope": {"mode": "auto"},
            },
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ACTIVE_PLOT_REQUIRED"
