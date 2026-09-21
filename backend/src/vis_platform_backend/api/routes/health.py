from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from vis_platform_backend.api.dependencies import CoordinatorDependency, SettingsDependency

router = APIRouter(tags=["system"])


class LlmConfigurationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    base_url: str
    model: str
    configured: bool
    thinking_enabled: bool
    reasoning_effort: str


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    api_version: Literal["v1"] = "v1"
    r_runtime_available: bool
    developer_trace_enabled: bool
    llm: LlmConfigurationResponse


@router.get("/health", response_model=HealthResponse)
def health(
    coordinator: CoordinatorDependency,
    settings: SettingsDependency,
) -> HealthResponse:
    return HealthResponse(
        r_runtime_available=coordinator.r_runtime_available,
        developer_trace_enabled=settings.developer_trace_enabled,
        llm=LlmConfigurationResponse(
            provider=settings.llm.provider,
            base_url=settings.llm.base_url,
            model=settings.llm.model,
            configured=settings.llm.configured,
            thinking_enabled=settings.llm.thinking_enabled,
            reasoning_effort=settings.llm.reasoning_effort.value,
        ),
    )
