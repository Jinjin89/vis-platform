"""Deterministic figure plans for browser verification; production uses LlmFigurePlanner."""

from __future__ import annotations

from typing import Any

from vis_platform_backend.contracts.figure_messages import FigurePlan


def _layout(panel_ids: list[str]) -> dict[str, Any]:
    """The first panel gets a full-width row; the rest share rows of two."""
    rows: list[dict[str, Any]] = [{"type": "panel", "panel_id": panel_ids[0]}]
    for index in range(1, len(panel_ids), 2):
        pair = panel_ids[index : index + 2]
        rows.append(
            {"type": "row", "children": [{"type": "panel", "panel_id": key} for key in pair]}
            if len(pair) == 2
            else {"type": "panel", "panel_id": pair[0]}
        )
    return rows[0] if len(rows) == 1 else {"type": "column", "children": rows}


class BrowserFigurePlanner:
    async def plan(self, context: dict[str, Any]) -> FigurePlan:
        text = context["message"].lower()
        panels = [panel for panel in context["panels"] if not panel["locked"]]
        if context["review"]:
            return FigurePlan(action="reply", message="The layout looks balanced.")
        if "which" in text and not context["clarification_answers"]:
            return FigurePlan.model_validate(
                {
                    "action": "ask_user",
                    "message": "One choice before arranging.",
                    "questions": [
                        {
                            "question_id": "emphasis",
                            "header": "Emphasis",
                            "prompt": "Which panel should lead the figure?",
                            "reason": "The first panel receives a full-width row.",
                            "selection": "single",
                            "choices": [
                                {"choice_id": panel["id"], "label": panel["title"] or panel["id"]}
                                for panel in panels[:4]
                            ],
                        }
                    ],
                }
            )
        if "build" in text:
            slots = {
                "distribution": "Use demonstration data to create a violin distribution",
                "comparison": "Use demonstration data to compare expression by treatment",
                "summary": "Use demonstration data to summarise expression by group",
            }
            return FigurePlan.model_validate(
                {
                    "action": "execute",
                    "message": "I planned three panels and will create each plot in turn.",
                    "steps": [
                        {
                            "kind": "slots",
                            "summary": "Planned three panels.",
                            "slots": [
                                {"panel_id": key, "prompt": prompt, "aspect": 1.4}
                                for key, prompt in slots.items()
                            ],
                            "arrangement": _layout(list(slots)),
                        }
                    ],
                }
            )
        if "legend" in text:
            return FigurePlan.model_validate(
                {
                    "action": "execute",
                    "message": "I wrote a legend entry for each panel from its description.",
                    "steps": [
                        {
                            "kind": "edit",
                            "summary": "Wrote the legend.",
                            "operations": [
                                {
                                    "op": "set_legend",
                                    "legend": {
                                        "title": "Overview of the study results.",
                                        "entries": {
                                            panel["id"]: (panel.get("description") or "Panel.")
                                            for panel in context["panels"]
                                        },
                                    },
                                }
                            ],
                        }
                    ],
                }
            )
        if "arrange" in text or "compose" in text or "which" in text:
            order = [panel["id"] for panel in panels]
            if context["clarification_answers"]:
                lead = context["clarification_answers"][-1]["answer"]["answers"][0]["choice_ids"][0]
                order = [lead, *[key for key in order if key != lead]]
            elif context["selection_hint"]:
                lead = context["selection_hint"][0]
                order = [lead, *[key for key in order if key != lead]]
            return FigurePlan.model_validate(
                {
                    "action": "execute",
                    "message": "I arranged the panels so the lead result spans the page.",
                    "steps": [
                        {
                            "kind": "arrange",
                            "summary": "Arranged the panels.",
                            "render": True,
                            "arrangement": _layout(order),
                        }
                    ],
                }
            )
        return FigurePlan(
            action="reply",
            message="Ask me to arrange the panels or to write the legend.",
        )
