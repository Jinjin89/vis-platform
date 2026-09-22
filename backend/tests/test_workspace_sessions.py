import time

from fastapi.testclient import TestClient


def project(client: TestClient) -> str:
    response = client.post("/api/v1/projects", json={"name": "Session study"})
    assert response.status_code == 201
    return response.json()["project_id"]


def start(client: TestClient, project_id: str, title: str, request_id: str) -> dict:
    return client.post(
        f"/api/v1/projects/{project_id}/workspace-sessions",
        json={"request_id": request_id, "title": title},
    )


def send(client: TestClient, project_id: str, session_id: str | None, text: str) -> dict:
    response = client.post(
        "/api/v1/assistant-turns",
        json={
            "project_id": project_id,
            "session_id": session_id,
            "request": {"text": text},
            "data_scope": {"mode": "auto"},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def completed(client: TestClient, status_path: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        snapshot = client.get(status_path).json()
        if snapshot["status"] == "completed":
            return snapshot
        time.sleep(0.01)
    raise AssertionError("The run did not complete")


def test_projects_can_be_reopened_by_id(agent_client: TestClient) -> None:
    project_id = project(agent_client)

    reopened = agent_client.get(f"/api/v1/projects/{project_id}")

    assert reopened.status_code == 200
    assert reopened.json()["name"] == "Session study"
    assert agent_client.get("/api/v1/projects/project_missing").status_code == 404


def test_a_conversation_keeps_its_turns_and_current_figure(agent_client: TestClient) -> None:
    project_id = project(agent_client)
    created = start(agent_client, project_id, "Violin study", "request-1")
    assert created.status_code == 201
    session_id = created.json()["session_id"]
    # A retried request opens the same conversation; a different title is a conflict.
    assert start(agent_client, project_id, "Violin study", "request-1").json() == created.json()
    assert start(agent_client, project_id, "Other", "request-1").status_code == 409

    greeting = send(agent_client, project_id, session_id, "how are you?")
    plot = send(
        agent_client,
        project_id,
        session_id,
        "Use demonstration data to make a violin plot of expression by treatment",
    )
    first = completed(agent_client, plot["plot_run"]["links"]["status"])
    # A later version made outside a turn (here a restore) becomes the conversation's figure.
    restored = agent_client.post(
        f"/api/v1/plots/{first['result']['plot_id']}/restore",
        json={"project_id": project_id, "source_version_id": first["result"]["version_id"]},
    )
    assert restored.status_code == 202
    latest = completed(agent_client, restored.json()["links"]["status"])

    document = agent_client.get(
        f"/api/v1/projects/{project_id}/workspace-sessions/{session_id}"
    ).json()

    assert document["title"] == "Violin study"
    assert [item["turn"]["turn_id"] for item in document["turns"]] == [
        greeting["turn_id"],
        plot["turn_id"],
    ]
    assert document["turns"][0]["turn"]["response"]["message"] == greeting["message"]
    assert document["turns"][0]["run"] is None
    assert document["turns"][0]["links"]["status"].startswith(
        f"/api/v1/assistant-turns/{greeting['turn_id']}?"
    )
    assert document["turns"][1]["run"]["result"]["version_id"] == first["result"]["version_id"]
    assert document["turns"][1]["answers"] == []
    assert document["figure"]["run_id"] == latest["run_id"]
    assert document["figure"]["result"]["version_id"] != first["result"]["version_id"]


def test_conversations_are_listed_by_latest_activity(agent_client: TestClient) -> None:
    project_id = project(agent_client)
    older = start(agent_client, project_id, "Older", "request-older").json()
    newer = start(agent_client, project_id, "Newer", "request-newer").json()
    listed = agent_client.get(f"/api/v1/projects/{project_id}/workspace-sessions").json()
    assert [item["title"] for item in listed["sessions"]] == ["Newer", "Older"]

    send(agent_client, project_id, older["session_id"], "how are you?")

    listed = agent_client.get(f"/api/v1/projects/{project_id}/workspace-sessions").json()
    assert [item["session_id"] for item in listed["sessions"]] == [
        older["session_id"],
        newer["session_id"],
    ]
    assert listed["total"] == 2
    missing = agent_client.get(f"/api/v1/projects/{project_id}/workspace-sessions/session_missing")
    assert missing.status_code == 404


def test_a_turn_cannot_join_another_projects_conversation(agent_client: TestClient) -> None:
    project_id = project(agent_client)
    other = project(agent_client)
    session_id = start(agent_client, other, "Private", "request-1").json()["session_id"]

    response = agent_client.post(
        "/api/v1/assistant-turns",
        json={
            "project_id": project_id,
            "session_id": session_id,
            "request": {"text": "how are you?"},
            "data_scope": {"mode": "auto"},
        },
    )

    assert response.status_code == 404
    opened = agent_client.get(f"/api/v1/projects/{other}/workspace-sessions/{session_id}")
    assert opened.json()["turns"] == []
