"""Isolated API for browser tests; uses real persistence, planning, and rendering paths."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import uvicorn
from figure_plans import BrowserFigurePlanner
from report_plans import BrowserReportPlanner
from test_datasets import ProfileOnlyAgent, research_plan
from transcriptomic_plans import transcriptomic_plan

from vis_platform_backend.agents.intent import IntentAgentExecution, IntentAgentInput
from vis_platform_backend.app import create_app
from vis_platform_backend.config import Settings
from vis_platform_backend.contracts.intent import IntentDecision
from vis_platform_backend.contracts.research import DataAnswer, ResearchDecision


class BrowserIntentAgent:
    async def analyze(self, input: IntentAgentInput) -> IntentAgentExecution:
        await asyncio.sleep(0.15)
        if "ask me" in input.text.lower() and not input.clarification_answers:
            decision = {
                "kind": "plot_create",
                "subtype": "clarification",
                "normalized_request": input.text,
                "confidence": 1,
                "next_action": "ask_user",
                "decision_summary": "One choice is needed before preparing the requested figure.",
                "user_reply": "Choose what the comparison should emphasize.",
                "questions": [
                    {
                        "question_id": "goal",
                        "header": "Comparison",
                        "prompt": "What should this comparison emphasize?",
                        "reason": "This determines which information takes priority in the figure.",
                        "selection": "single",
                        "allow_free_text": True,
                        "choices": [
                            {
                                "choice_id": "distribution",
                                "label": "The full distribution",
                                "description": "Show the shape and spread within each group.",
                                "recommended": True,
                            },
                            {
                                "choice_id": "average",
                                "label": "Group averages",
                                "description": "Focus on mean differences.",
                            },
                        ],
                    }
                ],
            }
        elif "explain" in input.text.lower() or "hello" in input.text.lower():
            decision = {
                "kind": "social",
                "subtype": "explanation",
                "normalized_request": input.text,
                "confidence": 1,
                "next_action": "reply",
                "decision_summary": (
                    "Answer the question using the recorded context "
                    "without creating another figure."
                ),
                "user_reply": (
                    "**Shape and spread**\n\nA distribution shows how observations "
                    "vary within each group.\n\n"
                )
                + (
                    "- Compare the center, spread, and shape of the groups.\n"
                    "- Show individual observations alongside a summary.\n\n"
                )
                * 10,
            }
        elif input.has_active_plot and input.text.startswith("Refine the selected plot"):
            decision = {
                "kind": "plot_refine",
                "subtype": "visual",
                "normalized_request": input.text,
                "confidence": 1,
                "next_action": "refine_context",
                "refinement": {
                    "reuse_data": True,
                    "changes": [
                        {"target": "color", "value": "steelblue", "change_class": "visual"}
                    ],
                },
                "decision_summary": "Refine the selected immutable plot version.",
            }
        elif input.data_scope.mode == "selected" or (
            "saved analysis" in input.text.lower()
            and input.workspace_context.get("get_current_results", {}).get("analysis_results")
        ):
            only_analysis = "without a plot" in input.text.lower()
            decision = {
                "kind": "analysis_create" if only_analysis else "plot_create",
                "subtype": "research",
                "normalized_request": input.text,
                "confidence": 1,
                "next_action": "execute_analysis" if only_analysis else "build_context",
                "analysis" if only_analysis else "plot": {"goal": input.text},
                "decision_summary": "Use the selected real data and save the requested outputs.",
            }
        else:
            goal = (
                "Use demonstration data to create a violin distribution of expression by treatment"
            )
            decision = {
                "kind": "plot_create",
                "subtype": "demo",
                "normalized_request": goal,
                "confidence": 1,
                "next_action": "build_context",
                "mode_requests": {"data": "demo"},
                "plot": {"goal": goal},
                "decision_summary": (
                    "The user explicitly chose demonstration data. "
                    "The available renderer supports this distribution figure."
                ),
            }
        return IntentAgentExecution(decision=IntentDecision.model_validate(decision), turns=())


class BrowserDataAgent(ProfileOnlyAgent):
    async def answer(self, context):
        if context.get("document_kind") == "slides":
            return DataAnswer(
                message=(
                    "- Group B has a higher observed mean than Group A.\n"
                    "- The figure summarizes the supplied treatment measurements.\n"
                    "- Further evidence is needed to assess uncertainty."
                )
            )
        if context.get("purpose") in {"report_text", "report_discussion"}:
            return DataAnswer(
                message=(
                    f"Summary for {context['topic']}. "
                    "Based on the saved figures and dataset descriptions."
                )
            )
        return await super().answer(context)

    async def plan(self, context):
        if "fail execution" in context.get("user_request", "").lower():
            plan = research_plan(context["objects"])
            plan["render_code"] = 'stop("Test R rendering failure")'
            return ResearchDecision.model_validate(
                {"action": "execute", "summary": "Exercise R error handling.", "plan": plan}
            )
        if any(
            item["name"] in {"Cell embedding", "Spatial coordinates"} for item in context["objects"]
        ):
            spatial = any(item["name"] == "Spatial coordinates" for item in context["objects"])
            return ResearchDecision(
                action="execute",
                summary="Plot the selected demonstration collection.",
                plan=transcriptomic_plan(context["objects"], spatial=spatial),
            )
        if context.get("selected_result_ids"):
            result = context["results"][0]
            return ResearchDecision.model_validate(
                {
                    "action": "execute",
                    "summary": "Render the selected saved analysis.",
                    "plan": {
                        "title": "Treatment comparison",
                        "figure_size": {"width": 6.5, "height": 4.5},
                        "description": result["description"],
                        "reuse_result_id": result["result_id"],
                        "render_code": (
                            "barplot(results$comparison$value, "
                            'names.arg=results$comparison$group, main="Treatment comparison",'
                            ' col="purple")'
                        ),
                    },
                }
            )
        return ResearchDecision.model_validate(
            {
                "action": "execute",
                "summary": "Use the selected measurements and sample annotations.",
                "plan": research_plan(
                    context["objects"], render=context["intent"] != "analysis_create"
                ),
            }
        )


class BrowserFigureSizeAgent:
    async def recommend(self, context):
        from vis_platform_backend.contracts.figures import FigureSize

        return FigureSize(width=8, height=5.5)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="vis-browser-api-") as folder:
        settings = Settings(
            database_path=Path(folder) / "browser.sqlite3",
            artifact_root=Path(folder) / "artifacts",
            fake_step_delay_seconds=0.01,
            r_home=Path(__file__).resolve().parents[1] / ".runtime/usr/lib/R",
            r_sandbox=Path(__file__).resolve().parents[1] / ".runtime/vis-r-sandbox",
        )
        uvicorn.run(
            create_app(
                settings,
                intent_agent=BrowserIntentAgent(),
                data_agent=BrowserDataAgent(),
                figure_size_agent=BrowserFigureSizeAgent(),
                report_planner=BrowserReportPlanner(),
                figure_planner=BrowserFigurePlanner(),
            ),
            host="127.0.0.1",
            port=18188,
            log_level="warning",
        )
