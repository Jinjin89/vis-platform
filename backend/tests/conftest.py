from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from vis_platform_backend.agents.intent import (
    IntentAgentExecution,
    IntentAgentInput,
    LlmTurnObservation,
)
from vis_platform_backend.app import create_app
from vis_platform_backend.config import LlmSettings, Settings
from vis_platform_backend.contracts.intent import (
    IntentAction,
    IntentDecision,
    IntentKind,
    ModeRequests,
    PlotIntent,
    RefinementChange,
    RefinementIntent,
)


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    settings = Settings(
        database_path=tmp_path / "test.sqlite3",
        artifact_root=tmp_path / "artifacts",
        fake_step_delay_seconds=0.001,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def slow_client(tmp_path) -> Iterator[TestClient]:
    settings = Settings(
        database_path=tmp_path / "slow-test.sqlite3",
        artifact_root=tmp_path / "slow-artifacts",
        fake_step_delay_seconds=0.1,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


class ScenarioIntentAgent:
    async def analyze(self, input: IntentAgentInput) -> IntentAgentExecution:
        text = input.text.casefold()
        plot_words = {"plot", "chart", "heatmap", "umap", "violin", "boxplot"}
        has_plot_request = any(word in text for word in plot_words)

        if input.has_active_plot and any(
            word in text for word in {"larger", "smaller", "legend", "color", "labels"}
        ):
            decision = IntentDecision(
                kind=IntentKind.PLOT_REFINE,
                subtype="visual_refinement",
                normalized_request=input.text,
                confidence=0.98,
                next_action=IntentAction.REFINE_CONTEXT,
                refinement=RefinementIntent(
                    changes=[
                        RefinementChange(
                            target="plot",
                            value=input.text,
                            change_class="visual",
                        )
                    ]
                ),
                decision_summary="The request changes the active plot.",
            )
        elif has_plot_request:
            decision = IntentDecision(
                kind=IntentKind.PLOT_CREATE,
                subtype="explicit_plot",
                normalized_request=input.text,
                confidence=0.99,
                next_action=IntentAction.BUILD_CONTEXT,
                plot=PlotIntent(goal=input.text),
                mode_requests=ModeRequests(data="demo" if "demonstration" in text else None),
                decision_summary="The request explicitly asks for a visualization.",
            )
        elif "dataset" in text or "data do i have" in text:
            decision = IntentDecision(
                kind=IntentKind.DATA_QUERY,
                subtype="list_data",
                normalized_request=input.text,
                confidence=0.97,
                next_action=IntentAction.CALL_DATA_TOOLS,
                decision_summary="The request asks about available data.",
                user_reply="Data discovery is not connected yet.",
            )
        else:
            decision = IntentDecision(
                kind=IntentKind.SOCIAL,
                subtype="conversation",
                normalized_request=input.text,
                confidence=0.99,
                next_action=IntentAction.REPLY,
                decision_summary="There is no concrete plotting request.",
                user_reply="I am ready when you want to create a plot.",
            )

        return IntentAgentExecution(
            decision=decision,
            turns=(
                LlmTurnObservation(
                    attempt=1,
                    duration_ms=12,
                    input={
                        "model": "test-model",
                        "authorization": "test-secret",
                        "messages": [{"role": "user", "content": input.text}],
                    },
                    output={
                        "content": decision.model_dump_json(),
                        "reasoning_content": "private test reasoning",
                    },
                    error=None,
                ),
            ),
        )


@pytest.fixture
def agent_client(tmp_path) -> Iterator[TestClient]:
    settings = Settings(
        database_path=tmp_path / "agent-test.sqlite3",
        artifact_root=tmp_path / "agent-artifacts",
        fake_step_delay_seconds=0.001,
        developer_trace_enabled=True,
        developer_trace_token="test-trace-token",
        llm=LlmSettings(api_key="test-secret"),
    )
    with TestClient(create_app(settings, intent_agent=ScenarioIntentAgent())) as test_client:
        yield test_client


class FixtureFigureSizeAgent:
    async def recommend(self, context):
        from vis_platform_backend.contracts.figures import FigureSize

        return FigureSize(width=8, height=5.5)


@pytest.fixture(autouse=True)
def fixture_figure_size_agent(monkeypatch):
    from vis_platform_backend.services import plot_runs

    monkeypatch.setattr(plot_runs, "LlmFigureSizeAgent", lambda _settings: FixtureFigureSizeAgent())
