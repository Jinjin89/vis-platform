import pytest

from vis_platform_backend.config import LlmSettings, ReasoningEffort, Settings


def test_deepseek_settings_load_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    monkeypatch.setenv("VIS_PLATFORM_LLM_MODEL", "deepseek-v4-flash-vision-exp")
    monkeypatch.setenv("VIS_PLATFORM_LLM_THINKING_ENABLED", "false")
    monkeypatch.setenv("VIS_PLATFORM_LLM_REASONING_EFFORT", "max")

    settings = Settings.from_environment()

    assert settings.llm.provider == "deepseek"
    assert settings.llm.api_key == "test-secret"
    assert settings.llm.model == "deepseek-v4-flash-vision-exp"
    assert not settings.llm.thinking_enabled
    assert settings.llm.reasoning_effort is ReasoningEffort.MAX
    assert settings.llm.configured


def test_llm_secret_is_excluded_from_settings_representation() -> None:
    settings = LlmSettings(api_key="never-print-this")

    assert "never-print-this" not in repr(settings)


def test_invalid_boolean_configuration_fails_fast(monkeypatch) -> None:
    monkeypatch.setenv("VIS_PLATFORM_LLM_THINKING_ENABLED", "sometimes")

    with pytest.raises(ValueError, match="must be true or false"):
        Settings.from_environment()
