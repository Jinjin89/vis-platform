from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from vis_platform_backend.app import create_app
from vis_platform_backend.config import Settings


def create_project(client: TestClient) -> str:
    response = client.post(
        "/api/v1/projects",
        json={"schema_version": "1.0", "name": "Test project"},
    )
    assert response.status_code == 201
    return response.json()["project_id"]


def wait_for_completed_run(client: TestClient, status_url: str) -> dict:
    deadline = time.monotonic() + 2
    snapshot = None
    while time.monotonic() < deadline:
        response = client.get(status_url)
        assert response.status_code == 200
        snapshot = response.json()
        if snapshot["status"] == "completed":
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"Plot run did not complete; last snapshot: {snapshot}")


def wait_for_status(client: TestClient, status_url: str, status: str) -> dict:
    deadline = time.monotonic() + 2
    snapshot = None
    while time.monotonic() < deadline:
        snapshot = client.get(status_url).json()
        if snapshot["status"] == status:
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"Plot run did not reach {status}; last snapshot: {snapshot}")


def test_health_reports_r_capability(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["api_version"] == "v1"
    assert isinstance(payload["r_runtime_available"], bool)
    assert not payload["developer_trace_enabled"]
    assert payload["llm"] == {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash-vision-exp",
        "configured": False,
        "thinking_enabled": True,
        "reasoning_effort": "high",
    }


def test_plot_run_completes_with_public_result(client: TestClient) -> None:
    project_id = create_project(client)
    response = client.post(
        "/api/v1/plot-runs",
        json={
            "schema_version": "1.0",
            "project_id": project_id,
            "data_scope": {"mode": "demo"},
            "request": {"text": "Compare treatment and control"},
        },
    )

    assert response.status_code == 202
    accepted = response.json()
    assert accepted["status"] == "queued"
    assert accepted["stage"] == "received"
    assert accepted["links"]["status"].endswith(accepted["run_id"])

    snapshot = wait_for_completed_run(client, accepted["links"]["status"])
    assert snapshot["status"] == "completed"
    assert snapshot["result"]["validation"]["status"] == "demo_only"
    assert {control["id"] for control in snapshot["result"]["controls"]} == {
        "figure_width",
        "figure_height",
        "title",
        "label_size",
        "palette",
        "show_points",
    }
    assert snapshot["result"]["parameter_updates_available"]
    assert "storage_path" not in str(snapshot)

    artifact_response = client.get(snapshot["result"]["preview"]["href"])
    assert artifact_response.status_code == 200
    assert artifact_response.headers["content-type"].startswith("image/svg+xml")
    assert artifact_response.headers["content-disposition"].startswith("inline")
    assert artifact_response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in artifact_response.headers["content-security-policy"]
    assert client.app.state.repository.version_exists(snapshot["result"]["version_id"])


def test_event_stream_is_ordered_and_replayable(client: TestClient) -> None:
    project_id = create_project(client)
    accepted = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": project_id,
            "data_scope": {"mode": "demo"},
            "request": {"text": "Create a publication plot"},
        },
    ).json()
    wait_for_completed_run(client, accepted["links"]["status"])

    response = client.get(accepted["links"]["events"])
    assert response.status_code == 200
    event_lines = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    sequences = [event["sequence"] for event in event_lines]
    assert sequences == sorted(sequences)
    assert event_lines[0]["type"] == "run.started"
    assert event_lines[-1]["type"] == "run.completed"

    replay = client.get(
        accepted["links"]["events"],
        headers={"Last-Event-ID": event_lines[-2]["event_id"]},
    )
    replay_events = [
        json.loads(line.removeprefix("data: "))
        for line in replay.text.splitlines()
        if line.startswith("data: ")
    ]
    assert [event["type"] for event in replay_events] == ["run.completed"]


def test_request_contract_rejects_invalid_conditional_options(client: TestClient) -> None:
    project_id = create_project(client)
    response = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": project_id,
            "data_scope": {"mode": "demo"},
            "request": {
                "text": "Make a plot",
                "gallery_mode": "selected",
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_question_answer_resumes_the_same_run(client: TestClient) -> None:
    project_id = create_project(client)
    accepted = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": project_id,
            "data_scope": {"mode": "demo"},
            "request": {"text": "Show survival differences"},
        },
    ).json()
    waiting = wait_for_status(client, accepted["links"]["status"], "awaiting_input")
    question = waiting["pending_question"]

    resumed = client.post(
        f"/api/v1/plot-runs/{accepted['run_id']}/questions/{question['question_id']}/answer",
        json={"choice_id": "overall_survival"},
    )

    assert resumed.status_code == 202
    assert resumed.json()["run_id"] == accepted["run_id"]
    completed = wait_for_completed_run(client, accepted["links"]["status"])
    assert completed["pending_question"] is None


