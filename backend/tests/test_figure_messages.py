from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from conftest import ScenarioIntentAgent
from fastapi.testclient import TestClient
from test_figure_compositions import create, new_project, plot, plot_panel, slot

from vis_platform_backend.app import create_app
from vis_platform_backend.config import LlmSettings, Settings
from vis_platform_backend.contracts.figure_messages import FigurePlan


class ScriptedPlanner:
    """Returns plans from a function of the planner context and records every context."""

    def __init__(self, respond: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        self.respond, self.contexts = respond, []
        self.release = asyncio.Event()
        self.release.set()

    async def plan(self, context: dict[str, Any]) -> FigurePlan:
        self.contexts.append(context)
        await self.release.wait()
        return FigurePlan.model_validate(self.respond(context))


@pytest.fixture
def figure_app(tmp_path) -> Iterator[Callable[[ScriptedPlanner], TestClient]]:
    clients: list[Any] = []

    def start(planner: ScriptedPlanner) -> TestClient:
        settings = Settings(
            database_path=tmp_path / f"figures-{len(clients)}.sqlite3",
            artifact_root=tmp_path / f"artifacts-{len(clients)}",
            fake_step_delay_seconds=0.001,
            llm=LlmSettings(api_key="test-secret"),
        )
        client = TestClient(
            create_app(settings, intent_agent=ScenarioIntentAgent(), figure_planner=planner)
        )
        clients.append(client.__enter__())
        return client

    yield start
    for client in clients:
        client.__exit__(None, None, None)


def base(document: dict[str, Any]) -> str:
    return (
        f"/api/v1/projects/{document['project_id']}/figure-compositions/"
        f"{document['composition_id']}"
    )


def send(client, document, message, request_id="message", **extra):
    response = client.post(
        base(document) + "/messages",
        json={"request_id": request_id, "message": message, **extra},
    )
    assert response.status_code == 202, response.text
    return response.json()


def settle(client, document, statuses=("completed",)):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        current = client.get(base(document)).json()
        last = current["messages"][-1]
        if last["status"] not in {"running"}:
            assert last["status"] in statuses, last
            return current
        time.sleep(0.05)
    raise AssertionError("The figure message did not finish")


def figure_with_plots(client, count=2):
    owner = new_project(client)
    plots = [plot(client, owner) for _ in range(count)]
    panels = [plot_panel(f"p{i}", item, 5, 5 + 70 * i, scale=0.3) for i, item in enumerate(plots)]
    return create(client, owner, panels).json(), plots


def test_replies_and_questions_do_not_edit_the_figure(figure_app):
    def respond(context):
        if "?" in context["message"]:
            return {"action": "reply", "message": "The figure has two panels."}
        if not context["clarification_answers"]:
            return {
                "action": "ask_user",
                "message": "One choice first.",
                "questions": [
                    {
                        "question_id": "title",
                        "header": "Title",
                        "prompt": "Which title should the figure use?",
                        "reason": "The request names two options.",
                        "selection": "single",
                        "choices": [
                            {"choice_id": "short", "label": "Figure 2"},
                            {"choice_id": "long", "label": "Figure 2: Response"},
                        ],
                    }
                ],
            }
        chosen = context["clarification_answers"][0]["answer"]["answers"][0]["choice_ids"][0]
        title = "Figure 2" if chosen == "short" else "Figure 2: Response"
        return {
            "action": "execute",
            "message": "Renaming the figure.",
            "steps": [
                {
                    "kind": "edit",
                    "operations": [{"op": "set_title", "title": title}],
                    "summary": "Renamed the figure.",
                }
            ],
        }

    planner = ScriptedPlanner(respond)
    client = figure_app(planner)
    document, _ = figure_with_plots(client)
    send(client, document, "How many panels are there?")
    replied = settle(client, document)
    assert replied["messages"][0]["response_text"] == "The figure has two panels."
    assert replied["revision"] == 1

    send(client, document, "Rename it", "rename")
    waiting = settle(client, document, ("awaiting_input",))
    message = waiting["messages"][-1]
    assert message["question"]["questions"][0]["question_id"] == "title"
    url = f"{base(document)}/messages/{message['message_id']}/answer"
    answer = {
        "interaction_id": message["question"]["interaction_id"],
        "answers": [{"question_id": "title", "choice_ids": ["long"]}],
    }
    assert client.post(url, json=answer).status_code == 202
    finished = settle(client, document)
    assert finished["title"] == "Figure 2: Response"
    assert finished["messages"][-1]["completed_actions"] == ["Renamed the figure."]
    assert client.post(url, json=answer).status_code == 409
    # The planner saw the figure, its panels, and the selection hint.
    context = planner.contexts[0]
    assert [panel["id"] for panel in context["panels"]] == ["p0", "p1"]
    assert context["figure"]["printable_width_mm"] == 200


def test_edits_additions_and_arrangements_run_in_order(figure_app):
    def respond(context):
        if context["review"]:
            return {"action": "reply", "message": "The layout is fine."}
        saved = context["available_plots"][0]["version_id"]
        return {
            "action": "execute",
            "message": "Adding the saved plot and arranging three panels.",
            "steps": [
                {"kind": "add", "panel_id": "extra", "version_id": saved},
                {
                    "kind": "arrange",
                    "summary": "Arranged the panels.",
                    "render": True,
                    "arrangement": {
                        "type": "column",
                        "children": [
                            {"type": "panel", "panel_id": "extra", "aspect": 2.5},
                            {
                                "type": "row",
                                "children": [
                                    {"type": "panel", "panel_id": "p0", "aspect": 1},
                                    {"type": "panel", "panel_id": "p1", "aspect": 1},
                                ],
                            },
                        ],
                    },
                },
                {
                    "kind": "edit",
                    "summary": "Wrote the legend.",
                    "operations": [
                        {
                            "op": "set_legend",
                            "legend": {"title": "Overview.", "entries": {"extra": "Summary."}},
                        }
                    ],
                },
            ],
        }

    planner = ScriptedPlanner(respond)
    client = figure_app(planner)
    document, _ = figure_with_plots(client)
    # A saved plot that is not yet in the figure.
    plot(client, document["project_id"], "Make a scatter relationship plot")
    first = send(client, document, "Add the scatter plot on top and arrange everything")
    again = send(client, document, "Add the scatter plot on top and arrange everything")
    assert len(again["messages"]) == len(first["messages"]) == 1
    finished = settle(client, document)
    frames = {key: value["frame"] for key, value in finished["panels"].items()}
    assert frames["extra"]["width_mm"] / frames["extra"]["height_mm"] == pytest.approx(2.5, 0.02)
    assert frames["p0"]["height_mm"] == pytest.approx(frames["p1"]["height_mm"], abs=0.3)
    assert frames["p0"]["y_mm"] > frames["extra"]["y_mm"] + frames["extra"]["height_mm"]
    assert {job["status"] for job in finished["jobs"]} == {"completed"}
    assert finished["content"]["legend"]["entries"] == {"extra": "Summary."}
    assert finished["messages"][0]["completed_actions"] == [
        "Added panel “extra”.",
        "Arranged the panels.",
        "Wrote the legend.",
    ]
    assert {panel["label"] for panel in finished["panels"].values()} == {"A", "B", "C"}


def test_plot_steps_use_the_shared_plot_agent(figure_app):
    def respond(context):
        if context["review"]:
            return {"action": "reply", "message": "Done."}
        return {
            "action": "execute",
            "message": "Creating a new panel.",
            "steps": [
                {
                    "kind": "plot",
                    "panel_id": "violin",
                    "instructions": "Use demonstration data to make a violin plot of expression",
                    "width_mm": 90,
                    "height_mm": 60,
                }
            ],
        }

    planner = ScriptedPlanner(respond)
    client = figure_app(planner)
    document, _ = figure_with_plots(client, count=1)
    send(client, document, "Add a violin plot")
    finished = settle(client, document)
    added = next(p for p in finished["content"]["panels"] if p["id"] == "violin")
    version = added["content"]["version_id"]
    assert finished["figures"][version]["execution_mode"] == "demo"
    # The new panel is placed below the existing content.
    assert finished["panels"]["violin"]["frame"]["y_mm"] > finished["panels"]["p0"]["frame"]["y_mm"]
    assert finished["messages"][-1]["completed_actions"] == ["Created panel “violin”."]
    assert finished["messages"][-1]["active_step"] is None


def test_review_rounds_fix_remaining_warnings(figure_app):
    def respond(context):
        if not context["review"]:
            return {
                "action": "execute",
                "message": "Overlapping the panels.",
                "steps": [
                    {
                        "kind": "arrange",
                        "summary": "Arranged only the first panel.",
                        "render": False,
                        "arrangement": {"type": "panel", "panel_id": "p0"},
                    },
                    {
                        "kind": "edit",
                        "summary": "Moved the second panel.",
                        # Crosses the first panel's lower edge: a partial overlap.
                        "operations": [
                            {
                                "op": "set_panel_geometry",
                                "panels": {"p1": {"x_mm": 180, "y_mm": 130, "scale": 0.12}},
                            }
                        ],
                    },
                ],
            }
        if not any(check["code"] == "overlap" for check in context["checks"]):
            return {"action": "reply", "message": "The remaining notes are acceptable."}
        return {
            "action": "execute",
            "message": "Separating the panels.",
            "steps": [
                {
                    "kind": "arrange",
                    "summary": "Separated the panels.",
                    "render": False,
                    "arrangement": {
                        "type": "row",
                        "children": [
                            {"type": "panel", "panel_id": "p0"},
                            {"type": "panel", "panel_id": "p1"},
                        ],
                    },
                }
            ],
        }

    planner = ScriptedPlanner(respond)
    client = figure_app(planner)
    document, _ = figure_with_plots(client)
    send(client, document, "Arrange the figure")
    finished = settle(client, document)
    # One round fixed the overlap; the second accepted the remaining warnings.
    assert [context["review"] for context in planner.contexts] == [False, True, True]
    assert any(c["code"] == "overlap" for c in planner.contexts[1]["checks"])
    assert not [c for c in finished["checks"] if c["code"] == "overlap"]
    assert finished["messages"][-1]["completed_actions"][-1] == "Separated the panels."


def test_failures_and_cancellation_are_reported(figure_app):
    planner = ScriptedPlanner(
        lambda context: {
            "action": "execute",
            "message": "Removing a panel.",
            "steps": [
                {
                    "kind": "edit",
                    "summary": "Removed the panel.",
                    "operations": [{"op": "remove_panel", "panel_id": "missing"}],
                }
            ],
        }
    )
    client = figure_app(planner)
    document, _ = figure_with_plots(client, count=1)
    send(client, document, "Remove the missing panel")
    failed = settle(client, document, ("failed",))
    assert "was not found" in failed["messages"][-1]["error"]
    assert failed["revision"] == 1

    planner.release.clear()
    waiting = send(client, document, "Try again", "slow")
    message_id = waiting["messages"][-1]["message_id"]
    cancelled = client.post(f"{base(document)}/messages/{message_id}/cancel").json()
    assert cancelled["messages"][-1]["status"] == "cancelled"
    planner.release.set()
    time.sleep(0.2)
    assert client.get(base(document)).json()["messages"][-1]["status"] == "cancelled"
    outsider = new_project(client)
    assert (
        client.post(
            f"/api/v1/projects/{outsider}/figure-compositions/{document['composition_id']}"
            "/messages",
            json={"request_id": "x", "message": "hello"},
        ).status_code
        == 404
    )


DEMO = "Use demonstration data to make "


def test_slots_lay_out_the_page_then_fill_one_at_a_time(figure_app):
    prompts = {
        "violin": DEMO + "a violin plot of expression by treatment",
        "scatter": DEMO + "a scatter plot of dose against response",
        "heatmap": "Make a heatmap of the study measurements",
    }

    def respond(context):
        if context["review"] and "Wrote the legend." in context["completed_actions"]:
            return {"action": "reply", "message": "The figure is ready."}
        if context["review"]:
            plots = [panel for panel in context["panels"] if panel["type"] == "plot"]
            return {
                "action": "execute",
                "message": "The legend describes the new plots.",
                "steps": [
                    {
                        "kind": "edit",
                        "summary": "Wrote the legend.",
                        "operations": [
                            {
                                "op": "set_legend",
                                "legend": {"entries": {p["id"]: p["title"] for p in plots}},
                            }
                        ],
                    }
                ],
            }
        return {
            "action": "execute",
            "message": "Building a three-panel figure.",
            "steps": [
                {
                    "kind": "slots",
                    "summary": "Planned three panels.",
                    "slots": [
                        {"panel_id": key, "prompt": text, "aspect": 1.5}
                        for key, text in prompts.items()
                    ],
                    "arrangement": {
                        "type": "column",
                        "children": [
                            {"type": "panel", "panel_id": "violin", "aspect": 2},
                            {
                                "type": "row",
                                "children": [
                                    {"type": "panel", "panel_id": "scatter"},
                                    {"type": "panel", "panel_id": "heatmap"},
                                ],
                            },
                        ],
                    },
                }
            ],
        }

    planner = ScriptedPlanner(respond)
    client = figure_app(planner)
    document = create(client, new_project(client), []).json()
    send(client, document, "Build a figure of the treatment response")
    finished = settle(client, document)
    message = finished["messages"][-1]
    assert planner.contexts[0]["data_source"] == "project"
    # Slots are filled in reading order; a failure leaves its slot and the queue continues.
    assert [(item["panel_id"], item["status"]) for item in message["panels"]] == [
        ("violin", "completed"),
        ("scatter", "completed"),
        ("heatmap", "failed"),
    ]
    assert message["panels"][2]["error"]
    assert message["completed_actions"][:3] == [
        "Planned three panels.",
        "Created panel “violin”.",
        "Created panel “scatter”.",
    ]
    assert message["completed_actions"][3].startswith("Panel “heatmap” could not be created")
    types = {panel["id"]: panel["content"]["type"] for panel in finished["content"]["panels"]}
    assert types == {"violin": "plot", "scatter": "plot", "heatmap": "slot"}
    # Each plot was made, or rendered again, at its slot's size.
    violin = finished["panels"]["violin"]["frame"]
    assert (violin["x_mm"], violin["y_mm"]) == (5, 5)
    assert violin["width_mm"] == pytest.approx(200, abs=0.3)
    assert violin["height_mm"] == pytest.approx(100, abs=0.3)
    scatter, heatmap = finished["panels"]["scatter"]["frame"], finished["panels"]["heatmap"]
    assert scatter["width_mm"] + 4 + heatmap["frame"]["width_mm"] == pytest.approx(200, abs=0.3)
    assert heatmap["label"] == "C"
    # The legend is written in the review, once the plots exist.
    review = planner.contexts[1]
    assert review["review"] and {p["type"] for p in review["panels"]} == {"plot", "slot"}
    assert set(finished["content"]["legend"]["entries"]) == {"violin", "scatter"}
    assert any(check["code"] == "empty_slot" for check in finished["checks"])


def test_create_plot_fills_a_slot_without_planning(figure_app):
    planner = ScriptedPlanner(lambda context: {"action": "reply", "message": "Unused."})
    client = figure_app(planner)
    owner = new_project(client)
    violin = plot(client, owner)
    document = create(
        client,
        owner,
        [
            slot("growth", 5, 5, prompt=DEMO + "a violin plot of expression by treatment"),
            slot("blank", 100, 5, prompt=" "),
            plot_panel("existing", violin, 5, 70, scale=0.3),
        ],
    ).json()
    url = base(document) + "/messages"
    for fill in (["existing"], ["blank"], ["missing"]):
        rejected = client.post(url, json={"request_id": "x", "message": "Create", "fill": fill})
        assert rejected.status_code in {404, 422}, rejected.text
    duplicate = {"request_id": "x", "message": "Create", "fill": ["growth", "growth"]}
    assert client.post(url, json=duplicate).status_code == 422

    send(client, document, "Create the plot for panel A", "fill", fill=["growth"])
    finished = settle(client, document)
    assert planner.contexts == []
    message = finished["messages"][-1]
    assert message["panels"] == [{"panel_id": "growth", "status": "completed", "error": None}]
    growth = next(panel for panel in finished["content"]["panels"] if panel["id"] == "growth")
    assert growth["content"]["type"] == "plot"
    # Repeating the request returns the same message instead of rejecting the filled slot.
    again = send(client, document, "Create the plot for panel A", "fill", fill=["growth"])
    assert len(again["messages"]) == 1
