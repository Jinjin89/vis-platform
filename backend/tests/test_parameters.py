from __future__ import annotations

import time
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from vis_platform_backend.agents.intent import IntentAgentExecution, IntentAgentInput
from vis_platform_backend.app import create_app
from vis_platform_backend.config import Settings
from vis_platform_backend.contracts.intent import IntentDecision
from vis_platform_backend.contracts.research import ResearchDecision, ResearchPlan
from vis_platform_backend.domain.parameters import InvalidParameterError, resolve_parameters


def project(client: TestClient) -> str:
    return client.post("/api/v1/projects", json={"name": "Parameter study"}).json()["project_id"]


def wait(client: TestClient, accepted: dict, expected: str = "completed") -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        snapshot = client.get(accepted["links"]["status"]).json()
        if snapshot["status"] == expected:
            return snapshot
        if snapshot["status"] in {"failed", "cancelled", "awaiting_input", "awaiting_approval"}:
            raise AssertionError(snapshot)
        time.sleep(0.01)
    raise AssertionError("Run did not finish")


def create(client: TestClient, text: str = "Make a violin distribution of expression") -> dict:
    response = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": project(client),
            "request": {"text": text},
            "data_scope": {"mode": "demo"},
        },
    )
    assert response.status_code == 202
    return wait(client, response.json())


def update(client: TestClient, base: dict, changes: dict, key: str | None = None):
    return client.post(
        f"/api/v1/plots/{base['result']['plot_id']}/parameters",
        json={
            "project_id": base["project_id"],
            "base_version_id": base["result"]["version_id"],
            "changes": changes,
        },
        headers={"Idempotency-Key": key} if key else {},
    )


def history(client: TestClient, base: dict) -> dict:
    response = client.get(
        f"/api/v1/projects/{base['project_id']}/plots/{base['result']['plot_id']}/versions"
    )
    assert response.status_code == 200
    return response.json()


def values(snapshot: dict) -> dict:
    return {control["id"]: control["value"] for control in snapshot["result"]["controls"]}


@pytest.mark.parametrize(
    "text,specific",
    [
        ("Show an expression distribution", {"show_points", "show_box"}),
        ("Show a scatter relationship", {"point_size", "show_trend", "show_band"}),
        ("Compare the treatment groups", {"show_points"}),
    ],
)
def test_controls_describe_each_executable_figure(
    client: TestClient, text: str, specific: set[str]
) -> None:
    base = create(client, text)
    assert (
        set(values(base))
        == {"figure_width", "figure_height", "title", "label_size", "palette"} | specific
    )
    assert base["result"]["parameter_updates_available"] is True
    assert base["result"]["control_groups"]
    assert "No research dataset" in base["result"]["data_summary"]
    assert "render_spec" not in str(base)


def test_apply_changes_svg_and_preserves_parent_values_and_artifact(client: TestClient) -> None:
    base = create(client)
    original_svg = client.get(base["result"]["preview"]["href"]).text
    response = update(
        client,
        base,
        {
            "title": "Treatment <comparison> & expression",
            "label_size": 13,
            "show_points": False,
            "palette": "plum",
        },
    )
    assert response.status_code == 202
    changed = wait(client, response.json())
    artifact = client.get(changed["result"]["preview"]["href"]).text
    tree = ET.fromstring(artifact)
    assert tree.find(".//*[@data-role='plot-title']").text == "Treatment <comparison> & expression"
    assert tree.find(".//*[@data-layer='observations']").get("display") == "none"
    assert "<comparison>" not in artifact
    assert "#965e7c" in artifact
    assert values(changed)["label_size"] == 13
    assert values(base)["label_size"] == 11
    assert client.get(base["result"]["preview"]["href"]).text == original_svg
    versions = history(client, base)
    assert len(versions["versions"]) == 2
    assert versions["versions"][0]["parent_version_id"] == base["result"]["version_id"]
    assert versions["current_version_id"] == changed["result"]["version_id"]
    assert versions["versions"][0]["result"]["validation"]["status"] == "demo_only"


