# API contracts

Backend Pydantic models are the source of truth for the public API.

Generate the checked-in OpenAPI and run-event schemas with:

~~~sh
cd backend
uv run python scripts/export_contracts.py
~~~

Frontend clients and runtime validators must be generated from, or tested against, these versioned artifacts.

## Plot reference images

The image API and exact request/response examples are documented in [REFERENCE_IMAGES.md](../docs/REFERENCE_IMAGES.md). `PlotRequest.reference_image_ids` accepts up to three unique project-owned IDs; absent/null permits refinement inheritance, and `[]` clears reference guidance. Empty text requires explicit images. `AssistantTurnSnapshot.reference_images` restores submitted thumbnails, while `PlotResultSummary.reference_images` records the immutable version's effective references. Image bytes are never part of these JSON contracts.

`RefinementIntent.execution_strategy` distinguishes existing parameter updates, rendering regeneration, and analysis replanning. Existing saved requests default to parameter updates. Rendering regeneration for visual changes must reuse the base figure's analysis result. Uploads and assistant submissions accept `Idempotency-Key` and reject conflicting reuse with HTTP 409.

## Assistant routing and data selection

`IntentDecision.kind` describes the user's goal. `next_action` describes what can happen now: plot creation and refinement intents may return `reply`, `ask_user`, or `reject` without creating a run. Message routes include a nonempty `user_reply`.

`data_scope.mode` accepts `auto`, `selected`, or `demo`. `auto` refers to project-data discovery, and `selected` requires bundle IDs. `demo` is an explicit request for illustrative data. Assistant decisions may express an explicit language selection in `mode_requests.data`; this does not replace selected bundles or pinned plotting engines.

The current renderer supports demo data with automatic generation and no gallery. Direct requests for unavailable capabilities, including unsupported freeform regeneration, receive HTTP 409 (`PLOT_CAPABILITY_UNAVAILABLE`) without creating a run. The assistant gateway reports those limitations as a message. A previous demo never makes later research requests implicit demos.


## Dynamic figure controls

`PlotResultSummary.controls` is a discriminated union of `number`, `choice`, `text`, and `boolean` controls. Every control includes its stable ID, current value, label, group, and update strategy. Optional `visible_when` references another control and its required value. `control_groups` supplies group labels; the frontend renders them without figure-family-specific forms.

`ResearchPlan.figure_size` must provide both width and height whenever `render_code` is present. Dimensions are in inches (2–30, in 0.01 increments) and have no implicit defaults. `figure_size` may be null for analysis-only plans. The backend exposes the chosen geometry as standard `figure_width` and `figure_height` controls; plot-specific controls and their defaults come from the plan. Missing or partial geometry is rejected before execution. Previously saved r-v1 versions without geometry replay at their historical 9 × 6 inch device size. New illustration demos obtain their initial dimensions from the model during planning; saved demo versions reuse their recorded geometry and parameters. Only historical demo-v1 specs without any recorded dimensions retain the old 10 × 5.83 inch fallback.

`parameter_updates_available` explicitly reports execution support. Legacy results default to false. `parameter_schema_version` currently equals `1.0`. Data and result tabs consume `data_summary`, logical `data_used` references, `title`, `caption`, artifacts, and validation metadata; no internal renderer context or storage paths are public.

A parameter mutation uses the selected immutable version:

~~~json
{
  "schema_version": "1.0",
  "project_id": "project_example",
  "base_version_id": "version_example",
  "changes": {
    "label_size": 13,
    "show_points": false
  }
}
~~~

Submit it to `POST /api/v1/plots/{plot_id}/parameters` with an optional `Idempotency-Key`. The response is the existing `PlotRunAccepted` contract; progress, cancellation, completion, and errors use the existing run APIs. Invalid parameter values return HTTP 422 with `INVALID_PLOT_PARAMETERS`; unsupported execution returns HTTP 409. Only completed, validated runs become versions.

History is available at `GET /api/v1/projects/{project_id}/plots/{plot_id}/versions`. Selecting a returned run for viewing does not change the current saved version. `POST /api/v1/plots/{plot_id}/restore` accepts `project_id` and `source_version_id`, creates a new version, and also supports idempotency keys.


## Assistant activity and questions

Clients can request asynchronous execution with `Prefer: respond-async` on the existing assistant-turn POST. HTTP 202 returns `AssistantTurnAccepted`; the returned links identify scoped status, events, and cancellation endpoints. The synchronous route remains supported.

`AssistantTurnSnapshot` includes the original request text, lifecycle status, revision, current activity, any pending question group, the response or a safe error, and an associated plot-run status when applicable. `assistant.updated` events carry snapshots. `Last-Event-ID` identifies the last revision; clients also support snapshot polling for reconnection.

`AgentActivity` includes a stable step ID, actor, kind, label, status, concise summary, optional tool name and duration, and timestamp. Repeated updates to a step replace its displayed state. This contract has no raw model input/output fields, secrets, file paths, or private reasoning.

`AssistantTurnResponse.outcome` now also supports `question`. Its `PlannerQuestions` object contains an interaction ID and one to four questions. Questions support single choice, multiple choice, and text; options can include descriptions and recommendations. The client submits `PlannerAnswerRequest` to `/assistant-turns/{turn_id}/answer`. Answer IDs, selection counts, free-text permissions, project ownership, and the pending interaction are validated. An exact retry returns the existing request; changed or stale answers are rejected.


## Figure downloads

`GET /api/v1/projects/{project_id}/plots/{plot_id}/versions/{version_id}/exports/{format}` returns the selected version as an attachment. `format` is `png`, `pdf`, or `svg`; corresponding media types are `image/png`, `application/pdf`, and `image/svg+xml`. PNG uses 300 dpi and the recorded width/height; PDF and SVG preserve vector content and physical size. Exports use the saved drawing and do not create a new version or analysis result. Missing or mismatched project/plot/version combinations return 404; unsupported formats and conversion failures return 422. Frontend downloads handle errors before saving a file.
