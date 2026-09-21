from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ReasoningEffort(StrEnum):
    LOW = "low"
    HIGH = "high"
    MAX = "max"


@dataclass(frozen=True, slots=True)
class LlmSettings:
    provider: str = "deepseek"
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash-vision-exp"
    api_key: str | None = field(default=None, repr=False)
    thinking_enabled: bool = True
    reasoning_effort: ReasoningEffort = ReasoningEffort.HIGH
    timeout_seconds: float = 120

    @property
    def configured(self) -> bool:
        return self.api_key is not None and bool(self.api_key.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path = Path("var/vis-platform.sqlite3")
    artifact_root: Path = Path("var/artifacts")
    fake_step_delay_seconds: float = 0.04
    developer_trace_enabled: bool = False
    developer_trace_token: str | None = field(default=None, repr=False)
    llm: LlmSettings = field(default_factory=LlmSettings)
    r_home: Path | None = None
    r_sandbox: Path | None = None
    analysis_platform_url: str | None = None
    analysis_platform_token: str | None = field(default=None, repr=False)
    upload_limit_bytes: int = 32 * 1024 * 1024

    @classmethod
    def from_environment(cls) -> Settings:
        reasoning_effort = os.getenv(
            "VIS_PLATFORM_LLM_REASONING_EFFORT", ReasoningEffort.HIGH.value
        )
        try:
            resolved_effort = ReasoningEffort(reasoning_effort)
        except ValueError as error:
            choices = ", ".join(effort.value for effort in ReasoningEffort)
            raise ValueError(
                f"VIS_PLATFORM_LLM_REASONING_EFFORT must be one of: {choices}"
            ) from error

        runtime = Path(__file__).resolve().parents[2] / ".runtime"
        r_home = os.getenv("VIS_PLATFORM_R_HOME")
        r_sandbox = os.getenv("VIS_PLATFORM_R_SANDBOX")
        return cls(
            r_home=Path(r_home)
            if r_home
            else (runtime / "usr/lib/R" if runtime.is_dir() else None),
            r_sandbox=Path(r_sandbox)
            if r_sandbox
            else (runtime / "vis-r-sandbox" if runtime.is_dir() else None),
            analysis_platform_url=os.getenv("VIS_PLATFORM_ANALYSIS_PLATFORM_URL") or None,
            analysis_platform_token=os.getenv("VIS_PLATFORM_ANALYSIS_PLATFORM_TOKEN") or None,
            database_path=Path(os.getenv("VIS_PLATFORM_DATABASE_PATH", "var/vis-platform.sqlite3")),
            artifact_root=Path(os.getenv("VIS_PLATFORM_ARTIFACT_ROOT", "var/artifacts")),
            fake_step_delay_seconds=float(
                os.getenv("VIS_PLATFORM_FAKE_STEP_DELAY_SECONDS", "0.04")
            ),
            developer_trace_enabled=_environment_boolean(
                "VIS_PLATFORM_DEVELOPER_TRACE_ENABLED",
                default=False,
            ),
            developer_trace_token=(os.getenv("VIS_PLATFORM_DEVELOPER_TRACE_TOKEN") or None),
            llm=LlmSettings(
                provider=os.getenv("VIS_PLATFORM_LLM_PROVIDER", "deepseek"),
                base_url=os.getenv("VIS_PLATFORM_LLM_BASE_URL", "https://api.deepseek.com").rstrip(
                    "/"
                ),
                model=os.getenv(
                    "VIS_PLATFORM_LLM_MODEL",
                    "deepseek-v4-flash-vision-exp",
                ),
                api_key=(
                    os.getenv("VIS_PLATFORM_LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or None
                ),
                thinking_enabled=_environment_boolean(
                    "VIS_PLATFORM_LLM_THINKING_ENABLED", default=True
                ),
                reasoning_effort=resolved_effort,
                timeout_seconds=float(os.getenv("VIS_PLATFORM_LLM_TIMEOUT_SECONDS", "120")),
            ),
        )


def _environment_boolean(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")
