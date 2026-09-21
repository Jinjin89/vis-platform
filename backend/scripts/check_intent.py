from __future__ import annotations

import argparse
import asyncio
import json

from vis_platform_backend.agents.deepseek_intent import DeepSeekIntentAgent
from vis_platform_backend.agents.intent import IntentAgentInput
from vis_platform_backend.config import Settings


async def run(text: str, *, has_active_plot: bool) -> None:
    settings = Settings.from_environment()
    execution = await DeepSeekIntentAgent(settings.llm).analyze(
        IntentAgentInput(
            text=text,
            has_active_plot=has_active_plot,
            generation_mode="auto",
            gallery_mode="off",
            controls_mode="hybrid",
        )
    )
    print(json.dumps(execution.decision.model_dump(mode="json"), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one DeepSeek intent classification without starting the API.",
    )
    parser.add_argument("text")
    parser.add_argument("--active-plot", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(run(arguments.text, has_active_plot=arguments.active_plot))


if __name__ == "__main__":
    main()
