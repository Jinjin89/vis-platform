from __future__ import annotations

import base64
import io
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from test_agent_context import RecordingAgent, plot, reply, settings
from test_datasets import RUNTIME, ProfileOnlyAgent, research_plan, upload_collection, wait_run
from test_planner_runtime import QuestionAgent

from vis_platform_backend.agents.deepseek_intent import DeepSeekIntentAgent
from vis_platform_backend.agents.intent import IntentAgentInput
from vis_platform_backend.agents.messages import ModelContext, ModelImage
from vis_platform_backend.agents.structured import structured_response
from vis_platform_backend.app import create_app
from vis_platform_backend.config import LlmSettings, Settings
from vis_platform_backend.contracts.research import DataAnswer, ResearchDecision


def png(color="purple", *, size=(32, 24)):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def project(client):
    return client.post("/api/v1/projects", json={"name": "Image study"}).json()["project_id"]


def upload(client, owner, *, content=None, key=None, name="reference.png"):
    response = client.post(
        f"/api/v1/projects/{owner}/plot-reference-images",
        params={"name": name},
        content=png() if content is None else content,
        headers={
            "Content-Type": "application/octet-stream",
            **({"Idempotency-Key": key} if key else {}),
        },
    )
    return response


def request(owner, image_ids=None, text="Make a plot like this.", **options):
    return {
        "project_id": owner,
        "request": {"text": text, "reference_image_ids": image_ids},
        "data_scope": {"mode": "auto"},
        **options,
    }


def await_turn(client, path):
    for _ in range(100):
        snapshot = client.get(path).json()
        if snapshot["status"] != "running":
            return snapshot
        time.sleep(0.02)
    raise AssertionError("Assistant did not finish")


def test_upload_is_a_reference_not_a_dataset_and_has_safe_previews(client):
    owner = project(client)
    original = Image.new("RGB", (40, 20), "red")
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "Private image metadata"
    source = io.BytesIO()
    original.save(source, format="JPEG", exif=exif)
    result = upload(client, owner, content=source.getvalue(), name="image.png")
    assert result.status_code == 201, result.text
    image = result.json()
    assert (image["width"], image["height"]) == (20, 40)
    assert image["media_type"] == "image/png"
    assert "storage_path" not in result.text
    preview = client.get(image["links"]["content"])
    assert preview.headers["x-content-type-options"] == "nosniff"
    decoded = Image.open(io.BytesIO(preview.content))
    assert not decoded.getexif()
    assert "Private image metadata" not in repr(decoded.info)
    assert client.get(image["links"]["thumbnail"]).status_code == 200
    assert client.get(f"/api/v1/projects/{owner}/datasets").json()["datasets"] == []


def test_upload_retry_deletion_and_project_isolation(client):
    owner, other = project(client), project(client)
    first = upload(client, owner, key="upload-one").json()
    again = upload(client, owner, key="upload-one").json()
    assert first["image_id"] == again["image_id"]
    conflict = upload(client, owner, key="upload-one", content=png("blue"))
    assert conflict.status_code == 409
    foreign = first["links"]["content"].replace(owner, other)
    assert client.get(foreign).status_code == 404
    base = first["links"]["content"].removesuffix("/content")
    assert client.delete(base.replace(owner, other)).status_code == 404
    assert client.delete(base).status_code == 204
    assert client.get(first["links"]["content"]).status_code == 404


@pytest.mark.parametrize(
    "content", [b"sample,value\ns1,7", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b""]
)
def test_non_images_never_enter_the_reference_pipeline(client, content):
    response = upload(client, project(client), content=content)
    assert response.status_code in (415, 422)


def test_image_limits_and_animation_are_checked_before_use(client, monkeypatch):
    owner = project(client)
    from vis_platform_backend.services import reference_images

    monkeypatch.setattr(reference_images, "PIXEL_LIMIT", 100)
    assert upload(client, owner).status_code == 413
    monkeypatch.setattr(reference_images, "PIXEL_LIMIT", 25_000_000)
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(
        output,
        format="WEBP",
        save_all=True,
        append_images=[Image.new("RGB", (8, 8), "blue")],
        duration=100,
        loop=0,
    )
    assert upload(client, owner, content=output.getvalue()).status_code == 415
    from vis_platform_backend.api.routes import reference_images as routes

    monkeypatch.setattr(routes, "UPLOAD_LIMIT", 10)
    assert upload(client, owner).status_code == 413