@pytest.mark.parametrize(
    "changes",
    [
        {"label_size": True},
        {"label_size": "12"},
        {"label_size": 50},
        {"label_size": 12.2},
        {"palette": "unknown"},
        {"show_points": "false"},
        {"unknown": 3},
        {"title": " "},
        {"title": "x" * 81},
        {"label_size": 11},
        {},
        {"title": None},
        {"title": {"html": "<script>"}},
    ],
)
def test_invalid_or_unchanged_parameters_never_create_versions(
    client: TestClient, changes: dict
) -> None:
    base = create(client)
    response = update(client, base, changes)
    assert response.status_code == 422
    assert len(history(client, base)["versions"]) == 1
    assert client.app.state.repository.active_run_ids() == []


def test_retries_reuse_one_run_and_conflicting_keys_are_rejected(client: TestClient) -> None:
    base = create(client)
    first = update(client, base, {"label_size": 12}, key="same-request")
    repeated = update(client, base, {"label_size": 12}, key="same-request")
    assert first.status_code == repeated.status_code == 202
    assert first.json()["run_id"] == repeated.json()["run_id"]
    wait(client, first.json())
    assert update(client, base, {"label_size": 13}, key="same-request").status_code == 409
    assert len(history(client, base)["versions"]) == 2


def test_scatter_parameters_control_real_mark_size_and_visibility(client: TestClient) -> None:
    base = create(client, "Create a scatter relationship")
    changed = wait(client, update(client, base, {"point_size": 8, "show_trend": False}).json())
    tree = ET.fromstring(client.get(changed["result"]["preview"]["href"]).text)
    observations = tree.find(".//*[@data-layer='observations']")
    assert {node.get("r") for node in observations} == {"8"}
    assert tree.find(".//*[@data-layer='trend']").get("display") == "none"
    assert tree.find(".//*[@data-layer='band']").get("display") == "none"
    band = next(
        control for control in changed["result"]["controls"] if control["id"] == "show_band"
    )
    assert band["visible_when"] == {"control_id": "show_trend", "equals": True}


def test_render_failure_does_not_replace_the_saved_version(client: TestClient, monkeypatch) -> None:
    base = create(client)

    def fail(*args, **kwargs):
        raise RuntimeError("Injected rendering failure")

    monkeypatch.setattr("vis_platform_backend.services.plot_runs.parameterize_demo", fail)
    failed = wait(client, update(client, base, {"label_size": 12}).json(), expected="failed")
    assert failed["result"] is None
    versions = history(client, base)
    assert len(versions["versions"]) == 1
    assert versions["current_version_id"] == base["result"]["version_id"]
    assert client.get(base["result"]["preview"]["href"]).status_code == 200


def test_versions_from_other_projects_or_plots_cannot_be_mutated(client: TestClient) -> None:
    base = create(client)
    other = create(client)
    response = client.post(
        f"/api/v1/plots/{other['result']['plot_id']}/parameters",
        json={
            "project_id": other["project_id"],
            "base_version_id": base["result"]["version_id"],
            "changes": {"label_size": 12},
        },
    )
    assert response.status_code == 404
    response = client.get(
        f"/api/v1/projects/{other['project_id']}/plots/{base['result']['plot_id']}/versions"
    )
    assert response.status_code == 404
    response = client.post(
        f"/api/v1/plots/{base['result']['plot_id']}/restore",
        json={
            "project_id": other["project_id"],
            "source_version_id": base["result"]["version_id"],
        },
    )
    assert response.status_code == 404


def test_restore_after_restart_reuses_saved_parameters_without_changing_old_versions(
    tmp_path: Path,
) -> None:
    settings = Settings(
        database_path=tmp_path / "study.sqlite3",
        artifact_root=tmp_path / "artifacts",
        fake_step_delay_seconds=0.001,
    )
    with TestClient(create_app(settings)) as client:
        base = create(client)
        original = client.get(base["result"]["preview"]["href"]).text
        changed = wait(client, update(client, base, {"title": "Updated title"}).json())
    with TestClient(create_app(settings)) as client:
        response = client.post(
            f"/api/v1/plots/{base['result']['plot_id']}/restore",
            json={
                "project_id": base["project_id"],
                "source_version_id": base["result"]["version_id"],
            },
            headers={"Idempotency-Key": "restore-request"},
        )
        assert response.status_code == 202
        restored = wait(client, response.json())
        assert values(restored) == values(base)
        assert client.get(restored["result"]["preview"]["href"]).text == original
        versions = history(client, base)
        assert len(versions["versions"]) == 3
        assert versions["current_version_id"] == restored["result"]["version_id"]
        assert versions["versions"][1]["result"]["title"] == changed["result"]["title"]


