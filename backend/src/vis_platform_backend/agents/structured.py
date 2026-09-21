from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from vis_platform_backend.agents.messages import ModelContext, user_content
from vis_platform_backend.config import LlmSettings


class StructuredAgentError(RuntimeError):
    pass


async def structured_response[T: BaseModel](
    settings: LlmSettings, model: type[T], instructions: str, context: dict[str, Any]
) -> T:
    if not settings.configured:
        raise StructuredAgentError("The model connection is not configured.")
    images = context.images if isinstance(context, ModelContext) else ()
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": instructions.rstrip()
            + "\n\nReturn a JSON object matching the supplied response_schema.",
        },
        {
            "role": "user",
            "content": user_content(
                json.dumps(
                    {"context": context, "response_schema": model.model_json_schema()},
                    ensure_ascii=False,
                ),
                images,
            ),
        },
    ]
    output_budget = 16_000
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
                response = await client.post(
                    settings.base_url + "/chat/completions",
                    headers={"Authorization": f"Bearer {settings.api_key}"},
                    json={
                        "model": settings.model,
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                        "max_tokens": output_budget,
                        "thinking": {
                            "type": "enabled" if settings.thinking_enabled else "disabled"
                        },
                        "reasoning_effort": settings.reasoning_effort.value,
                    },
                )
                response.raise_for_status()
                choice = response.json()["choices"][0]
                content = choice["message"]["content"]
            if choice.get("finish_reason") == "length":
                if attempt:
                    raise StructuredAgentError(
                        "The model response exceeded its output limit. Try a smaller "
                        "analysis request."
                    )
                output_budget = 32_000
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The response was truncated. Return a complete, concise JSON "
                            "object with the same requirements."
                        ),
                    }
                )
                continue
            if not isinstance(content, str):
                raise StructuredAgentError("The model returned an invalid response.")
            if content.strip().startswith("```"):
                content = "\n".join(content.strip().splitlines()[1:-1])
            try:
                return model.model_validate_json(content)
            except ValidationError as error:
                if attempt:
                    raise StructuredAgentError(
                        "The model could not produce a valid data plan."
                    ) from error
                issues = [
                    {"location": list(item["loc"]), "message": item["msg"]}
                    for item in error.errors(include_input=False, include_context=False)
                ]
                messages += [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": "Correct the response to satisfy the schema: "
                        + json.dumps(issues),
                    },
                ]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
            raise StructuredAgentError(
                "The data-planning model could not be reached or returned an invalid response."
            ) from error
    raise StructuredAgentError("The model could not produce a valid response.")
