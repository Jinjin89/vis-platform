# Vis Platform backend

The backend exposes the versioned HTTP API, owns plot-run state, and coordinates dataset tools, agents, reusable analysis results, and a restricted R worker.

## Development

~~~sh
uv sync
uv run uvicorn vis_platform_backend.app:app \
  --host 0.0.0.0 \
  --port 18080 \
  --env-file .env
~~~

The API listens on all network interfaces at port 18080. Its OpenAPI document is available at http://SERVER_IP:18080/docs.

The dataset registry and upload APIs work independently of figures. Real-data planning and execution use the configured model and the restricted R runtime. Provision the runtime as described in [DATA_WORKFLOW.md](../docs/DATA_WORKFLOW.md); the repository-local installation is detected automatically. Unsupported execution is rejected instead of running code without isolation or substituting demonstration data.

The assistant can inspect datasets, create figures, or compute results without a figure. Results retain their input revisions, code, parameters, artifacts, and environment. Visual parameter updates rerender saved results; restoring history copies the saved figure and its references. Source descriptions and content access are separated by the common provider interface.

Set the DeepSeek API key in .env. See [../docs/LLM_CONFIGURATION.md](../docs/LLM_CONFIGURATION.md) for every supported setting.


## Plot reference images

Project-scoped image uploads, content, thumbnails, and deletion are exposed under `/api/v1/projects/{project_id}/plot-reference-images`. The assistant receives `request.reference_image_ids`, sends prepared pixels to intent and R planning, and saves reference metadata with resulting versions. Reference uploads are separate from datasets. Visual rendering regeneration reuses the current analysis result. Upload and assistant request retries accept `Idempotency-Key`.

See [REFERENCE_IMAGES.md](../docs/REFERENCE_IMAGES.md) for formats, limits, ownership, persistence, API examples, and remaining review work.

## Figure parameters and versions

For model-generated figures, the planner must choose explicit output width and height alongside the plot-specific controls. It uses the original user request, data profiles, and existing figure settings; no universal canvas size is applied. Omitted dimensions go through the normal bounded schema-correction retry. New illustration demos also request an initial size recommendation from the configured LLM during figure planning. Their renderer uses that recommendation to populate the width/height controls and save the output dimensions. A missing or failed recommendation fails the new run instead of substituting a constant. Parameter edits and history reuse saved dimensions without another model call.

Each new result includes `controls`, `control_groups`, `parameter_schema_version`, and `parameter_updates_available`. Controls carry typed values, labels, ranges or choices, groups, optional visibility conditions, and their execution strategy. The renderer publishes only controls it actually implements; the frontend does not decide which parameters are supported.

- `POST /api/v1/plots/{plot_id}/parameters`: pass `project_id`, `base_version_id`, and a typed `changes` object. Unknown IDs, invalid values, unsupported strategies, and no-op changes are rejected before creating a run.
- `GET /api/v1/projects/{project_id}/plots/{plot_id}/versions`: return saved versions, their parent IDs, result snapshots, and the current version ID.
- `POST /api/v1/plots/{plot_id}/restore`: pass `project_id` and `source_version_id` to create a new version from saved rendering settings.

Parameter and restore requests accept `Idempotency-Key`. Retrying the same request with the same key returns the existing run; using the key for different changes returns a conflict. Version ownership is checked against both the project and plot.

Versions preserve their renderer, actual parameters, and input/result references. Demo versions also retain their original request and selected endpoint. Failed runs never replace the saved version. Older snapshots without rendering context remain viewable but cannot be adjusted or restored through these endpoints.


## Live planning

`POST /api/v1/assistant-turns` accepts `Prefer: respond-async`. It returns HTTP 202 with the turn ID and status, event, and cancellation links. Without the header, the existing synchronous response is retained.

The public state and event endpoints require `project_id`. Activity remains available when developer traces are disabled and includes only user-facing summaries of real operations. Server-sent events use `assistant.updated` with a monotonic revision and an authoritative snapshot. Protected raw diagnostics still use the existing developer token.

Questions use `outcome: "question"` and a stable interaction ID. Submit all selected choice IDs and/or custom text to `/assistant-turns/{turn_id}/answer` with the project and interaction IDs. The same question/answer cannot be submitted with conflicting content. On resume, the model receives its previous question and the new answer in conversation order. Answers and pending questions persist across restarts; cancelled or interrupted requests cannot silently continue.

See [ANALYSIS_PLATFORM_CONTRACT.md](../docs/ANALYSIS_PLATFORM_CONTRACT.md) for the source adapter and [DATA_WORKFLOW.md](../docs/DATA_WORKFLOW.md) for ingestion, revision, and result APIs.


## Figure export

The Export menu downloads PNG (300 dpi), PDF, or SVG for the selected saved figure version. All formats use the saved SVG and its recorded physical dimensions; export does not rerun the model, analysis, or R drawing code. PDF keeps vector graphics and PNG includes resolution metadata. PNG and PDF conversion uses [CairoSVG](https://cairosvg.org/documentation/); install the system Cairo library (`libcairo2` on Debian/Ubuntu) alongside the Python dependencies with `uv sync`.

The version-scoped endpoint is `GET /api/v1/projects/{project_id}/plots/{plot_id}/versions/{version_id}/exports/{format}`, where format is `png`, `pdf`, or `svg`. It returns a binary attachment with the matching media type and filename. Ownership is checked against project, plot, and version. Exports are cached by figure content and written atomically. The scientific drawing, labels, and demo-data disclosure are retained; UI framing is excluded. Exports of older illustration templates remove their decorative outer card without rewriting saved artifacts.