def test_foreign_and_duplicate_references_are_rejected_before_model_calls(tmp_path):
    agent = RecordingAgent([reply()])
    with TestClient(create_app(settings(tmp_path), intent_agent=agent)) as client:
        owner, other = project(client), project(client)
        image = upload(client, owner).json()
        assert (
            client.post(
                "/api/v1/assistant-turns", json=request(other, [image["image_id"]])
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/v1/assistant-turns", json=request(owner, [image["image_id"]] * 2)
            ).status_code
            == 422
        )
        assert (
            client.post("/api/v1/assistant-turns", json=request(owner, [], text=" ")).status_code
            == 422
        )
        assert not agent.inputs


def test_image_only_turns_persist_pixels_and_pin_images(tmp_path):
    agent = RecordingAgent([reply(), reply()])
    config = settings(tmp_path)
    with TestClient(create_app(config, intent_agent=agent)) as client:
        owner = project(client)
        image = upload(client, owner).json()
        response = client.post(
            "/api/v1/assistant-turns", json=request(owner, [image["image_id"]], text="")
        )
        assert response.status_code == 200, response.text
        turn = response.json()
        assert (
            agent.inputs[-1].reference_images[0].data
            == client.get(image["links"]["content"]).content
        )
        assert "using available data" in agent.inputs[-1].text
        state = client.get(turn["links"]["status"]).json()
        assert state["request_text"] == ""
        assert state["reference_images"] == [image]
        assert "base64" not in json.dumps(state)
        assert client.delete(image["links"]["content"].removesuffix("/content")).status_code == 409
    with TestClient(create_app(config, intent_agent=agent)) as client:
        assert client.get(turn["links"]["status"]).json()["reference_images"] == [image]
        client.post("/api/v1/assistant-turns", json=request(owner, text="Use the earlier image."))
        assert agent.inputs[-1].reference_images[0].image_id == image["image_id"]


def test_pending_questions_keep_images_after_restart(tmp_path):
    agent = QuestionAgent(delay=0)
    config = settings(tmp_path)
    with TestClient(create_app(config, intent_agent=agent)) as client:
        owner = project(client)
        image = upload(client, owner).json()
        first = client.post(
            "/api/v1/assistant-turns", json=request(owner, [image["image_id"]])
        ).json()
        assert first["outcome"] == "question"
    with TestClient(create_app(config, intent_agent=agent)) as client:
        accepted = client.post(
            f"/api/v1/assistant-turns/{first['turn_id']}/answer",
            json={
                "project_id": owner,
                "interaction_id": first["question"]["interaction_id"],
                "answers": [{"question_id": "focus", "choice_ids": ["distribution"]}],
            },
        )
        assert accepted.status_code == 202, accepted.text
        assert await_turn(client, accepted.json()["links"]["status"])["status"] == "completed"
        assert agent.inputs[-1].reference_images[0].image_id == image["image_id"]
        assert agent.inputs[-1].clarification_answers


@pytest.mark.asyncio
async def test_intent_retries_keep_pixels_and_traces_redact_them():
    payloads = []
    data = png()

    def handler(req):
        payload = json.loads(req.content)
        payloads.append(payload)
        content = "{}" if len(payloads) == 1 else json.dumps(reply())
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    agent = DeepSeekIntentAgent(
        LlmSettings(api_key="test-key"), transport=httpx.MockTransport(handler)
    )
    result = await agent.analyze(
        IntentAgentInput(
            text="Use these colors.",
            has_active_plot=False,
            generation_mode="auto",
            gallery_mode="off",
            controls_mode="hybrid",
            reference_images=(ModelImage("ref_one", data),),
        )
    )
    encoded = base64.b64encode(data).decode()
    for payload in payloads:
        content = payload["messages"][1]["content"]
        assert content[-1]["image_url"]["url"].endswith(encoded)
        assert payload["messages"][1]["role"] == "user"
    assert len(payloads) == 2
    assert encoded not in repr(result.turns)
    assert "image redacted" in repr(result.turns)


