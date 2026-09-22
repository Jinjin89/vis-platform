from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient

from vis_platform_backend.agents.intent import IntentAgentExecution, IntentAgentInput
from vis_platform_backend.app import create_app
from vis_platform_backend.config import Settings
from vis_platform_backend.contracts.intent import IntentDecision


class RecordingAgent:
    def __init__(self, decisions: list[dict]) -> None:
        self.decisions = decisions
        self.inputs: list[IntentAgentInput] = []

    async def analyze(self, input: IntentAgentInput) -> IntentAgentExecution:
        self.inputs.append(input)
        return IntentAgentExecution(
            decision=IntentDecision.model_validate(self.decisions[len(self.inputs) - 1]),
            turns=(),
        )


def reply(message: str = "Hello! How can I help?") -> dict:
    return {
        "kind": "social",
        "subtype": "conversation",
        "normalized_request": "Continue discussion",
        "confidence": 0.95,
        "next_action": "reply",
        "decision_summary": "Answer the request.",
        "user_reply": message,
    }


def plot(**updates) -> dict:
    return {
        "kind": "plot_create",
        "subtype": "new_plot",
        "normalized_request": "Plot expression by treatment",
        "confidence": 0.95,
        "next_action": "build_context",
        "decision_summary": "Plot requested.",
        "plot": {"goal": "Compare expression by treatment"},
        **updates,
    }


def settings(tmp_path) -> Settings:
    return Settings(
        database_path=tmp_path / "test.sqlite3",
        artifact_root=tmp_path / "artifacts",
        fake_step_delay_seconds=0.001,
    )


def project(client: TestClient, name: str = "Study") -> str:
    return client.post("/api/v1/projects", json={"name": name}).json()["project_id"]


