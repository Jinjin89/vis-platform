"""Deterministic report plans for browser verification; production uses LlmReportPlanner."""

from __future__ import annotations

import re
from uuid import uuid4

from vis_platform_backend.contracts.report_messages import ReportPlan


class BrowserReportPlanner:
    async def plan(self, context):
        message = context["message"]
        text = message.lower()
        sections = context["outline"]

        def new_id(prefix):
            return prefix + "_" + uuid4().hex[:12]

        hint = context.get("selection_hint") or {}
        named = next((section for section in sections if section["title"].lower() in text), None)
        selected = next(
            (section for section in sections if section["id"] == hint.get("section_id")), None
        )
        section = (
            named
            or selected
            or next(
                (s for s in sections if "result" in s["title"].lower()),
                sections[0] if sections else None,
            )
        )
        if "ambiguous" in text and not context["clarification_answers"]:
            return ReportPlan.model_validate(
                {
                    "action": "ask_user",
                    "message": "Choose which comparison to summarize.",
                    "questions": [
                        {
                            "question_id": "target",
                            "header": "Summary",
                            "prompt": "Which section should receive the summary?",
                            "selection": "single",
                            "choices": [
                                {"choice_id": s["id"], "label": s["title"]}
                                for s in (
                                    [
                                        s
                                        for s in sections
                                        if s["title"].lower() in {"results", "discussion"}
                                    ]
                                    or sections[:2]
                                )
                            ],
                        }
                    ],
                }
            )
        if context["clarification_answers"]:
            answers = context["clarification_answers"][-1]["answer"]["answers"]
            chosen = (answers[0].get("choice_ids") or [None])[0]
            section = next((s for s in sections if s["id"] == chosen), section)
        if text.startswith(
            ("what ", "why ", "how ", "explain the previous", "discuss", "review the report")
        ):
            return ReportPlan.model_validate(
                {
                    "action": "reply",
                    "message": (
                        "The report contains the available findings. "
                        "Additional evidence may be needed before drawing conclusions."
                    ),
                }
            )
        if "move" in text and "discussion" in text:
            discussion = next(s for s in sections if s["title"].lower() == "discussion")
            root = next((s for s in sections if s["title"].lower() == "results"), None) or next(
                s for s in sections if s["parent_id"] is None and s["id"] != discussion["id"]
            )
            return ReportPlan.model_validate(
                {
                    "action": "execute",
                    "message": "Reorder the report.",
                    "steps": [
                        {
                            "kind": "document",
                            "summary": "Moved Discussion before Results.",
                            "operations": [
                                {
                                    "op": "move_section",
                                    "section_id": discussion["id"],
                                    "before_id": root["id"],
                                }
                            ],
                        }
                    ],
                }
            )
        steps = []
        if "abstract" in text:
            abstract = next((s for s in sections if s["title"].lower() == "abstract"), None)
            if abstract is None:
                abstract = {"id": new_id("abstract"), "title": "Abstract", "blocks": []}
                first = next((s for s in sections if s["level"] == 1), None)
                steps.append(
                    {
                        "kind": "document",
                        "summary": "Added Abstract at the beginning.",
                        "operations": [
                            {
                                "op": "insert_section",
                                "section": abstract,
                                "before_id": first["id"] if first else None,
                            },
                        ],
                    }
                )
            section = abstract
        elif "subsection" in text:
            if section is None:
                section = {"id": new_id("results"), "title": "Results", "blocks": []}
                steps.append(
                    {
                        "kind": "document",
                        "summary": "Added Results.",
                        "operations": [{"op": "insert_section", "section": section}],
                    }
                )
            subsection = {
                "id": new_id("comparison"),
                "title": "Treatment comparison",
                "level": 2,
                "parent_id": section["id"],
                "blocks": [],
            }
            steps.append(
                {
                    "kind": "document",
                    "summary": "Added the treatment subsection.",
                    "operations": [{"op": "insert_section", "section": subsection}],
                }
            )
            section = subsection
        if section is None:
            section = {"id": new_id("results"), "title": "Results", "blocks": []}
            steps.append(
                {
                    "kind": "document",
                    "summary": "Added Results.",
                    "operations": [{"op": "insert_section", "section": section}],
                }
            )
        numbered = re.search(r"figure\s+(\d+)", text)
        if numbered:
            match = next(
                (
                    (s, b)
                    for s in sections
                    for b in s["blocks"]
                    if b.get("figure_number") == int(numbered.group(1))
                ),
                None,
            )
            if match:
                section = match[0]
                hint["block_id"] = match[1]["id"]
        selected_block = next(
            (block for block in section["blocks"] if block["id"] == hint.get("block_id")), None
        )
        make_plot = any(
            token in text
            for token in (
                "create a figure",
                "create another",
                "plot",
                "compare treatment",
                "fail execution",
                "refine figure",
                "refine this figure",
            )
        )
        if any(token in text for token in ("write", "summarize", "paragraph", "abstract")):
            make_plot = False
        if (
            "subsection" in text or context.get("document_kind") == "slides"
        ) and "create a figure" in text:
            make_plot = True
        plot_id = None
        if make_plot:
            refining = (
                selected_block
                and selected_block["type"] == "figure"
                and ("refine" in text or "blue" in text)
            )
            plot_id = selected_block["id"] if refining else new_id("figure")
            steps.append(
                {
                    "kind": "plot",
                    "section_id": section["id"],
                    "block_id": selected_block["id"] if refining else None,
                    "output_id": plot_id,
                    "instructions": message,
                }
            )
        if not make_plot or (
            ("subsection" in text or context.get("document_kind") == "slides")
            and ("summary" in text or "summarize" in text)
        ):
            replacing = (
                selected_block
                and selected_block["type"] == "text"
                and ("revise" in text or "shorten" in text)
            )
            after = plot_id or next(
                (block["id"] for block in reversed(section["blocks"]) if block["type"] == "figure"),
                None,
            )
            steps.append(
                {
                    "kind": "write",
                    "section_id": section["id"],
                    "block_id": selected_block["id"] if replacing else None,
                    "output_id": selected_block["id"] if replacing else new_id("paragraph"),
                    "after_id": None if replacing else after,
                    "instructions": message,
                }
            )
        return ReportPlan.model_validate(
            {"action": "execute", "message": "Apply the requested changes.", "steps": steps}
        )
