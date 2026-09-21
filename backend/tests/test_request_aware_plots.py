import time

import pytest
from fastapi.testclient import TestClient


def _create_project(client: TestClient) -> str:
    response = client.post("/api/v1/projects", json={"name": "Figure family test"})
    assert response.status_code == 201
    return response.json()["project_id"]


def _create_run(
    client: TestClient,
    project_id: str,
    text: str,
    *,
    base_version_id: str | None = None,
) -> dict:
    response = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": project_id,
            "data_scope": {"mode": "demo"},
            "base_version_id": base_version_id,
            "request": {"text": text},
        },
    )
    assert response.status_code == 202
    return response.json()


def _wait_for_status(client: TestClient, path: str, expected: str) -> dict:
    deadline = time.monotonic() + 2
    snapshot = None
    while time.monotonic() < deadline:
        response = client.get(path)
        assert response.status_code == 200
        snapshot = response.json()
        if snapshot["status"] == expected:
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"Run did not reach {expected}; last snapshot: {snapshot}")


@pytest.mark.parametrize(
    ("request_text", "expected_kind", "expected_title"),
    [
        (
            "Create a violin plot of expression by treatment group",
            "distribution",
            "Expression distribution by group",
        ),
        (
            "Plot response versus dose as a scatter relationship",
            "relationship",
            "Dose–response relationship",
        ),
        (
            "Compare treatment and control",
            "group_comparison",
            "Measured response by research group",
        ),
    ],
)
def test_plot_request_selects_matching_demo_figure_family(
    client: TestClient,
    request_text: str,
    expected_kind: str,
    expected_title: str,
) -> None:
    project_id = _create_project(client)
    accepted = _create_run(client, project_id, request_text)
    snapshot = _wait_for_status(client, accepted["links"]["status"], "completed")

    artifact = client.get(snapshot["result"]["preview"]["href"])

    assert artifact.status_code == 200
    assert f'data-figure-kind="{expected_kind}"' in artifact.text
    assert expected_title in artifact.text
    assert "DEMONSTRATION · NO DATASET" in artifact.text


def test_survival_answer_controls_request_aware_figure_title(client: TestClient) -> None:
    project_id = _create_project(client)
    accepted = _create_run(
        client,
        project_id,
        "Show a publication-style survival curve by cohort",
    )
    waiting = _wait_for_status(client, accepted["links"]["status"], "awaiting_input")

    response = client.post(
        (
            f"/api/v1/plot-runs/{accepted['run_id']}/questions/"
            f"{waiting['pending_question']['question_id']}/answer"
        ),
        json={"choice_id": "overall_survival"},
    )
    assert response.status_code == 202
    snapshot = _wait_for_status(client, accepted["links"]["status"], "completed")

    artifact = client.get(snapshot["result"]["preview"]["href"])

    assert 'data-figure-kind="survival"' in artifact.text
    assert "Overall survival by cohort" in artifact.text
    assert "Number at risk" in artifact.text
    assert "Measured response by research group" not in artifact.text


@pytest.mark.parametrize(
    "data_scope", [None, {"mode": "auto"}, {"mode": "selected", "bundle_ids": ["bundle_one"]}]
)
def test_research_requests_never_fall_back_to_demo(
    client: TestClient, data_scope: dict | None
) -> None:
    project_id = _create_project(client)
    payload = {
        "project_id": project_id,
        "request": {"text": "Show my treatment outcomes"},
    }
    if data_scope is not None:
        payload["data_scope"] = data_scope
    response = client.post("/api/v1/plot-runs", json=payload)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLOT_CAPABILITY_UNAVAILABLE"
    assert client.app.state.repository.active_run_ids() == []
    assert not list(client.app.state.settings.artifact_root.rglob("*.svg"))


@pytest.mark.parametrize(
    "options",
    [
        {"generation_mode": "raw_code"},
        {"generation_mode": "skill", "skill_id": "requested_skill"},
        {"gallery_mode": "auto"},
    ],
)
def test_explicit_demo_preserves_requested_engine_and_gallery(
    client: TestClient, options: dict
) -> None:
    project_id = _create_project(client)
    response = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": project_id,
            "request": {"text": "Use demonstration data", **options},
            "data_scope": {"mode": "demo"},
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLOT_CAPABILITY_UNAVAILABLE"
    assert not list(client.app.state.settings.artifact_root.rglob("*.svg"))
