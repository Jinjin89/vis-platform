import json

import httpx
import pytest

from vis_platform_backend.agents.structured import StructuredAgentError, structured_response
from vis_platform_backend.config import LlmSettings
from vis_platform_backend.contracts.research import DataAnswer


@pytest.mark.asyncio
async def test_truncated_json_gets_a_larger_budget_without_replaying_partial_output(monkeypatch):
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {"content": '{"message":"unfinished'},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": '{"message":"Complete"}'}}
                ]
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = await structured_response(LlmSettings(api_key="test"), DataAnswer, "Return JSON", {})
    assert result.message == "Complete"
    assert [item["max_tokens"] for item in calls] == [16_000, 32_000]
    assert "unfinished" not in json.dumps(calls[1]["messages"])


@pytest.mark.asyncio
async def test_persistent_truncation_has_a_bounded_clear_failure(monkeypatch):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "length", "message": {"content": ""}}]}
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    with pytest.raises(StructuredAgentError, match="output limit"):
        await structured_response(LlmSettings(api_key="test"), DataAnswer, "Return JSON", {})
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_json_mode_meets_provider_requirements_for_plain_task_instructions(monkeypatch):
    def respond(request):
        body = json.loads(request.content)
        if body["response_format"]["type"] == "json_object" and not any(
            "json" in item["content"].casefold() for item in body["messages"]
        ):
            return httpx.Response(400, json={"error": {"message": "Prompt must mention JSON."}})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"message":"Ready"}'},
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
    result = await structured_response(
        LlmSettings(api_key="test"), DataAnswer, "Answer briefly.", {}
    )
    assert result.message == "Ready"
