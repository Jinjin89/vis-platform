from __future__ import annotations

import time
from uuid import uuid4

import pytest
from browser_server import BrowserDataAgent, BrowserIntentAgent
from fastapi.testclient import TestClient
from test_datasets import RUNTIME, project, upload_collection

from vis_platform_backend.app import create_app
from vis_platform_backend.config import Settings
from vis_platform_backend.contracts.research import DataAnswer


class ReportDataAgent(BrowserDataAgent):
    def __init__(self):
        self.text_contexts = []

    async def answer(self, context):
        self.text_contexts.append(context)
        return DataAnswer(
            message=(
                f"Summary for {context['topic']}. Based on {len(context['figures'])} saved figures."
            )
        )


@pytest.fixture
def report_env(tmp_path):
    settings = Settings(
        database_path=tmp_path / "report.sqlite",
        artifact_root=tmp_path / "artifacts",
        r_home=RUNTIME / "usr/lib/R",
        r_sandbox=RUNTIME / "vis-r-sandbox",
        fake_step_delay_seconds=0.001,
    )
    agent = ReportDataAgent()
    with TestClient(
        create_app(settings, data_agent=agent, intent_agent=BrowserIntentAgent())
    ) as client:
        yield client, settings, agent


def create(client, owner, dataset=None, blocks=None):
    content = {
        "schema_version": "2.0",
        "title": "Treatment report",
        "datasets": [{"dataset_id": dataset["dataset_id"], "revision_id": dataset["revision_id"]}]
        if dataset
        else [],
        "sections": [
            {"id": "comparison", "title": "Treatment comparison", "blocks": blocks or []},
            {"id": "discussion", "title": "Discussion", "blocks": []},
        ],
    }
    response = client.post(
        f"/api/v1/projects/{owner}/reports", json={"content": content, "request_id": uuid4().hex}
    )
    assert response.status_code == 201, response.text
    return response.json()


def path(report):
    return f"/api/v1/projects/{report['project_id']}/reports/{report['report_id']}"


def edit(client, report, **kwargs):
    payload = {
        "request_id": uuid4().hex,
        "base_revision": report["revision"],
        "section_id": "comparison",
        "kind": "figure",
        "prompt": "Compare treatment means",
        **kwargs,
    }
    response = client.post(path(report) + "/edits", json=payload)
    assert response.status_code == 202, response.text
    return response.json(), payload


def finish(client, report, edit_id=None):
    for _ in range(500):
        document = client.get(path(report)).json()
        item = (
            next((e for e in document["edits"] if e["edit_id"] == edit_id), None)
            if edit_id
            else document["edits"][-1]
        )
        if item["status"] in {"completed", "failed", "cancelled"}:
            return document, item
        time.sleep(0.025)
    raise AssertionError("Report edit did not complete")


