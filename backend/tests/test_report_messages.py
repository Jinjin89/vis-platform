from __future__ import annotations

import json
import time

import pytest
from browser_server import BrowserDataAgent, BrowserIntentAgent
from fastapi.testclient import TestClient
from test_datasets import RUNTIME, project, upload_collection

from vis_platform_backend.app import create_app
from vis_platform_backend.config import Settings
from vis_platform_backend.contracts.report_content import ReportContent
from vis_platform_backend.contracts.report_messages import ReportPlan
from vis_platform_backend.contracts.report_operations import ReportOperationsRequest
from vis_platform_backend.domain.report_operations import apply_report_operations


class QueuePlanner:
    def __init__(self, plans):
        self.plans = list(plans)
        self.contexts = []

    async def plan(self, context):
        self.contexts.append(context)
        return ReportPlan.model_validate(self.plans.pop(0))


def config(tmp_path):
    return Settings(
        database_path=tmp_path / "reports.sqlite",
        artifact_root=tmp_path / "artifacts",
        r_home=RUNTIME / "usr/lib/R",
        r_sandbox=RUNTIME / "vis-r-sandbox",
        fake_step_delay_seconds=0.001,
    )


def create(client, dataset=None):
    owner = dataset["project_id"] if dataset else project(client)
    response = client.post(
        f"/api/v1/projects/{owner}/reports",
        json={
            "request_id": "new-report",
            "content": {
                "schema_version": "2.0",
                "title": "Scientific report",
                "datasets": [
                    {"dataset_id": dataset["dataset_id"], "revision_id": dataset["revision_id"]}
                ]
                if dataset
                else [],
                "sections": [
                    {"id": "results", "title": "Results", "level": 1, "blocks": []},
                    {"id": "discussion", "title": "Discussion", "level": 1, "blocks": []},
                ],
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def path(report):
    return f"/api/v1/projects/{report['project_id']}/reports/{report['report_id']}"


def send(client, report, message, key="message", selection=None):
    response = client.post(
        path(report) + "/messages",
        json={
            "request_id": key,
            "message": message,
            "selection": selection,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def wait(client, report, expected=("completed", "failed", "cancelled", "awaiting_input")):
    for _ in range(800):
        document = client.get(path(report)).json()
        state = document["messages"][-1]
        if state["status"] in expected:
            return document, state
        time.sleep(0.025)
    raise AssertionError("Report message did not finish")


def test_hierarchy_operations_preserve_ids_and_move_subtrees():
    content = ReportContent.model_validate(
        {
            "title": "Report",
            "sections": [
                {
                    "id": "r",
                    "title": "Results",
                    "blocks": [{"id": "p", "type": "text", "body": "Keep me"}],
                },
                {"id": "a", "title": "Analysis", "level": 2, "parent_id": "r"},
                {"id": "d", "title": "Discussion"},
            ],
        }
    )
    request = ReportOperationsRequest.model_validate(
        {
            "request_id": "move",
            "base_revision": 1,
            "operations": [{"op": "move_section", "section_id": "r", "after_id": "d"}],
        }
    )
    moved = apply_report_operations(content, request.operations)
    assert [section.id for section in moved.sections] == ["d", "r", "a"]
    assert moved.sections[1].blocks[0].id == "p"
    assert content.sections[0].id == "r"
    request.operations = ReportOperationsRequest.model_validate(
        {
            "request_id": "move-block",
            "base_revision": 2,
            "operations": [{"op": "move_block", "block_id": "p", "section_id": "a"}],
        }
    ).operations
    changed = apply_report_operations(moved, request.operations)
    assert changed.sections[2].blocks[0].body == "Keep me"


@pytest.mark.parametrize(
    "sections",
    [
        [{"id": "a", "title": "Sub", "level": 2}],
        [{"id": "a", "title": "Root", "parent_id": "x"}],
        [
            {"id": "a", "title": "Root"},
            {"id": "b", "title": "Sub", "level": 2, "parent_id": "a"},
            {"id": "c", "title": "Nested", "level": 2, "parent_id": "b"},
        ],
        [
            {"id": "a", "title": "Root"},
            {"id": "b", "title": "Root 2"},
            {"id": "c", "title": "Wrong order", "level": 2, "parent_id": "a"},
        ],
    ],
)
def test_invalid_section_hierarchy_is_rejected(sections):
    with pytest.raises(ValueError):
        ReportContent.model_validate({"title": "Report", "sections": sections})


def test_operations_are_atomic_idempotent_and_project_scoped(tmp_path):
    with TestClient(create_app(config(tmp_path))) as client:
        report = create(client)
        request = {
            "request_id": "ops",
            "base_revision": 1,
            "operations": [
                {"op": "rename_section", "section_id": "results", "title": "Findings"},
                {"op": "move_section", "section_id": "discussion", "before_id": "missing"},
            ],
        }
        response = client.post(path(report) + "/operations", json=request)
        assert response.status_code == 404
        assert client.get(path(report)).json()["revision"] == 1
        request["operations"].pop()
        saved = client.post(path(report) + "/operations", json=request).json()
        assert saved["content"]["sections"][0]["title"] == "Findings"
        again = client.post(path(report) + "/operations", json=request).json()
        assert again["revision"] == saved["revision"]
        request["request_id"] = "stale"
        assert client.post(path(report) + "/operations", json=request).status_code == 409
        outsider = project(client)
        assert (
            client.post(
                path(report).replace(report["project_id"], outsider) + "/operations", json=request
            ).status_code
            == 404
        )


def test_one_message_creates_subsection_shared_plot_and_positioned_summary(tmp_path):
    planner = QueuePlanner(
        [
            {
                "action": "execute",
                "message": "Add the comparison and its explanation.",
                "steps": [
                    {
                        "kind": "document",
                        "summary": "Added a treatment subsection.",
                        "operations": [
                            {
                                "op": "insert_section",
                                "section": {
                                    "id": "treatment",
                                    "title": "Treatment comparison",
                                    "level": 2,
                                    "parent_id": "results",
                                },
                            },
                        ],
                    },
                    {
                        "kind": "plot",
                        "section_id": "treatment",
                        "output_id": "shared-figure",
                        "instructions": "Compare treatment means",
                    },
                    {
                        "kind": "write",
                        "section_id": "treatment",
                        "output_id": "summary",
                        "after_id": "shared-figure",
                        "instructions": "Explain this figure's results",
                    },
                ],
            }
        ]
    )
    with TestClient(
        create_app(
            config(tmp_path),
            report_planner=planner,
            data_agent=BrowserDataAgent(),
            intent_agent=BrowserIntentAgent(),
        )
    ) as client:
        dataset = upload_collection(client, project(client))
        report = create(client, dataset)
        send(client, report, "Compare the groups in a Results subsection and explain the plot.")
        completed, state = wait(client, report, ("completed", "failed"))
        assert state["status"] == "completed", state
        assert len(planner.contexts) == 1
        assert planner.contexts[0]["selection_hint"] is None
        section = completed["content"]["sections"][1]
        assert section["parent_id"] == "results" and section["level"] == 2
        assert [block["id"] for block in section["blocks"]] == ["shared-figure", "summary"]
        version = section["blocks"][0]["version_id"]
        assert section["blocks"][0]["caption"] == ""
        figure = completed["figures"][version]
        shared_run = next(edit["run"] for edit in completed["edits"] if edit["kind"] == "figure")
        shared = client.get(shared_run["links"]["status"]).json()["result"]
        assert figure == shared
        assert all(edit["message_id"] == state["message_id"] for edit in completed["edits"])
        repeat = send(
            client, report, "Compare the groups in a Results subsection and explain the plot."
        )
        assert len(repeat["messages"]) == 1
        assert repeat["revision"] == completed["revision"]


def test_auto_placement_can_override_optional_selection_and_inspect_more_context(tmp_path):
    planner = QueuePlanner(
        [
            {
                "action": "inspect",
                "message": "Read the results section.",
                "inspect_section_ids": ["results"],
            },
            {
                "action": "execute",
                "message": "Write an abstract.",
                "steps": [
                    {
                        "kind": "document",
                        "summary": "Added Abstract before Results.",
                        "operations": [
                            {
                                "op": "insert_section",
                                "section": {"id": "abstract", "title": "Abstract"},
                                "before_id": "results",
                            },
                        ],
                    },
                    {
                        "kind": "write",
                        "section_id": "abstract",
                        "output_id": "abstract-text",
                        "instructions": "Write an abstract of the available findings",
                    },
                ],
            },
        ]
    )
    with TestClient(
        create_app(config(tmp_path), report_planner=planner, data_agent=BrowserDataAgent())
    ) as client:
        report = create(client)
        content = report["content"]
        content["sections"][0]["blocks"] = [
            {"id": f"paragraph-{index}", "type": "text", "body": f"Finding {index}."}
            for index in range(120)
        ]
        response = client.put(
            path(report),
            json={"base_revision": report["revision"], "content": content},
        )
        assert response.status_code == 200, response.text
        report = response.json()
        send(
            client,
            report,
            "Add an abstract at the beginning.",
            selection={"section_id": "discussion"},
        )
        completed, state = wait(client, report)
        assert state["status"] == "completed", state
        assert completed["content"]["sections"][0]["id"] == "abstract"
        assert completed["content"]["sections"][0]["blocks"][0]["id"] == "abstract-text"
        assert planner.contexts[0]["outline"][0]["complete"] is False
        assert len(planner.contexts[0]["outline"][0]["blocks"]) == 12
        assert planner.contexts[1]["outline"][0]["complete"] is True
        assert len(planner.contexts[1]["outline"][0]["blocks"]) == 120
        assert planner.contexts[1]["outline"][0]["blocks"][-1]["id"] == "paragraph-119"


def test_clarification_resumes_original_message_and_survives_restart(tmp_path):
    settings = config(tmp_path)
    first = QueuePlanner(
        [
            {
                "action": "ask_user",
                "message": "Which comparison should be summarized?",
                "questions": [
                    {
                        "question_id": "comparison",
                        "header": "Comparison",
                        "prompt": "Which comparison?",
                        "selection": "text",
                        "allow_free_text": True,
                    }
                ],
            }
        ]
    )
    with TestClient(create_app(settings, report_planner=first)) as client:
        report = create(client)
        send(client, report, "Summarize the comparison")
        pending, state = wait(client, report)
        assert state["status"] == "awaiting_input"
        question = state["question"]
    second = QueuePlanner(
        [
            {
                "action": "execute",
                "message": "Write the treatment summary.",
                "steps": [
                    {
                        "kind": "write",
                        "section_id": "results",
                        "output_id": "summary",
                        "instructions": "Summarize the treatment comparison",
                    },
                ],
            }
        ]
    )
    with TestClient(
        create_app(settings, report_planner=second, data_agent=BrowserDataAgent())
    ) as client:
        request = {
            "interaction_id": question["interaction_id"],
            "answers": [{"question_id": "comparison", "free_text": "Treatment groups"}],
        }
        response = client.post(
            path(report) + f"/messages/{state['message_id']}/answer", json=request
        )
        assert response.status_code == 202, response.text
        completed, state = wait(client, report)
        assert state["status"] == "completed", state
        assert second.contexts[0]["message"] == "Summarize the comparison"
        assert second.contexts[0]["clarification_answers"]


def test_legacy_reports_upgrade_without_copying_shared_plot_descriptions(tmp_path):
    with TestClient(
        create_app(
            config(tmp_path), data_agent=BrowserDataAgent(), intent_agent=BrowserIntentAgent()
        )
    ) as client:
        dataset = upload_collection(client, project(client))
        report = create(client, dataset)
        from test_reports import edit, finish

        active, _ = edit(client, report, section_id="results")
        report, status = finish(client, active)
        assert status["status"] == "completed"
        figure = next(iter(report["figures"].values()))
        legacy = {
            "schema_version": "1.0",
            "title": "Legacy",
            "topics": [
                {
                    "id": "old",
                    "title": "Results",
                    "blocks": [
                        {
                            "id": "plot",
                            "type": "figure",
                            "version_id": figure["version_id"],
                            "caption": figure["caption"],
                        },
                    ],
                },
            ],
        }
        imported = client.post(
            f"/api/v1/projects/{report['project_id']}/reports",
            json={"request_id": "legacy", "content": legacy},
        ).json()
        assert imported["content"]["schema_version"] == "2.0"
        assert len(imported["content"]["sections"][0]["blocks"]) == 1
        assert imported["content"]["sections"][0]["blocks"][0]["caption"] == ""
        legacy["topics"][0]["blocks"][0]["caption"] = "An author's separate interpretation."
        custom = client.post(
            f"/api/v1/projects/{report['project_id']}/reports",
            json={"request_id": "authored", "content": legacy},
        ).json()
        assert (
            custom["content"]["sections"][0]["blocks"][1]["body"]
            == "An author's separate interpretation."
        )
        assert custom["figures"][figure["version_id"]]["caption"] == figure["caption"]


def test_stored_v1_content_and_history_are_upgraded_on_read(tmp_path):
    settings = config(tmp_path)
    with TestClient(create_app(settings)) as client:
        report = create(client)
        legacy = {
            "schema_version": "1.0",
            "title": "Old saved report",
            "datasets": [],
            "topics": [
                {
                    "id": "legacy-results",
                    "title": "Results",
                    "blocks": [{"id": "old-text", "type": "text", "body": "Preserve this text."}],
                },
            ],
        }
        store = client.app.state.report_service.store
        with store.lock, store.connection:
            store.connection.execute(
                "UPDATE reports SET content_json = ? WHERE report_id = ?",
                (json.dumps(legacy), report["report_id"]),
            )
            store.connection.execute(
                "UPDATE report_revisions SET content_json = ? WHERE report_id = ?",
                (json.dumps(legacy), report["report_id"]),
            )
    with TestClient(create_app(settings)) as client:
        upgraded = client.get(path(report)).json()
        assert upgraded["content"]["schema_version"] == "2.0"
        assert upgraded["content"]["sections"][0]["id"] == "legacy-results"
        assert upgraded["content"]["sections"][0]["blocks"][0]["body"] == "Preserve this text."
        historical = client.get(path(report) + "/revisions/1").json()
        assert historical == upgraded["content"]
        store = client.app.state.report_service.store
        with store.lock:
            raw = store.connection.execute(
                "SELECT content_json FROM report_revisions WHERE report_id = ?",
                (report["report_id"],),
            ).fetchone()[0]
        assert json.loads(raw)["schema_version"] == "1.0"


def test_message_resumes_shared_plot_question_without_replanning_or_duplicate_sections(tmp_path):
    settings = config(tmp_path)
    planner = QueuePlanner(
        [
            {
                "action": "execute",
                "message": "Create the requested subsection and plot.",
                "steps": [
                    {
                        "kind": "document",
                        "summary": "Added a subsection.",
                        "operations": [
                            {
                                "op": "insert_section",
                                "section": {
                                    "id": "comparison",
                                    "title": "Comparison",
                                    "level": 2,
                                    "parent_id": "results",
                                },
                            },
                        ],
                    },
                    {
                        "kind": "plot",
                        "section_id": "comparison",
                        "output_id": "plot",
                        "instructions": "Compare groups but ask me first",
                    },
                ],
            }
        ]
    )
    with TestClient(
        create_app(
            settings,
            report_planner=planner,
            data_agent=BrowserDataAgent(),
            intent_agent=BrowserIntentAgent(),
        )
    ) as client:
        dataset = upload_collection(client, project(client))
        report = create(client, dataset)
        send(client, report, "Create the comparison subsection and its figure.")
        pending, state = wait(client, report)
        assert state["status"] == "awaiting_input"
        assert state["question"] is None
        child = next(
            edit for edit in pending["edits"] if edit["edit_id"] == state["active_edit_id"]
        )
        question = child["assistant_state"]["question"]
        turn_id = child["assistant"]["turn_id"]
    fresh_planner = QueuePlanner([])
    with TestClient(
        create_app(
            settings,
            report_planner=fresh_planner,
            data_agent=BrowserDataAgent(),
            intent_agent=BrowserIntentAgent(),
        )
    ) as client:
        answer = client.post(
            f"/api/v1/assistant-turns/{turn_id}/answer",
            json={
                "project_id": report["project_id"],
                "interaction_id": question["interaction_id"],
                "answers": [{"question_id": "goal", "choice_ids": ["distribution"]}],
            },
        )
        assert answer.status_code == 202
        completed, state = wait(client, report, ("completed", "failed"))
        assert state["status"] == "completed", state
        assert fresh_planner.contexts == []
        assert [section["id"] for section in completed["content"]["sections"]].count(
            "comparison"
        ) == 1
        assert (
            next(
                section
                for section in completed["content"]["sections"]
                if section["id"] == "comparison"
            )["blocks"][0]["id"]
            == "plot"
        )
