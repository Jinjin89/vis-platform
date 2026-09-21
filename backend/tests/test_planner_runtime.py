from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vis_platform_backend.agents.intent import (
    IntentAgentError,
    IntentAgentExecution,
    IntentAgentInput,
    LlmTurnObservation,
)
from vis_platform_backend.app import create_app
from vis_platform_backend.config import LlmSettings, Settings
from vis_platform_backend.contracts.intent import IntentDecision


class QuestionAgent:
    def __init__(
        self, *, delay: float = 0.03, fail: bool = False, selection: str = "single"
    ) -> None:
        self.inputs: list[IntentAgentInput] = []
        self.delay = delay
        self.fail = fail
        self.selection = selection

    async def analyze(self, input: IntentAgentInput) -> IntentAgentExecution:
        import asyncio

        self.inputs.append(input)
        await asyncio.sleep(self.delay)
        if self.fail:
            raise IntentAgentError("Private internal failure", code="TEST_MODEL_FAILURE")
        if input.clarification_answers:
            answer = input.clarification_answers[-1]
            message = answer["free_text"] or ", ".join(answer["choices"])
            payload = {
                "kind": "social",
                "subtype": "answered",
                "normalized_request": input.text,
                "confidence": 1,
                "next_action": "reply",
                "decision_summary": "Continue using the recorded choice.",
                "user_reply": "Selected: " + message,
            }
        else:
            payload = {
                "kind": "unclear",
                "subtype": "choice",
                "normalized_request": input.text,
                "confidence": 1,
                "next_action": "ask_user",
                "decision_summary": "One unresolved user decision remains.",
                "user_reply": "Choose the focus for this figure.",
                "questions": [
                    {
                        "question_id": "focus",
                        "header": "Figure goal",
                        "prompt": "What should the figure emphasize?",
                        "reason": "Choose the information that matters to your comparison.",
                        "selection": self.selection,
                        "choices": [
                            {
                                "choice_id": "distribution",
                                "label": "Distribution",
                                "description": "Show the spread.",
                                "recommended": True,
                            },
                            {
                                "choice_id": "mean",
                                "label": "Group means",
                                "description": "Show average differences.",
                            },
                        ],
                    }
                ],
            }
        return IntentAgentExecution(
            decision=IntentDecision.model_validate(payload),
            turns=(
                LlmTurnObservation(
                    attempt=1,
                    duration_ms=20,
                    input={
                        "authorization": "test-private-key",
                        "messages": [{"content": "PRIVATE_SYSTEM_PROMPT"}],
                    },
                    output={
                        "reasoning_content": "PRIVATE_REASONING",
                        "content": json.dumps(payload),
                    },
                    error=None,
                ),
            ),
        )


def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "state.sqlite3",
        artifact_root=tmp_path / "artifacts",
        fake_step_delay_seconds=0.001,
        llm=LlmSettings(api_key="test-private-key"),
    )


def project(client: TestClient) -> str:
    return client.post("/api/v1/projects", json={"name": "Planner study"}).json()["project_id"]