def test_empty_report_import_validation_and_project_isolation(report_env):
    client, _, _ = report_env
    owner = project(client)
    report = create(client, owner)
    assert report["datasets"] == []
    assert report["content"]["sections"][0]["blocks"] == []
    assert client.get(f"/api/v1/projects/{owner}/reports").json()["total"] == 1
    outsider = project(client)
    foreign = path(report).replace(owner, outsider)
    assert client.get(foreign).status_code == 404
    assert client.get(foreign + "/revisions").status_code == 404
    assert (
        client.put(foreign, json={"base_revision": 1, "content": report["content"]}).status_code
        == 404
    )
    invalid = {
        **report["content"],
        "sections": [
            {"id": "same", "title": "One", "blocks": []},
            {"id": "same", "title": "Two", "blocks": []},
        ],
    }
    assert (
        client.post(
            f"/api/v1/projects/{owner}/reports", json={"content": invalid, "request_id": "bad"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            path(report) + "/edits",
            json={
                "request_id": "no-data",
                "base_revision": 1,
                "section_id": "comparison",
                "kind": "figure",
                "prompt": "Plot data",
            },
        ).status_code
        == 422
    )


def test_pre_report_loads_text_tables_and_rejects_foreign_references(report_env):
    client, _, _ = report_env
    owner = project(client)
    dataset = upload_collection(client, owner)
    report = create(
        client,
        owner,
        dataset,
        [
            {"id": "intro", "type": "text", "body": "## Overview\nA prepared report."},
            {
                "id": "means",
                "type": "table",
                "title": "Group means",
                "columns": ["Group", "Mean"],
                "rows": [["A", 2], ["B", 6]],
                "source_description": "Imported summary",
            },
        ],
    )
    assert report["content"]["sections"][0]["blocks"][1]["rows"][1] == ["B", 6]
    foreign = project(client)
    response = client.post(
        f"/api/v1/projects/{foreign}/reports",
        json={"content": report["content"], "request_id": "foreign"},
    )
    assert response.status_code == 404
    malformed = {
        **report["content"],
        "sections": [
            {
                "id": "t",
                "title": "Table",
                "blocks": [
                    {"id": "b", "type": "table", "columns": ["One"], "rows": [[1, 2]]},
                ],
            }
        ],
    }
    assert (
        client.post(
            f"/api/v1/projects/{owner}/reports",
            json={"content": malformed, "request_id": "bad-table"},
        ).status_code
        == 422
    )


def test_report_creation_and_edit_retries_are_idempotent(report_env):
    client, _, _ = report_env
    owner = project(client)
    payload = {
        "content": {"title": "Report", "datasets": [], "sections": []},
        "request_id": "create-once",
    }
    first = client.post(f"/api/v1/projects/{owner}/reports", json=payload).json()
    again = client.post(f"/api/v1/projects/{owner}/reports", json=payload).json()
    assert first["report_id"] == again["report_id"]
    payload["content"]["title"] = "Different report"
    assert client.post(f"/api/v1/projects/{owner}/reports", json=payload).status_code == 409
    report = create(client, owner)
    accepted, request = edit(client, report, kind="text", prompt="Introduce this topic")
    completed, job = finish(client, accepted)
    assert job["status"] == "completed"
    again = client.post(path(report) + "/edits", json=request)
    assert again.status_code == 202
    assert len(again.json()["edits"]) == 1
    assert again.json()["revision"] == completed["revision"]


def test_real_figure_refinement_preserves_original_and_can_insert_another(report_env):
    client, _, _ = report_env
    owner = project(client)
    report = create(client, owner, upload_collection(client, owner))
    report, _ = edit(client, report)
    report, status = finish(client, report)
    assert status["status"] == "completed", status
    original = report["content"]["sections"][0]["blocks"][0]
    original_result = report["figures"][original["version_id"]]
    first_revision = report["revision"]
    original_svg = client.get(original_result["preview"]["href"]).content
    active, _ = edit(
        client, report, block_id=original["id"], prompt="", parameter_changes={"color": "steelblue"}
    )
    assert active["content"]["sections"][0]["blocks"][0] == original
    report, status = finish(client, active)
    assert status["status"] == "completed", status
    replacement = report["content"]["sections"][0]["blocks"][0]
    assert replacement["id"] == original["id"]
    assert replacement["version_id"] != original["version_id"]
    assert client.get(original_result["preview"]["href"]).content == original_svg
    historical = client.get(path(report) + f"/revisions/{first_revision}").json()
    assert historical["sections"][0]["blocks"][0] == {**original, "follow_plot_id": None}
    active, _ = edit(
        client,
        report,
        block_id=replacement["id"],
        prompt="",
        parameter_changes={"color": "purple"},
        insert_new=True,
    )
    report, status = finish(client, active)
    assert status["status"] == "completed", status
    assert len(report["content"]["sections"][0]["blocks"]) == 2
    assert report["content"]["sections"][0]["blocks"][0] == replacement
    assert client.get(f"/api/v1/projects/{owner}/analysis-results").json()["total"] == 1


def test_report_edits_merge_unrelated_changes_and_reject_stale_saves(report_env):
    client, _, _ = report_env
    owner = project(client)
    report = create(client, owner, upload_collection(client, owner))
    active, _ = edit(client, report)
    content = {**report["content"], "title": "Renamed while plotting"}
    changed = client.put(
        path(report), json={"base_revision": report["revision"], "content": content}
    )
    assert changed.status_code == 200, changed.text
    completed, status = finish(client, active)
    assert status["status"] == "completed", status
    assert completed["title"] == "Renamed while plotting"
    assert len(completed["content"]["sections"][0]["blocks"]) == 1
    assert (
        client.put(
            path(report), json={"base_revision": report["revision"], "content": content}
        ).status_code
        == 409
    )


def test_text_generation_is_scoped_to_topic_and_does_not_run_r(report_env):
    client, _, agent = report_env
    owner = project(client)
    report = create(client, owner, upload_collection(client, owner))
    active, _ = edit(client, report)
    report, status = finish(client, active)
    figure = report["content"]["sections"][0]["blocks"][0]
    active, _ = edit(client, report, kind="text", prompt="Summarize this topic")
    report, status = finish(client, active)
    assert status["status"] == "completed", status
    text = report["content"]["sections"][0]["blocks"][-1]
    assert text["evidence_version_ids"] == [figure["version_id"]]
    assert agent.text_contexts[-1]["topic"] == "Treatment comparison"
    assert len(agent.text_contexts[-1]["figures"]) == 1
    active, _ = edit(
        client, report, kind="text", section_id="discussion", prompt="Write a discussion"
    )
    report, status = finish(client, active)
    assert status["status"] == "completed"
    assert agent.text_contexts[-1]["figures"] == []
    assert client.get(f"/api/v1/projects/{owner}/analysis-results").json()["total"] == 1


def test_failure_and_cancel_preserve_existing_content(report_env):
    client, _, _ = report_env
    owner = project(client)
    report = create(
        client,
        owner,
        upload_collection(client, owner),
        [{"id": "intro", "type": "text", "body": "Keep this paragraph."}],
    )
    active, _ = edit(client, report, prompt="Fail execution to test recovery")
    report, status = finish(client, active)
    assert status["status"] == "failed"
    assert report["content"]["sections"][0]["blocks"][0]["body"] == "Keep this paragraph."
    active, _ = edit(client, report, prompt="Compare groups, but ask me first")
    for _ in range(100):
        latest = client.get(path(report)).json()
        job = latest["edits"][-1]
        if job["status"] == "awaiting_input":
            break
        time.sleep(0.02)
    assert job["assistant_state"]["question"]
    cancelled = client.post(path(report) + f"/edits/{job['edit_id']}/cancel").json()
    assert cancelled["edits"][-1]["status"] == "cancelled"
    assert cancelled["content"]["sections"][0]["blocks"][0]["body"] == "Keep this paragraph."


def test_persistence_and_revision_restore_after_restart(report_env):
    client, settings, _ = report_env
    owner = project(client)
    report = create(
        client, owner, blocks=[{"id": "text", "type": "text", "body": "Original paragraph"}]
    )
    old_content = report["content"]
    content = {**old_content, "title": "Updated title"}
    changed = client.put(
        path(report), json={"base_revision": report["revision"], "content": content}
    ).json()
    with TestClient(
        create_app(settings, data_agent=ReportDataAgent(), intent_agent=BrowserIntentAgent())
    ) as restarted:
        saved = restarted.get(path(report)).json()
        assert saved["title"] == "Updated title"
        restored = restarted.put(
            path(report),
            json={
                "base_revision": saved["revision"],
                "content": old_content,
                "summary": "Restored revision 1",
            },
        ).json()
        assert restored["title"] == "Treatment report"
        assert restored["revision"] > changed["revision"]
        assert len(restarted.get(path(report) + "/revisions").json()["revisions"]) == 3


def test_parallel_new_figures_merge_and_active_topics_cannot_be_removed(report_env):
    client, _, _ = report_env
    owner = project(client)
    report = create(client, owner, upload_collection(client, owner))
    active, _ = edit(client, report)
    first_id = active["edits"][-1]["edit_id"]
    active, _ = edit(client, report, section_id="discussion")
    second_id = active["edits"][-1]["edit_id"]
    response = client.put(
        path(report),
        json={
            "base_revision": report["revision"],
            "content": {**report["content"], "sections": []},
        },
    )
    assert response.status_code == 409
    _, first = finish(client, active, first_id)
    completed, second = finish(client, active, second_id)
    assert first["status"] == second["status"] == "completed"
    assert all(len(topic["blocks"]) == 1 for topic in completed["content"]["sections"])
    assert completed["revision"] == report["revision"] + 2


def test_imported_images_are_project_scoped_and_pinned_by_report_history(report_env):
    from test_reference_images import png

    client, _, _ = report_env
    owner, outsider = project(client), project(client)
    image = client.post(
        f"/api/v1/projects/{owner}/plot-reference-images?name=figure.png",
        content=png(),
        headers={"Content-Type": "image/png"},
    ).json()
    report = create(
        client, owner, blocks=[{"id": "image", "type": "figure", "image_id": image["image_id"]}]
    )
    assert image["image_id"] in report["images"]
    foreign = client.post(
        f"/api/v1/projects/{outsider}/reports",
        json={"content": report["content"], "request_id": "foreign-image"},
    )
    assert foreign.status_code == 404
    updated = {**report["content"], "sections": []}
    assert (
        client.put(
            path(report), json={"base_revision": report["revision"], "content": updated}
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"/api/v1/projects/{owner}/plot-reference-images/{image['image_id']}"
        ).status_code
        == 409
    )


def test_pending_report_question_recovers_after_server_restart(tmp_path):
    settings = Settings(
        database_path=tmp_path / "restart.sqlite",
        artifact_root=tmp_path / "artifacts",
        r_home=RUNTIME / "usr/lib/R",
        r_sandbox=RUNTIME / "vis-r-sandbox",
        fake_step_delay_seconds=0.001,
    )

    def app():
        return create_app(settings, data_agent=ReportDataAgent(), intent_agent=BrowserIntentAgent())

    with TestClient(app()) as client:
        owner = project(client)
        report = create(client, owner, upload_collection(client, owner))
        active, _ = edit(client, report, prompt="Compare treatment means, but ask me first")
        for _ in range(100):
            saved = client.get(path(report)).json()
            job = saved["edits"][-1]
            if job["status"] == "awaiting_input":
                break
            time.sleep(0.02)
        assert job["status"] == "awaiting_input"
        turn_id = job["assistant"]["turn_id"]
        question_id = job["assistant_state"]["question"]["interaction_id"]
    with TestClient(app()) as client:
        restored = client.get(path(report)).json()
        assert restored["edits"][-1]["assistant"]["turn_id"] == turn_id
        response = client.post(
            f"/api/v1/assistant-turns/{turn_id}/answer",
            json={
                "project_id": owner,
                "interaction_id": question_id,
                "answers": [{"question_id": "goal", "choice_ids": ["distribution"]}],
            },
        )
        assert response.status_code == 202, response.text
        completed, status = finish(client, restored)
        assert status["status"] == "completed", status
        assert len(completed["content"]["sections"][0]["blocks"]) == 1


def test_report_discussion_saves_a_reply_without_publishing_content(report_env):
    client, _, agent = report_env
    owner = project(client)
    report = create(
        client, owner, blocks=[{"id": "text", "type": "text", "body": "Existing results."}]
    )
    active, request = edit(
        client, report, kind="discussion", block_id="text", prompt="Explain these findings"
    )
    completed, status = finish(client, active)
    assert status["status"] == "completed", status
    assert status["response_text"]
    assert completed["content"] == report["content"]
    assert completed["revision"] == report["revision"]
    assert agent.text_contexts[-1]["purpose"] == "report_discussion"
    assert agent.text_contexts[-1]["selected_content"]["body"] == "Existing results."
    assert client.get(f"/api/v1/projects/{owner}/analysis-results").json()["total"] == 0
    repeated = client.post(path(report) + "/edits", json=request).json()
    assert len(repeated["edits"]) == 1
    request["request_id"] = "invalid-discussion"
    request["insert_new"] = True
    assert client.post(path(report) + "/edits", json=request).status_code == 422


def test_report_conversation_keeps_original_replies_and_section_scope(report_env):
    client, _, agent = report_env
    owner = project(client)
    report = create(client, owner)
    active, _ = edit(client, report, kind="text", prompt="Draft the result paragraph")
    written, status = finish(client, active)
    original_reply = status["response_text"]
    assert original_reply == written["content"]["sections"][0]["blocks"][0]["body"]
    content = written["content"]
    content["sections"][0]["blocks"][0]["body"] = "The author revised this paragraph."
    saved = client.put(
        path(written), json={"base_revision": written["revision"], "content": content}
    ).json()
    active, _ = edit(client, saved, kind="discussion", prompt="Explain the previous suggestion")
    completed, _ = finish(client, active)
    context = agent.text_contexts[-1]
    assert context["conversation"][-1]["response"] == original_reply
    assert context["section_text"] == ["The author revised this paragraph."]
    assert completed["edits"][0]["response_text"] == original_reply
    active, _ = edit(
        client, completed, kind="discussion", section_id="discussion", prompt="Discuss this section"
    )
    _, status = finish(client, active)
    assert status["status"] == "completed"
    assert agent.text_contexts[-1]["conversation"] == []


def test_discussion_does_not_lock_the_document_for_editing(report_env):
    client, _, _ = report_env
    owner = project(client)
    report = create(
        client, owner, blocks=[{"id": "text", "type": "text", "body": "Initial results"}]
    )
    active, _ = edit(
        client, report, kind="discussion", block_id="text", prompt="Discuss this paragraph"
    )
    updated = {**report["content"], "sections": []}
    response = client.put(
        path(report), json={"base_revision": report["revision"], "content": updated}
    )
    assert response.status_code == 200, response.text
    done, status = finish(client, active)
    assert status["status"] == "completed"
    assert done["content"]["sections"] == []


def test_summary_tracks_evidence_from_other_report_sections(report_env):
    client, _, agent = report_env
    owner = project(client)
    report = create(client, owner, upload_collection(client, owner))
    active, _ = edit(client, report)
    report, status = finish(client, active)
    assert status["status"] == "completed"
    figure = report["content"]["sections"][0]["blocks"][0]
    active, _ = edit(
        client, report, kind="text", section_id="discussion", prompt="Summarize the report findings"
    )
    report, status = finish(client, active)
    assert status["status"] == "completed"
    text = report["content"]["sections"][1]["blocks"][0]
    assert text["evidence_version_ids"] == [figure["version_id"]]
    assert report["stale_text_ids"] == []
    assert (
        agent.text_contexts[-1]["report_context"]["sections"][0]["figures"][0]["version_id"]
        == figure["version_id"]
    )
    content = report["content"]
    content["sections"][0]["blocks"] = []
    updated = client.put(
        path(report), json={"base_revision": report["revision"], "content": content}
    ).json()
    assert text["id"] in updated["stale_text_ids"]
