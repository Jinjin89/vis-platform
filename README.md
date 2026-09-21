# Vis Platform

A language-first platform that helps researchers create publication-ready plots without coding.

## Architecture

The agreed MVP architecture is documented in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

DeepSeek configuration is documented in [docs/LLM_CONFIGURATION.md](docs/LLM_CONFIGURATION.md).

The implemented plot reference image workflow is documented in [docs/REFERENCE_IMAGES.md](docs/REFERENCE_IMAGES.md), with further review plans in [docs/PLOT_REFERENCES_DESIGN.md](docs/PLOT_REFERENCES_DESIGN.md).

## Interfaces

Choose **Workspace**, **Canvas**, **Report**, or **Slides** in the header. The [Report interface](docs/REPORT_UI.md) organizes figures, tables, and prose into sections and subsections. Its single assistant input chooses whether to plot, write, or reorganize the report and where to place the changes. Report content v2 supports targeted edits, saved history, and legacy pre-report import.

The infinite canvas supports dataset-to-plot branches, immutable refinements, and the existing parameter controls. All four interfaces use the same plot agent and figure records. See [the canvas guide](docs/CANVAS_UI.md) for navigation, persistence, and code export.

The [Slides MVP](docs/SLIDES_UI.md) adds an online presentation editor with shared figures, layouts, speaker notes, presentation mode, and JSON/PDF export. Linked figures update across Report and Slides; pinned versions remain unchanged.

A fifth interface, **Figure**, will compose saved plots and images into publication figures on an A4 or journal-width page. Its [design](docs/FIGURE_UI_DESIGN.md) is agreed; the backend contract, API, and page exports are implemented, and the editor and figure agent follow.

## Current implementation

The foundation slice is runnable and includes:

- Separate frontend and backend applications
- Separate Data and Add image actions, with reference image paste, file selection, and drag-and-drop
- Image-aware intent and R planning, persistent reference thumbnails, and rendering refinement that reuses saved analysis
- A viewport-sized workspace with a fitted figure, compact grouped controls, and a fixed message composer
- Inline, collapsible agent activity backed by actual context checks, planning, routing, and rendering events
- Structured planner questions with choices, custom answers, cancellation, and recovery after refresh or server restart
- A DeepSeek assistant with project-scoped conversation history and saved figure context
- Structured routing for conversation, plot creation, refinement, data questions, plot questions, workspace actions, unclear requests, and blocked requests
- Token-protected developer traces with sanitized LLM turns and routing decisions
- Versioned OpenAPI and typed progress-event contracts
- Persistent projects, plot runs, events, artifacts, and immutable plot versions
- Progress streaming with replay, bounded reconnects, and polling fallback
- Essential-question and scientific-approval flows, including free-text answers
- Execution readiness checks that preserve the requested data source and plotting method
- A workspace with draggable conversation and figure-control dividers, keyboard resizing, and session-saved panel sizes
- Live stage progress, cancellation, preview recovery, and last-good-figure retention
- Versioned dataset collections from related uploads or a configured analysis-platform provider
- Locally measured profiles and LLM-assisted descriptions, with source-independent object tools
- Restricted R analysis, reusable tables/scalars/models, result-only requests, and real SVG figures
- Selectable single-cell and spatial transcriptomic demo collections in the analysis-platform picker
- Standard output width/height controls and an independent figure stage with fit, zoom, and pan
- PNG (300 dpi), vector PDF, and SVG figure exports, plus analysis-output downloads
- Request-aware demonstration figures for survival, distributions, relationships, and group comparisons
- A Parameters / Data / Results panel with a fixed figure-size area and compact, visible parameter groups; sub-tabs appear only for unusually large forms
- Validated parameter updates through the form or language, with real SVG changes and immutable versions
- A collapsible history strip left of the figure with saved parameters, version previews, and restoration as a new version
- Idempotent parameter and restore requests
- Persistent scientific question and approval history, including the selected survival endpoint
- Protected developer diagnostics kept outside the primary research workflow
- Request-specific answers grounded in available capabilities, without keyword-based reply replacement
- Explicit demonstration requests and persistent data-source disclosure

The assistant separates intent from execution readiness. It discovers project datasets independently of saved figures, resolves versioned objects, and can analyze real inputs through the restricted R worker. Analyses create reusable results; they never add datasets. Figure controls reuse saved results, and history retains exact input references. Demonstrations still require an explicit request and never substitute for missing research data.

See [the data workflow](docs/DATA_WORKFLOW.md) for setup, APIs, supported formats, and current limits. The analysis-platform adapter implements a documented source contract; its live connection requires the platform's URL and response mapping. Plot skills, automated scientific/publication review, and the full publication export pipeline remain separate work.

The interface keeps unsupported gallery actions hidden.
Older figure versions show their recorded parameters as read-only when execution support is unavailable.
Every action visible in the primary workspace is connected to the current API.

## Getting started

Requirements:

- Python 3.12 and uv
- Node.js 24.15 LTS
- R with jsonlite and the restricted worker for real-data execution; see [runtime setup](docs/DATA_WORKFLOW.md#restricted-r-runtime)

Start the backend:

~~~sh
cd backend
uv sync
uv run uvicorn vis_platform_backend.app:app \
  --host 0.0.0.0 \
  --port 18080 \
  --env-file .env
~~~

Start the frontend in another terminal:

~~~sh
cd frontend
npm install
npm run dev
~~~

From another computer on the same network, open http://SERVER_IP:5173. The frontend proxies API requests to the backend on port 18080.

Both development servers are exposed to the local network. Because the MVP has no authentication, do not expose ports 5173 or 18080 to an untrusted or public network.

## Repository structure

- backend/: API, orchestration, persistence, and execution boundaries
- frontend/: browser application and API client
- contracts/: generated, versioned API contracts
- docs/: architecture and design documentation

## Contributing

Before making changes, read [`AGENTS.md`](AGENTS.md) for the repository's working guidelines.