@pytest.mark.asyncio
async def test_structured_generation_receives_images_outside_json_context(monkeypatch):
    payloads = []
    original_client = httpx.AsyncClient

    def handler(req):
        payloads.append(json.loads(req.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"message":"Ready"}'}}]}
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    context = ModelContext({"request": "Match the layout"}, images=(ModelImage("ref_one", png()),))
    answer = await structured_response(
        LlmSettings(api_key="key"), DataAnswer, "Describe the plot.", context
    )
    assert answer.message == "Ready"
    parts = payloads[0]["messages"][1]["content"]
    assert json.loads(parts[0]["text"])["context"] == {"request": "Match the layout"}
    assert parts[-1]["type"] == "image_url"


def test_message_idempotency_keeps_one_turn_across_retries_and_restart(tmp_path):
    agent = RecordingAgent([reply()])
    config = settings(tmp_path)
    headers = {"Prefer": "respond-async", "Idempotency-Key": "same-message"}
    with TestClient(create_app(config, intent_agent=agent)) as client:
        owner = project(client)
        image = upload(client, owner).json()
        body = request(owner, [image["image_id"]])
        first = client.post("/api/v1/assistant-turns", json=body, headers=headers)
        retry = client.post("/api/v1/assistant-turns", json=body, headers=headers)
        assert first.status_code == retry.status_code == 202
        assert first.json()["turn_id"] == retry.json()["turn_id"]
        assert await_turn(client, first.json()["links"]["status"])["status"] == "completed"
        changed = client.post(
            "/api/v1/assistant-turns",
            json=request(owner, [image["image_id"]], text="A different message"),
            headers=headers,
        )
        assert changed.status_code == 409
        assert len(agent.inputs) == 1
    with TestClient(create_app(config, intent_agent=agent)) as client:
        retry = client.post("/api/v1/assistant-turns", json=body, headers=headers)
        assert retry.json()["turn_id"] == first.json()["turn_id"]
        assert await_turn(client, retry.json()["links"]["status"])["status"] == "completed"
        assert len(agent.inputs) == 1


class ReferenceDataAgent(ProfileOnlyAgent):
    def __init__(self):
        self.contexts = []

    async def plan(self, context):
        self.contexts.append(context)
        if context.get("render_only"):
            plan = {
                "title": "Restyled comparison",
                "description": "Same means with a horizontal layout.",
                "figure_size": context["active_figure"]["figure_size"],
                "reuse_result_id": context["active_figure"]["results"][0]["result_id"],
                "render_code": "barplot(results$comparison$value, horiz=TRUE, col='steelblue')",
                "controls": [],
            }
        else:
            plan = research_plan(context["objects"])
        return ResearchDecision.model_validate(
            {"action": "execute", "summary": "Use the reference.", "plan": plan}
        )


@pytest.mark.skipif(
    not (RUNTIME / "usr/lib/R").is_dir(), reason="Restricted R runtime is unavailable"
)
def test_real_reference_creation_refinement_and_restore_preserve_data(tmp_path):
    refinement = {
        "kind": "plot_refine",
        "subtype": "visual",
        "normalized_request": "Match the new image layout.",
        "confidence": 1,
        "next_action": "refine_context",
        "decision_summary": "Restyle the same results.",
        "refinement": {
            "reuse_data": True,
            "execution_strategy": "regenerate_render",
            "changes": [{"target": "layout", "value": "horizontal", "change_class": "visual"}],
        },
    }
    agent = RecordingAgent([plot(), refinement])
    data_agent = ReferenceDataAgent()
    config = Settings(
        database_path=tmp_path / "data.sqlite",
        artifact_root=tmp_path / "artifacts",
        r_home=RUNTIME / "usr/lib/R",
        r_sandbox=RUNTIME / "vis-r-sandbox",
    )
    with TestClient(create_app(config, intent_agent=agent, data_agent=data_agent)) as client:
        owner = project(client)
        dataset = upload_collection(client, owner)
        first = upload(client, owner).json()
        response = client.post(
            "/api/v1/assistant-turns",
            json=request(
                owner,
                [first["image_id"]],
                data_scope={"mode": "selected", "bundle_ids": [dataset["dataset_id"]]},
            ),
        )
        assert response.status_code == 200, response.text
        assert response.json()["outcome"] == "plot_run", response.text
        created = wait_run(client, response.json()["plot_run"])
        assert created["status"] == "completed", created
        base = created["result"]
        assert base["reference_images"] == [first]
        assert data_agent.contexts[0].images[0].image_id == first["image_id"]
        result_id = base["analysis_results"][0]["result_id"]
        second = upload(client, owner, content=png("blue")).json()
        response = client.post(
            "/api/v1/assistant-turns",
            json=request(owner, [second["image_id"]], base_version_id=base["version_id"]),
        )
        assert response.status_code == 200, response.text
        assert response.json()["outcome"] == "plot_run", response.text
        changed = wait_run(client, response.json()["plot_run"])
        assert changed["status"] == "completed", changed
        assert changed["result"]["reference_images"] == [second]
        assert changed["result"]["analysis_results"][0]["result_id"] == result_id
        assert data_agent.contexts[-1]["render_only"] is True
        assert data_agent.contexts[-1]["active_figure"]["render_code"]
        assert len(client.get(f"/api/v1/projects/{owner}/datasets").json()["datasets"]) == 1
        restored = client.post(
            f"/api/v1/plots/{base['plot_id']}/restore",
            json={
                "project_id": owner,
                "source_version_id": base["version_id"],
            },
        )
        saved = wait_run(client, restored.json())
        assert saved["status"] == "completed"
        assert saved["result"]["reference_images"] == [first]
        assert saved["result"]["analysis_results"][0]["result_id"] == result_id
