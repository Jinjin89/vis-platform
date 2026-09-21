import json

import httpx
import pytest

from vis_platform_backend.agents.deepseek_intent import DeepSeekIntentAgent
from vis_platform_backend.agents.intent import (
    ActivePlotContext,
    ConversationMessage,
    IntentAgentInput,
)
from vis_platform_backend.config import LlmSettings


def social_decision() -> dict:
    return {
        "kind": "social",
        "subtype": "greeting",
        "normalized_request": "how are you?",
        "confidence": 0.99,
        "next_action": "reply",
        "mode_requests": {
            "generation": None,
            "gallery": None,
            "controls": None,
        },
        "plot": None,
        "refinement": None,
        "missing_context": [],
        "decision_summary": "The message is conversational and requests no plot.",
        "user_reply": "I am ready to help with a plot.",
    }


@pytest.mark.asyncio
async def test_deepseek_intent_parses_json_and_redacts_reasoning() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "request_1",
                "model": "deepseek-v4-flash-vision-exp",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(social_decision()),
                            "reasoning_content": "private chain text",
                        }
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
        )

    agent = DeepSeekIntentAgent(
        LlmSettings(api_key="test-key"),
        transport=httpx.MockTransport(handler),
    )

    execution = await agent.analyze(
        IntentAgentInput(
            text="how are you?",
            has_active_plot=False,
            generation_mode="auto",
            gallery_mode="off",
            controls_mode="hybrid",
        )
    )

    assert execution.decision.kind == "social"
    serialized = repr(execution.turns)
    assert "private chain text" not in serialized
    assert "test-key" not in serialized
    assert execution.turns[0].output["reasoning_content_redacted"] is True


@pytest.mark.asyncio
async def test_deepseek_intent_retries_invalid_structured_output() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        content = "{}" if attempts == 1 else json.dumps(social_decision())
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "request_" + str(attempts),
                "choices": [{"message": {"content": content}}],
            },
        )

    agent = DeepSeekIntentAgent(
        LlmSettings(api_key="test-key"),
        transport=httpx.MockTransport(handler),
    )

    execution = await agent.analyze(
        IntentAgentInput(
            text="hello",
            has_active_plot=False,
            generation_mode="auto",
            gallery_mode="off",
            controls_mode="hybrid",
        )
    )

    assert attempts == 2
    assert len(execution.turns) == 2
    assert execution.turns[0].error["code"] == "INVALID_INTENT_JSON"
    assert len(execution.turns[0].input["messages"]) == 2
    assert len(execution.turns[1].input["messages"]) == 4
    assert execution.turns[1].input["messages"][2] == {"role": "assistant", "content": "{}"}
    assert "Field required" in execution.turns[1].input["messages"][3]["content"]
    assert execution.decision.kind == "social"


@pytest.mark.asyncio
async def test_model_receives_conversation_capabilities_and_recorded_plot_context() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        messages = payload["messages"]
        context = json.loads(messages[1]["content"].split("\n", 1)[1])
        assert context["conversation"] == [
            {"role": "user", "content": "Compare treatment groups"},
            {"role": "assistant", "content": "We can plan the comparison."},
        ]
        assert context["active_plot"]["original_request"] == "Illustrate treatment groups"
        assert context["active_plot"]["execution_mode"] == "demo"
        assert context["capabilities"]["plotting"]["data_modes"] == ["demo"]
        assert context["capabilities"]["data_upload"] is False
        assert context["data_scope"] == {"mode": "auto"}
        assert context["text"] == "What does this show?"
        return httpx.Response(
            200,
            request=request,
            json={
                "choices": [{"message": {"content": json.dumps(social_decision())}}],
            },
        )

    execution = await DeepSeekIntentAgent(
        LlmSettings(api_key="test-key"),
        transport=httpx.MockTransport(handler),
    ).analyze(
        IntentAgentInput(
            text="What does this show?",
            has_active_plot=True,
            generation_mode="auto",
            gallery_mode="off",
            controls_mode="hybrid",
            conversation=(
                ConversationMessage(role="user", content="Compare treatment groups"),
                ConversationMessage(role="assistant", content="We can plan the comparison."),
            ),
            active_plot=ActivePlotContext(
                version_id="version_one",
                original_request="Illustrate treatment groups",
                latest_request="Illustrate treatment groups",
                description="Illustrative observations.",
                execution_mode="demo",
                validation_status="demo_only",
            ),
        )
    )
    assert execution.decision.user_reply == social_decision()["user_reply"]


@pytest.mark.asyncio
async def test_resuming_orders_the_previous_question_before_the_new_answer() -> None:
    previous = social_decision()
    previous["kind"] = "unclear"
    previous["next_action"] = "ask_user"
    previous["user_reply"] = "Which figure type?"
    answers = (
        {"question": "Which figure type?", "choices": ["Violin distribution"], "free_text": None},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        messages = payload["messages"]
        assert [message["role"] for message in messages] == ["system", "user", "assistant", "user"]
        assert json.loads(messages[2]["content"]) == previous
        latest = json.loads(messages[3]["content"].split("\n", 1)[1])
        assert latest == {"phase": "answer_received", "answers": list(answers)}
        assert "ask me before drawing" not in messages[3]["content"]
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": json.dumps(social_decision())}}]},
        )

    await DeepSeekIntentAgent(
        LlmSettings(api_key="test-key"), transport=httpx.MockTransport(handler)
    ).analyze(
        IntentAgentInput(
            text="Please ask me before drawing",
            has_active_plot=False,
            generation_mode="auto",
            gallery_mode="off",
            controls_mode="hybrid",
            clarification_answers=answers,
            previous_decision=previous,
        )
    )
