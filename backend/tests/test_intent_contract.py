import pytest
from pydantic import ValidationError

from vis_platform_backend.contracts.intent import IntentDecision


def test_social_intent_cannot_route_to_plot_context() -> None:
    with pytest.raises(ValidationError, match="next_action"):
        IntentDecision.model_validate(
            {
                "kind": "social",
                "subtype": "greeting",
                "normalized_request": "hello",
                "confidence": 1,
                "next_action": "build_context",
                "decision_summary": "Incorrect route",
                "user_reply": "Hello",
            }
        )


def test_plot_intent_requires_plot_details() -> None:
    with pytest.raises(ValidationError, match="plot details"):
        IntentDecision.model_validate(
            {
                "kind": "plot_create",
                "subtype": "new_plot",
                "normalized_request": "make a plot",
                "confidence": 0.9,
                "next_action": "build_context",
                "decision_summary": "Plot requested",
            }
        )


def test_intent_confidence_is_bounded() -> None:
    with pytest.raises(ValidationError):
        IntentDecision.model_validate(
            {
                "kind": "social",
                "subtype": "greeting",
                "normalized_request": "hello",
                "confidence": 1.5,
                "next_action": "reply",
                "decision_summary": "Greeting",
                "user_reply": "Hello",
            }
        )


@pytest.mark.parametrize("action", ["reply", "ask_user", "reject"])
def test_plot_intent_can_respond_without_executing(action: str) -> None:
    decision = IntentDecision.model_validate(
        {
            "kind": "plot_create",
            "subtype": "needs_context",
            "normalized_request": "Compare treatments",
            "confidence": 0.9,
            "next_action": action,
            "plot": {"goal": "Compare treatments"},
            "decision_summary": "Execution is not ready.",
            "user_reply": "Which treatment groups?",
        }
    )
    assert decision.next_action == action


@pytest.mark.parametrize("message", [None, "", "   "])
def test_message_routes_require_a_nonempty_reply(message: str | None) -> None:
    with pytest.raises(ValidationError):
        IntentDecision.model_validate(
            {
                "kind": "plot_create",
                "subtype": "needs_context",
                "normalized_request": "Compare treatments",
                "confidence": 0.9,
                "next_action": "reply",
                "plot": {"goal": "Compare treatments"},
                "decision_summary": "Execution is not ready.",
                "user_reply": message,
            }
        )


@pytest.mark.parametrize("kind", ["plot_create", "plot_refine"])
def test_unready_intent_does_not_require_an_executable_plan(kind: str) -> None:
    decision = IntentDecision.model_validate(
        {
            "kind": kind,
            "subtype": "unavailable",
            "normalized_request": "Use research data",
            "confidence": 0.9,
            "next_action": "reject",
            "decision_summary": "No data access.",
            "user_reply": "Research-data plotting is not connected here.",
        }
    )
    assert decision.plot is None
    assert decision.refinement is None