def start(client: TestClient, project_id: str) -> dict:
    response = client.post(
        "/api/v1/assistant-turns",
        headers={"Prefer": "respond-async"},
        json={
            "project_id": project_id,
            "request": {"text": "Help me decide how to show the comparison"},
            "data_scope": {"mode": "auto"},
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def wait(client: TestClient, accepted: dict, expected: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.get(accepted["links"]["status"])
        assert response.status_code == 200
        snapshot = response.json()
        if snapshot["status"] == expected:
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"Planner did not reach {expected}: {snapshot}")


def answer_payload(project_id: str, snapshot: dict, **changes) -> dict:
    return {
        "project_id": project_id,
        "interaction_id": snapshot["question"]["interaction_id"],
        "answers": [{"question_id": "focus", "choice_ids": ["distribution"]}],
        **changes,
    }


def test_async_activity_is_real_and_available_without_a_developer_token(tmp_path: Path) -> None:
    agent = QuestionAgent(delay=0.2)
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        accepted = start(client, project(client))
        working = client.get(accepted["links"]["status"]).json()
        assert working["status"] == "running"
        assert any(
            entry["actor"] == "Intent planner" and entry["status"] == "running"
            for entry in working["activity"]
        )
        waiting = wait(client, accepted, "awaiting_input")
        assert {entry["tool_name"] for entry in waiting["activity"]} >= {
            "get_current_data",
            "get_current_results",
        }
        assert any(
            entry["actor"] == "Intent planner" and entry["status"] == "completed"
            for entry in waiting["activity"]
        )
        assert waiting["question"]["questions"][0]["choices"][0]["recommended"] is True
        encoded = json.dumps(waiting)
        assert "test-private-key" not in encoded
        assert "PRIVATE_REASONING" not in encoded
        assert "PRIVATE_SYSTEM_PROMPT" not in encoded
        assert "authorization" not in encoded
        assert client.get(accepted["links"]["trace"]).status_code == 404
        assert agent.inputs[0].workspace_context["get_current_data"]["discovery_available"] is True
        assert agent.inputs[0].workspace_context["get_current_results"]["figures"] == []


def test_answer_resumes_same_request_and_retries_do_not_run_the_model_twice(tmp_path: Path) -> None:
    agent = QuestionAgent(delay=0.08)
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        project_id = project(client)
        accepted = start(client, project_id)
        waiting = wait(client, accepted, "awaiting_input")
        payload = answer_payload(project_id, waiting)
        path = f"/api/v1/assistant-turns/{accepted['turn_id']}/answer"
        first = client.post(path, json=payload)
        repeated = client.post(path, json=payload)
        assert first.status_code == repeated.status_code == 202
        assert first.json()["turn_id"] == accepted["turn_id"]
        completed = wait(client, accepted, "completed")
        assert completed["response"]["message"] == "Selected: Distribution"
        assert len(agent.inputs) == 2
        assert agent.inputs[0].text == agent.inputs[1].text
        assert agent.inputs[1].clarification_answers == (
            {
                "question": "What should the figure emphasize?",
                "choices": ["Distribution"],
                "free_text": None,
            },
        )
        assert completed["question"] is None
        assert not any(entry["status"] in {"waiting", "running"} for entry in completed["activity"])
        payload["answers"][0]["choice_ids"] = ["mean"]
        assert client.post(path, json=payload).status_code == 409


@pytest.mark.parametrize(
    "answers",
    [
        [{"question_id": "focus", "choice_ids": []}],
        [{"question_id": "focus", "choice_ids": ["missing"]}],
        [{"question_id": "focus", "choice_ids": ["distribution", "mean"]}],
        [{"question_id": "missing", "choice_ids": ["distribution"]}],
        [
            {"question_id": "focus", "choice_ids": ["distribution"]},
            {"question_id": "focus", "choice_ids": ["mean"]},
        ],
    ],
)
def test_invalid_answers_preserve_the_pending_question(tmp_path: Path, answers: list) -> None:
    agent = QuestionAgent()
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        project_id = project(client)
        accepted = start(client, project_id)
        waiting = wait(client, accepted, "awaiting_input")
        response = client.post(
            f"/api/v1/assistant-turns/{accepted['turn_id']}/answer",
            json=answer_payload(project_id, waiting, answers=answers),
        )
        assert response.status_code == 422
        assert client.get(accepted["links"]["status"]).json()["question"] == waiting["question"]
        assert len(agent.inputs) == 1


@pytest.mark.parametrize(
    "selection,answer",
    [
        ("multiple", {"question_id": "focus", "choice_ids": ["distribution", "mean"]}),
        ("single", {"question_id": "focus", "free_text": "Show individual observations"}),
    ],
)
def test_multiple_choices_and_custom_answers_reach_the_planner(
    tmp_path: Path, selection: str, answer: dict
) -> None:
    agent = QuestionAgent(selection=selection)
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        project_id = project(client)
        accepted = start(client, project_id)
        waiting = wait(client, accepted, "awaiting_input")
        response = client.post(
            f"/api/v1/assistant-turns/{accepted['turn_id']}/answer",
            json=answer_payload(project_id, waiting, answers=[answer]),
        )
        assert response.status_code == 202
        completed = wait(client, accepted, "completed")
        assert completed["response"]["message"] == (
            "Selected: Distribution, Group means"
            if selection == "multiple"
            else "Selected: Show individual observations"
        )


def test_questions_survive_server_restart(tmp_path: Path) -> None:
    configuration = settings(tmp_path)
    with TestClient(create_app(configuration, intent_agent=QuestionAgent())) as client:
        project_id = project(client)
        accepted = start(client, project_id)
        original = wait(client, accepted, "awaiting_input")
    resumed_agent = QuestionAgent()
    with TestClient(create_app(configuration, intent_agent=resumed_agent)) as client:
        recovered = client.get(accepted["links"]["status"]).json()
        assert recovered["question"] == original["question"]
        response = client.post(
            f"/api/v1/assistant-turns/{accepted['turn_id']}/answer",
            json=answer_payload(project_id, recovered),
        )
        assert response.status_code == 202
        completed = wait(client, accepted, "completed")
        assert completed["turn_id"] == accepted["turn_id"]
        assert len(resumed_agent.inputs) == 1
        assert resumed_agent.inputs[0].clarification_answers


def test_failed_and_cancelled_requests_have_terminal_public_state(tmp_path: Path) -> None:
    with TestClient(
        create_app(settings(tmp_path), intent_agent=QuestionAgent(fail=True))
    ) as client:
        accepted = start(client, project(client))
        failed = wait(client, accepted, "failed")
        assert failed["error"]["code"] == "TEST_MODEL_FAILURE"
        assert "Private internal failure" not in json.dumps(failed)
    slow = QuestionAgent(delay=2)
    with TestClient(create_app(settings(tmp_path), intent_agent=slow)) as client:
        accepted = start(client, project(client))
        cancelled = client.post(accepted["links"]["cancel"])
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert not any(
            entry["status"] in {"waiting", "running"} for entry in cancelled.json()["activity"]
        )
        assert client.get(accepted["links"]["status"]).json()["response"] is None


def test_activity_and_answers_are_scoped_to_the_project(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path), intent_agent=QuestionAgent())) as client:
        owner = project(client)
        other = project(client)
        accepted = start(client, owner)
        waiting = wait(client, accepted, "awaiting_input")
        base = f"/api/v1/assistant-turns/{accepted['turn_id']}"
        assert client.get(base, params={"project_id": other}).status_code == 404
        assert client.get(base + "/events", params={"project_id": other}).status_code == 404
        assert client.post(base + "/answer", json=answer_payload(other, waiting)).status_code == 404
        assert client.post(base + "/cancel", params={"project_id": other}).status_code == 404
        assert client.get(accepted["links"]["status"]).json()["status"] == "awaiting_input"


def test_event_stream_reports_persisted_state_and_supports_reconnection(tmp_path: Path) -> None:
    with TestClient(create_app(settings(tmp_path), intent_agent=QuestionAgent())) as client:
        accepted = start(client, project(client))
        snapshot = wait(client, accepted, "awaiting_input")
        response = client.get(accepted["links"]["events"])
        assert response.status_code == 200
        assert "event: assistant.updated" in response.text
        assert f"id: {snapshot['revision']}" in response.text
        replay = client.get(
            accepted["links"]["events"], headers={"Last-Event-ID": str(snapshot["revision"])}
        )
        assert replay.text == ""
