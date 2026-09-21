from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_datasets import ProfileOnlyAgent, project, research_plan, upload_collection, wait_run
from test_r_repair import submit
from test_report_messages import config

from vis_platform_backend.app import create_app
from vis_platform_backend.contracts.slide_layout import SlideFrame
from vis_platform_backend.contracts.slides import SlideDeckContent


def create_deck(client, owner, elements=None):
    response = client.post(
        f"/api/v1/projects/{owner}/slides",
        json={
            "request_id": "deck-create",
            "content": {
                "title": "Research presentation",
                "slides": [
                    {"id": "findings", "title": "Key findings", "elements": elements or []},
                    {"id": "takeaways", "title": "Takeaways", "settings": {"layout": "statement"}},
                ],
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_slide_contract_validates_identity_and_geometry():
    with pytest.raises(ValidationError):
        SlideFrame(x=0.9, y=0, width=0.5, height=0.4)
    with pytest.raises(ValidationError):
        SlideDeckContent.model_validate(
            {
                "title": "Deck",
                "slides": [
                    {"id": "same", "title": "Slide", "elements": [{"id": "same", "type": "text"}]}
                ],
            }
        )
    content = SlideDeckContent.model_validate(
        {
            "title": "Deck",
            "slides": [
                {
                    "id": "one",
                    "title": "Finding",
                    "settings": {"layout": "two-column", "notes": "Context"},
                }
            ],
        }
    )
    assert SlideDeckContent.from_document(content.to_document()) == content


def test_slides_reuse_document_operations_and_keep_separate_library(tmp_path):
    with TestClient(create_app(config(tmp_path), data_agent=ProfileOnlyAgent())) as client:
        owner = project(client)
        deck = create_deck(client, owner)
        repeated = create_deck(client, owner)
        assert deck["report_id"] == repeated["report_id"]
        assert client.get(f"/api/v1/projects/{owner}/reports").json()["total"] == 0
        assert client.get(f"/api/v1/projects/{owner}/slides").json()["total"] == 1
        base = f"/api/v1/projects/{owner}/reports/{deck['report_id']}"
        response = client.post(
            base + "/operations",
            json={
                "request_id": "layout",
                "base_revision": 1,
                "operations": [
                    {
                        "op": "set_slide_settings",
                        "section_id": "findings",
                        "settings": {"layout": "two-column", "notes": "Discuss uncertainty."},
                    },
                    {"op": "move_section", "section_id": "takeaways", "before_id": "findings"},
                ],
            },
        )
        assert response.status_code == 200, response.text
        changed = response.json()
        assert changed["content"]["sections"][0]["id"] == "takeaways"
        assert changed["content"]["sections"][1]["slide"]["notes"] == "Discuss uncertainty."
        invalid = client.post(
            base + "/operations",
            json={
                "request_id": "nested",
                "base_revision": changed["revision"],
                "operations": [
                    {"op": "move_section", "section_id": "takeaways", "parent_id": "findings"}
                ],
            },
        )
        assert invalid.status_code == 422
        assert client.get(base).json()["revision"] == changed["revision"]
        outsider = project(client)
        assert (
            client.get(f"/api/v1/projects/{outsider}/reports/{deck['report_id']}").status_code
            == 404
        )
        assert (
            client.get(f"/api/v1/projects/{owner}/slides/{deck['report_id']}/content").json()[
                "slides"
            ][0]["id"]
            == "takeaways"
        )


def test_linked_figures_update_report_and_slides_but_preserve_pins_and_history(tmp_path):
    with TestClient(create_app(config(tmp_path), data_agent=ProfileOnlyAgent())) as client:
        owner = project(client)
        dataset = upload_collection(client, owner)
        result = wait_run(
            client, submit(client, owner, dataset, research_plan(dataset["objects"]))
        )["result"]
        plot_id, first_version = result["plot_id"], result["version_id"]
        shared = f"/api/v1/projects/{owner}/shared-figures/{plot_id}"
        assert client.post(shared, json={"version_id": first_version}).status_code == 200
        live = {
            "id": "live",
            "type": "figure",
            "version_id": first_version,
            "follow_plot_id": plot_id,
        }
        pinned = {"id": "pinned", "type": "figure", "version_id": first_version}
        report_response = client.post(
            f"/api/v1/projects/{owner}/reports",
            json={
                "request_id": "report",
                "content": {
                    "title": "Publication",
                    "sections": [{"id": "results", "title": "Results", "blocks": [live, pinned]}],
                },
            },
        )
        assert report_response.status_code == 201, report_response.text
        report = report_response.json()
        report_url = f"/api/v1/projects/{owner}/reports/{report['report_id']}"
        deck = create_deck(client, owner, [live])
        deck_url = f"/api/v1/projects/{owner}/reports/{deck['report_id']}"
        response = client.post(
            deck_url + "/edits",
            json={
                "request_id": "refine-shared",
                "base_revision": 1,
                "section_id": "findings",
                "block_id": "live",
                "kind": "figure",
                "parameter_changes": {"color": "steelblue"},
            },
        )
        assert response.status_code == 202, response.text
        import time

        for _ in range(400):
            updated = client.get(deck_url).json()
            if updated["edits"][-1]["status"] in {"completed", "failed"}:
                break
            time.sleep(0.025)
        assert updated["edits"][-1]["status"] == "completed", updated["edits"]
        current_version = updated["figure_bindings"]["live"]
        assert current_version != first_version
        other = client.get(report_url).json()
        assert other["figure_bindings"]["live"] == current_version
        assert other["figure_bindings"]["pinned"] == first_version
        assert (
            next(
                c["value"]
                for c in other["figures"][current_version]["controls"]
                if c["id"] == "color"
            )
            == "steelblue"
        )
        assert (
            next(
                c["value"]
                for c in other["figures"][first_version]["controls"]
                if c["id"] == "color"
            )
            == "purple"
        )
        historical = client.get(report_url + "/revisions/1").json()
        assert historical["sections"][0]["blocks"][0]["version_id"] == first_version
        assert historical["sections"][0]["blocks"][0]["follow_plot_id"] is None
        # A Canvas/Workspace experiment alone must not publish a linked update.
        experiment = client.post(
            f"/api/v1/plots/{plot_id}/parameters",
            json={
                "project_id": owner,
                "base_version_id": current_version,
                "changes": {"color": "purple"},
            },
        )
        experimental_version = wait_run(client, experiment.json())["result"]["version_id"]
        assert client.get(report_url).json()["figure_bindings"]["live"] == current_version
        # The linked library previews the exact shared version it will insert.
        library = f"/api/v1/projects/{owner}/reports/figures"
        assert (
            client.get(library + "?linked=true").json()["figures"][0]["version_id"]
            == current_version
        )
        assert client.get(library).json()["figures"][0]["version_id"] == experimental_version
        assert (
            client.put(
                shared,
                json={"version_id": experimental_version, "expected_version_id": first_version},
            ).status_code
            == 409
        )
        assert (
            client.put(
                shared,
                json={"version_id": experimental_version, "expected_version_id": current_version},
            ).status_code
            == 200
        )
        exported = client.get(f"/api/v1/projects/{owner}/slides/{deck['report_id']}/content").json()
        assert exported["slides"][0]["elements"][0]["version_id"] == experimental_version
        assert exported["slides"][0]["elements"][0]["follow_plot_id"] is None
        assert client.get(report_url).json()["figure_bindings"]["pinned"] == first_version
        outsider = project(client)
        assert (
            client.post(
                f"/api/v1/projects/{outsider}/shared-figures/{plot_id}",
                json={"version_id": first_version},
            ).status_code
            == 404
        )
