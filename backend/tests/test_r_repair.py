from __future__ import annotations

import asyncio
import copy
import time

import pytest
from fastapi.testclient import TestClient
from test_datasets import ProfileOnlyAgent, project, research_plan, upload_collection, wait_run
from test_report_messages import config

from vis_platform_backend.agents.r_repair import RCodeRepair
from vis_platform_backend.app import create_app


class RepairAgent:
    def __init__(self, codes):
        self.codes = iter(codes)
        self.contexts = []

    async def repair(self, context):
        self.contexts.append(copy.deepcopy(context))
        return RCodeRepair(code=next(self.codes))


def submit(client, owner, dataset, plan):
    response = client.post(
        "/api/v1/plot-runs",
        json={
            "project_id": owner,
            "request": {"text": "Compare treatment group means"},
            "data_scope": {"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
            "research_plan": plan,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


@pytest.mark.parametrize("phase", ["analysis", "render"])
def test_real_r_error_repairs_and_saves_corrected_code(tmp_path, phase):
    agent = RepairAgent([])
    with TestClient(
        create_app(config(tmp_path), data_agent=ProfileOnlyAgent(), r_repair_agent=agent)
    ) as client:
        owner = project(client)
        dataset = upload_collection(client, owner)
        plan = research_plan(dataset["objects"])
        corrected = plan[phase + "_code"]
        agent.codes = iter([corrected])
        plan[phase + "_code"] = 'stop("broken generated code")'
        completed = wait_run(client, submit(client, owner, dataset, plan))
        assert completed["status"] == "completed", completed
        assert len(agent.contexts) == 1
        context = agent.contexts[0]
        assert "broken generated code" in context["diagnostic"]
        assert context["execution"]["mode"] == ("analyze" if phase == "analysis" else "render")
        assert context["objects"]
        assert context["execution"]["code"] == 'stop("broken generated code")'
        assert client.get(f"/api/v1/projects/{owner}/analysis-results").json()["total"] == 1
        result = completed["result"]
        assert client.get(result["preview"]["href"]).status_code == 200
        stored = client.app.state.repository.get_run(completed["run_id"])
        assert stored["interaction"]["render_spec"]["plan"][phase + "_code"] == corrected
        assert stored["interaction"]["r_repair_attempts"] == 1
        if phase == "analysis":
            script = next(
                a for a in result["analysis_results"][0]["artifacts"] if a["role"] == "script"
            )
            assert client.get(script["href"]).text == corrected
        else:
            # A later parameter edit must reuse the repaired renderer and original analysis.
            changed = client.post(
                f"/api/v1/plots/{result['plot_id']}/parameters",
                json={
                    "project_id": owner,
                    "base_version_id": result["version_id"],
                    "changes": {"color": "steelblue"},
                },
            )
            assert changed.status_code == 202, changed.text
            updated = wait_run(client, changed.json())
            assert updated["status"] == "completed", updated
            assert (
                updated["result"]["analysis_results"][0]["result_id"]
                == (result["analysis_results"][0]["result_id"])
            )
            assert len(agent.contexts) == 1


def test_repair_budget_is_shared_by_analysis_and_render(tmp_path):
    agent = RepairAgent([])
    with TestClient(
        create_app(config(tmp_path), data_agent=ProfileOnlyAgent(), r_repair_agent=agent)
    ) as client:
        owner = project(client)
        dataset = upload_collection(client, owner)
        plan = research_plan(dataset["objects"])
        agent.codes = iter([plan["analysis_code"], 'stop("still bad")', 'stop("last error")'])
        plan["analysis_code"] = 'stop("analysis failed")'
        plan["render_code"] = 'stop("render failed")'
        failed = wait_run(client, submit(client, owner, dataset, plan))
        assert failed["status"] == "failed"
        assert len(agent.contexts) == 3
        assert [c["execution"]["mode"] for c in agent.contexts] == ["analyze", "render", "render"]
        assert [c["attempt"] for c in agent.contexts] == [1, 2, 3]
        assert "still bad" in agent.contexts[2]["diagnostic"]
        assert failed["result"] is None
        stored = client.app.state.repository.get_run(failed["run_id"])
        assert stored["interaction"]["r_repair_attempts"] == 3
        diagnostics = stored["interaction"]["r_execution_errors"]
        assert len(diagnostics) == 4
        assert diagnostics[-1]["diagnostic"] == "last error"
        assert "r_execution_errors" not in failed
        assert client.get(f"/api/v1/projects/{owner}/analysis-results").json()["total"] == 1


def test_failed_refinement_preserves_original_version(tmp_path):
    agent = RepairAgent(['stop("cannot repair")'] * 3)
    with TestClient(
        create_app(config(tmp_path), data_agent=ProfileOnlyAgent(), r_repair_agent=agent)
    ) as client:
        owner = project(client)
        dataset = upload_collection(client, owner)
        plan = research_plan(dataset["objects"])
        plan["render_code"] = (
            'if(params$color == "steelblue") stop("bad refinement");' + plan["render_code"]
        )
        original = wait_run(client, submit(client, owner, dataset, plan))["result"]
        preview = client.get(original["preview"]["href"]).content
        response = client.post(
            f"/api/v1/plots/{original['plot_id']}/parameters",
            json={
                "project_id": owner,
                "base_version_id": original["version_id"],
                "changes": {"color": "steelblue"},
            },
        )
        assert response.status_code == 202, response.text
        failed = wait_run(client, response.json())
        assert failed["status"] == "failed"
        assert len(agent.contexts) == 3
        versions = client.get(
            f"/api/v1/projects/{owner}/plots/{original['plot_id']}/versions"
        ).json()
        assert len(versions["versions"]) == 1
        assert client.get(original["preview"]["href"]).content == preview


class WaitingRepair:
    def __init__(self):
        self.started = False
        self.cancelled = False

    async def repair(self, context):
        self.started = True
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def test_code_repair_contract_cannot_change_inputs_or_parameters():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RCodeRepair.model_validate({"code": "plot(1)", "inputs": [], "params": {"color": "red"}})


def test_cancelling_during_repair_does_not_publish_a_plot(tmp_path):
    agent = WaitingRepair()
    with TestClient(
        create_app(config(tmp_path), data_agent=ProfileOnlyAgent(), r_repair_agent=agent)
    ) as client:
        owner = project(client)
        dataset = upload_collection(client, owner)
        plan = research_plan(dataset["objects"])
        plan["render_code"] = 'stop("render failed")'
        accepted = submit(client, owner, dataset, plan)
        for _ in range(200):
            if agent.started:
                break
            time.sleep(0.025)
        assert agent.started
        response = client.post(f"/api/v1/plot-runs/{accepted['run_id']}/cancel")
        assert response.status_code == 200, response.text
        stopped = wait_run(client, accepted)
        assert stopped["status"] == "cancelled"
        assert stopped["result"] is None
        for _ in range(100):
            if agent.cancelled:
                break
            time.sleep(0.01)
        assert agent.cancelled


def test_report_message_recovers_failed_render_and_receives_shared_figure(tmp_path):
    from browser_server import BrowserDataAgent, BrowserIntentAgent
    from test_report_messages import QueuePlanner, create, send, wait

    class BrokenRenderAgent(BrowserDataAgent):
        async def plan(self, context):
            decision = await super().plan(context)
            if decision.plan is not None:
                decision.plan.render_code = 'stop("report rendering error")'
            return decision

    repair = RepairAgent([])
    planner = QueuePlanner(
        [
            {
                "action": "execute",
                "message": "Create a comparison figure.",
                "steps": [
                    {
                        "kind": "plot",
                        "section_id": "results",
                        "output_id": "comparison",
                        "instructions": "Compare treatment group means",
                    }
                ],
            }
        ]
    )
    with TestClient(
        create_app(
            config(tmp_path),
            data_agent=BrokenRenderAgent(),
            intent_agent=BrowserIntentAgent(),
            report_planner=planner,
            r_repair_agent=repair,
        )
    ) as client:
        dataset = upload_collection(client, project(client))
        repair.codes = iter([research_plan(dataset["objects"])["render_code"]])
        report = create(client, dataset)
        send(client, report, "Plot the treatment comparison")
        completed, state = wait(client, report)
        assert state["status"] == "completed", state
        assert len(repair.contexts) == 1
        block = completed["content"]["sections"][0]["blocks"][0]
        assert block["type"] == "figure" and block["caption"] == ""
        shared = completed["figures"][block["version_id"]]
        assert client.get(shared["preview"]["href"]).status_code == 200
        assert (
            client.get(f"/api/v1/projects/{dataset['project_id']}/analysis-results").json()["total"]
            == 1
        )