def turn(client: TestClient, project_id: str, text: str, **options) -> dict:
    response = client.post(
        "/api/v1/assistant-turns",
        json={
            "project_id": project_id,
            "request": {"text": text},
            "data_scope": {"mode": "auto"},
            **options,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "text,message",
    [
        ("Hi", "Hello! How can I help?"),
        (
            "What does a violin plot show?",
            "A violin plot shows the distribution and density of observations.",
        ),
        ("Explain the term dataset", "A dataset is a collection of related observations."),
        ("请用中文解释置信区间", "置信区间表达估计的不确定性。"),
    ],
)
def test_preserves_request_specific_replies_without_keyword_overrides(
    tmp_path, text, message
) -> None:
    agent = RecordingAgent([reply(message)])
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        result = turn(client, project(client), text)
        assert result["message"] == message
        assert result["plot_run"] is None
        assert result["intent"]["user_reply"] == message
        assert (
            client.app.state.repository.get_assistant_turn(result["turn_id"])["message"] == message
        )
        assert not list(client.app.state.settings.artifact_root.rglob("*.svg"))


def test_follow_up_receives_project_scoped_persisted_history(tmp_path) -> None:
    agent = RecordingAgent(
        [
            reply("Use a violin plot for the distribution."),
            reply("Another study."),
            reply("I will keep those groups."),
        ]
    )
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        first_project = project(client)
        other_project = project(client, "Other")
        turn(client, first_project, "Compare expression across treatment groups")
        turn(client, other_project, "Unrelated private study")
    # A restart must not erase the conversation supplied to the model.
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        turn(client, first_project, "Keep the same groups")
    assert [asdict(message) for message in agent.inputs[-1].conversation] == [
        {"role": "user", "content": "Compare expression across treatment groups"},
        {"role": "assistant", "content": "Use a violin plot for the distribution."},
    ]
    assert agent.inputs[-1].data_scope.mode == "auto"
    assert agent.inputs[-1].capabilities.plotting.data_modes == ("demo",)
    assert agent.inputs[-1].capabilities.data_discovery


def test_each_workspace_conversation_has_its_own_history(tmp_path) -> None:
    agent = RecordingAgent([reply("First answer."), reply("Other answer."), reply("Again.")] * 2)
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        project_id = project(client)
        first, second = (
            client.post(
                f"/api/v1/projects/{project_id}/workspace-sessions",
                json={"request_id": key, "title": key},
            ).json()["session_id"]
            for key in ("first", "second")
        )
        turn(client, project_id, "Compare treatment groups", session_id=first)
        turn(client, project_id, "Unrelated question", session_id=second)
        turn(client, project_id, "Keep the same groups", session_id=first)
        assert [message.content for message in agent.inputs[-1].conversation] == [
            "Compare treatment groups",
            "First answer.",
        ]
        # Turns outside a conversation, such as report and figure edits, keep their own history.
        turn(client, project_id, "Report request")
        assert agent.inputs[-1].conversation == ()


def test_conversation_window_is_bounded_and_excludes_current_turn(tmp_path) -> None:
    agent = RecordingAgent([reply()] * 16)
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        project_id = project(client)
        for index in range(16):
            turn(client, project_id, f"Request {index}")
    history = agent.inputs[-1].conversation
    assert len(history) == 24
    assert history[0].content == "Request 3"
    assert history[-2].content == "Request 14"


@pytest.mark.parametrize(
    "decision,scope",
    [
        (plot(), {"mode": "auto"}),
        (plot(mode_requests={"data": "demo"}), {"mode": "selected", "bundle_ids": ["bundle_real"]}),
        (plot(mode_requests={"data": "demo", "generation": "raw_code"}), {"mode": "auto"}),
    ],
)
def test_capability_gate_never_substitutes_a_demo_for_requested_work(
    tmp_path, decision, scope
) -> None:
    agent = RecordingAgent([decision])
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        result = turn(client, project(client), "Plot the requested data", data_scope=scope)
        assert result["outcome"] == "message"
        assert result["plot_run"] is None
        assert result["intent"]["next_action"] == "reply"
        assert "not connected" in result["message"]
        assert client.app.state.repository.active_run_ids() == []
        assert not list(client.app.state.settings.artifact_root.rglob("*.svg"))


def test_model_can_explain_plot_readiness_without_starting_a_run(tmp_path) -> None:
    message = "I can help plan your heatmap, but research-data plotting is not connected here."
    agent = RecordingAgent([plot(next_action="reply", user_reply=message)])
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        result = turn(client, project(client), "Make a heatmap of my expression data")
        assert result["intent"]["kind"] == "plot_create"
        assert result["message"] == message
        assert result["plot_run"] is None


def test_unresolved_context_blocks_execution_even_for_an_explicit_demo(tmp_path) -> None:
    agent = RecordingAgent(
        [plot(mode_requests={"data": "demo"}, missing_context=["which comparison to illustrate"])]
    )
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        result = turn(client, project(client), "Use demo data")
        assert result["intent"]["next_action"] == "ask_user"
        assert "which comparison" in result["message"]
        assert result["plot_run"] is None


def test_explicit_demo_uses_resolved_follow_up_and_exposes_saved_plot_context(tmp_path) -> None:
    import time

    request_text = "Use demonstration data to show a scatter relationship between dose and response"
    agent = RecordingAgent(
        [
            reply("We can illustrate dose and response."),
            plot(normalized_request=request_text, mode_requests={"data": "demo"}),
            reply("This figure uses illustrative observations."),
            plot(),
        ]
    )
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        project_id = project(client)
        turn(client, project_id, "Plan a dose-response example")
        result = turn(client, project_id, "Yes, use demonstration data")
        assert result["outcome"] == "plot_run"
        run = result["plot_run"]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            snapshot = client.get(run["links"]["status"]).json()
            if snapshot["status"] == "completed":
                break
            time.sleep(0.01)
        assert snapshot["status"] == "completed"
        stored = client.app.state.repository.get_run(run["run_id"])
        assert stored["request"]["request"]["text"] == request_text
        assert stored["request"]["data_scope"]["mode"] == "demo"
        version_id = snapshot["result"]["version_id"]
        answer = turn(client, project_id, "What data did you use?", base_version_id=version_id)
        assert answer["outcome"] == "message"
        context = agent.inputs[-1].active_plot
        assert context.version_id == version_id
        assert context.original_request == request_text
        assert context.execution_mode == "demo"
        assert context.validation_status == "demo_only"
        assert "demo" in context.description.lower()
        assert "Plot run status: completed" in agent.inputs[-1].conversation[-1].content
        assert "storage_path" not in repr(context)
        # A completed demonstration must not authorize demo data for a later research request.
        research = turn(client, project_id, "Now plot my real data", base_version_id=version_id)
        assert research["outcome"] == "message"
        assert research["plot_run"] is None


def test_active_version_is_checked_before_calling_model(tmp_path) -> None:
    agent = RecordingAgent([])
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        response = client.post(
            "/api/v1/assistant-turns",
            json={
                "project_id": project(client),
                "request": {"text": "Explain the plot"},
                "data_scope": {"mode": "auto"},
                "base_version_id": "version_missing",
            },
        )
        assert response.status_code == 404
        assert agent.inputs == []


def test_explicit_engine_cannot_be_downgraded_to_demo_engine(tmp_path) -> None:
    agent = RecordingAgent([plot(mode_requests={"data": "demo", "generation": "auto"})])
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        result = turn(
            client,
            project(client),
            "Use the requested engine",
            request={
                "text": "Use the requested engine",
                "generation_mode": "raw_code",
            },
        )
        assert result["outcome"] == "message"
        assert "engine is not connected" in result["message"]


def test_explicit_research_request_can_leave_demo_scope(tmp_path) -> None:
    agent = RecordingAgent([plot(mode_requests={"data": "auto"})])
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        result = turn(client, project(client), "Use real data instead", data_scope={"mode": "demo"})
        assert result["outcome"] == "message"
        assert "Research-data" in result["message"]


def test_unavailable_plot_can_be_declined_with_its_contextual_reply(tmp_path) -> None:
    message = "Research-data plotting is not connected, so I cannot render your expression data."
    agent = RecordingAgent([plot(next_action="reject", user_reply=message)])
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        result = turn(client, project(client), "Now plot my real expression data")
        assert result["outcome"] == "message"
        assert result["intent"]["next_action"] == "reject"
        assert result["message"] == message
        assert result["plot_run"] is None