class ParameterAgent:
    def __init__(self, reuse_data: bool = True) -> None:
        self.input: IntentAgentInput | None = None
        self.reuse_data = reuse_data

    async def analyze(self, input: IntentAgentInput) -> IntentAgentExecution:
        self.input = input
        return IntentAgentExecution(
            decision=IntentDecision.model_validate(
                {
                    "kind": "plot_refine",
                    "subtype": "visual",
                    "normalized_request": "Increase label size",
                    "confidence": 0.99,
                    "next_action": "refine_context",
                    "refinement": {
                        "reuse_data": self.reuse_data,
                        "changes": [
                            {"target": "label_size", "value": 13, "change_class": "visual"}
                        ],
                    },
                    "decision_summary": "Use the supported label size parameter.",
                }
            ),
            turns=(),
        )


@pytest.mark.parametrize("reuse_data", [True, False])
def test_language_changes_use_the_same_parameter_contract(tmp_path: Path, reuse_data: bool) -> None:
    settings = Settings(
        database_path=tmp_path / "agent.sqlite3",
        artifact_root=tmp_path / "artifacts",
        fake_step_delay_seconds=0.001,
    )
    agent = ParameterAgent(reuse_data)
    with TestClient(create_app(settings, intent_agent=agent)) as client:
        base = create(client)
        response = client.post(
            "/api/v1/assistant-turns",
            json={
                "project_id": base["project_id"],
                "base_version_id": base["result"]["version_id"],
                "data_scope": {"mode": "auto"},
                "request": {"text": "Make labels larger"},
            },
        )
        assert response.status_code == 200
        assert agent.input.active_plot.parameter_updates_available is True
        assert {control["id"] for control in agent.input.active_plot.controls} == set(values(base))
        turn = response.json()
        if reuse_data:
            assert turn["outcome"] == "plot_run"
            updated = wait(client, turn["plot_run"])
            assert values(updated)["label_size"] == 13
        else:
            assert turn["outcome"] == "message"
            assert len(history(client, base)["versions"]) == 1


def off_scale_plan() -> dict:
    return {
        "title": "Expression",
        "description": "Expression by group.",
        "reuse_result_id": "result_1",
        "render_code": "plot(results$summary$value, col=adjustcolor(1, params$alpha))",
        "figure_size": {"width": 6, "height": 4},
        "controls": [
            {"type": "text", "id": "title", "label": "Title", "value": "Expression"},
            # 0.75 lies within the bounds but the 0.1 steps from 0.1 cannot reach it.
            {
                "type": "number",
                "id": "alpha",
                "label": "Point opacity",
                "value": 0.75,
                "minimum": 0.1,
                "maximum": 1,
                "step": 0.1,
            },
        ],
    }


def test_new_plans_start_every_number_control_on_its_scale() -> None:
    with pytest.raises(ValidationError, match="“alpha” starts at 0.75"):
        ResearchDecision.model_validate(
            {"action": "execute", "summary": "Plot", "plan": off_scale_plan()}
        )
    on_scale = off_scale_plan()
    on_scale["controls"][1]["value"] = 0.8
    ResearchDecision.model_validate({"action": "execute", "summary": "Plot", "plan": on_scale})


def test_saved_off_scale_values_stay_readable_and_only_changes_are_checked() -> None:
    # Versions planned before the rule was enforced still load and accept edits.
    plan = ResearchPlan.model_validate(off_scale_plan())
    values = resolve_parameters(plan.controls, {"title": "Treated"})
    assert values == {"title": "Treated", "alpha": 0.75}
    assert resolve_parameters(plan.controls, {"alpha": 0.8})["alpha"] == 0.8
    # Sending the saved value as a change is checked like any new value.
    with pytest.raises(InvalidParameterError, match="Point opacity"):
        resolve_parameters(plan.controls, {"alpha": 0.75}, require_change=False)