def test_scientific_approval_resumes_after_a_decision(client: TestClient) -> None:
    project_id = create_project(client)
    accepted = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": project_id,
            "data_scope": {"mode": "demo"},
            "request": {"text": "Remove outliers and compare groups"},
        },
    ).json()
    waiting = wait_for_status(client, accepted["links"]["status"], "awaiting_approval")
    approval = waiting["pending_approval"]

    resumed = client.post(
        f"/api/v1/plot-runs/{accepted['run_id']}/approvals/{approval['approval_id']}",
        json={"decision": "reject"},
    )

    assert resumed.status_code == 202
    completed = wait_for_completed_run(client, accepted["links"]["status"])
    assert completed["pending_approval"] is None


def test_language_mode_omits_dynamic_controls(client: TestClient) -> None:
    project_id = create_project(client)
    accepted = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": project_id,
            "data_scope": {"mode": "demo"},
            "request": {
                "text": "Create a language-only plot",
                "controls_mode": "language",
            },
        },
    ).json()

    completed = wait_for_completed_run(client, accepted["links"]["status"])
    assert completed["result"]["controls_mode"] == "language"
    assert completed["result"]["controls"] == []


def test_unsupported_refinement_preserves_the_committed_version(client: TestClient) -> None:
    project_id = create_project(client)
    first = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": project_id,
            "request": {"text": "Create the first plot"},
            "data_scope": {"mode": "demo"},
        },
    ).json()
    first_result = wait_for_completed_run(client, first["links"]["status"])["result"]
    preview = client.get(first_result["preview"]["href"]).text

    response = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": project_id,
            "base_version_id": first_result["version_id"],
            "request": {"text": "Move the legend below the plot"},
            "data_scope": {"mode": "demo"},
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLOT_CAPABILITY_UNAVAILABLE"
    assert client.get(first["links"]["status"]).json()["result"] == first_result
    assert client.get(first_result["preview"]["href"]).text == preview
    assert client.app.state.repository.active_run_ids() == []


def test_cancellation_is_terminal(slow_client: TestClient) -> None:
    project_id = create_project(slow_client)
    accepted = slow_client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": project_id,
            "data_scope": {"mode": "demo"},
            "request": {"text": "Create a slow plot"},
        },
    ).json()

    cancelled = slow_client.post(accepted["links"]["cancel"])
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    time.sleep(0.15)
    assert slow_client.get(accepted["links"]["status"]).json()["status"] == "cancelled"


def test_shutdown_marks_active_runs_as_interrupted(tmp_path) -> None:
    settings = Settings(
        database_path=tmp_path / "restart.sqlite3",
        artifact_root=tmp_path / "restart-artifacts",
        fake_step_delay_seconds=1,
    )
    with TestClient(create_app(settings)) as first_client:
        project_id = create_project(first_client)
        accepted = first_client.post(
            "/api/v1/plot-runs",
            json={
                "project_id": project_id,
                "data_scope": {"mode": "demo"},
                "request": {"text": "Create an interrupted plot"},
            },
        ).json()

    with TestClient(create_app(settings)) as restarted_client:
        snapshot = restarted_client.get(accepted["links"]["status"]).json()

    assert snapshot["status"] == "failed"
    assert snapshot["failure"]["code"] == "RUN_INTERRUPTED"


def test_missing_event_stream_returns_the_public_404(client: TestClient) -> None:
    response = client.get("/api/v1/plot-runs/run_missing/events")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_openapi_documents_public_errors_and_event_stream(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    create_responses = document["paths"]["/api/v1/plot-runs"]["post"]["responses"]
    validation_schema = create_responses["422"]["content"]["application/json"]["schema"]
    event_content = document["paths"]["/api/v1/plot-runs/{run_id}/events"]["get"]["responses"][
        "200"
    ]["content"]

    assert validation_schema["$ref"].endswith("/ApiErrorEnvelope")
    assert "text/event-stream" in event_content


def test_artifact_delivery_cannot_escape_storage_root(client: TestClient, tmp_path) -> None:
    project_id = create_project(client)
    accepted = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": project_id,
            "data_scope": {"mode": "demo"},
            "request": {"text": "Create a plot"},
        },
    ).json()
    wait_for_completed_run(client, accepted["links"]["status"])
    outside_file = tmp_path / "outside.svg"
    outside_file.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    client.app.state.repository.create_artifact(
        artifact_id="artifact_outside",
        run_id=accepted["run_id"],
        media_type="image/svg+xml",
        filename="outside.svg",
        storage_path=outside_file,
    )

    response = client.get("/api/v1/artifacts/artifact_outside")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_unknown_run_has_stable_error_contract(client: TestClient) -> None:
    response = client.get("/api/v1/plot-runs/run_missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
