import time

import pytest
from fastapi.testclient import TestClient


def _create_project(client: TestClient, name: str) -> str:
    response = client.post("/api/v1/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()["project_id"]


def _wait_for_completed_run(client: TestClient, status_url: str) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        response = client.get(status_url)
        assert response.status_code == 200
        snapshot = response.json()
        if snapshot["status"] == "completed":
            return snapshot
        time.sleep(0.01)
    raise AssertionError("Plot run did not complete")


@pytest.mark.parametrize("endpoint", ["/api/v1/plot-runs", "/api/v1/assistant-turns"])
def test_plot_version_cannot_be_used_from_another_project(
    client: TestClient, endpoint: str
) -> None:
    source_project_id = _create_project(client, "Source project")
    other_project_id = _create_project(client, "Other project")
    first_run = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": source_project_id,
            "data_scope": {"mode": "demo"},
            "request": {"text": "Create the source plot"},
        },
    )
    assert first_run.status_code == 202
    first_result = _wait_for_completed_run(client, first_run.json()["links"]["status"])["result"]

    response = client.post(
        endpoint,
        json={
            "project_id": other_project_id,
            "data_scope": {"mode": "demo"},
            "base_version_id": first_result["version_id"],
            "request": {"text": "Refine a plot from the other project"},
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
