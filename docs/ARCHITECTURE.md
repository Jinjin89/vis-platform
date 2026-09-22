# Vis Platform Architecture

Status: agreed MVP design baseline
Last updated: 2026-09-21

## 1. Product goal

Vis Platform enables researchers without coding skills to create publication-ready plots from their own data or data exposed by a compatible analysis platform.

The language-first workflow is:

1. The researcher describes what they want to show.
2. The system discovers and selects relevant data.
3. It generates one strong initial plot.
4. The researcher refines it with language, dynamic controls, or both.
5. The result is saved, versioned, and exported with a reproducibility record.

The target is to acquire the required data context within one interaction whenever possible and produce the requested plot within three user interactions.

## 2. Design principles

- Produce publication-ready output by default.
- Ask only questions that tools and available context cannot resolve safely.
- Describe broadly, adjust precisely.
- Keep the figure central and conversation concise.
- Hide internal agent coordination, tool calls, and repair attempts.
- Keep raw data in the execution environment, not in model context.
- Record data selection, transformations, code, parameters, and environment details.
- Prefer immutable versions over in-place mutation.
- Keep frontend and backend independently deployable behind a versioned API.

## 3. MVP scope

The MVP includes:

- Standalone projects without authentication or user management
- Uploaded files of any format
- Analysis-platform discovery through a JSON-like contract
- Compact local data profiling
- Intent-based data selection
- Controlled multi-agent plot orchestration
- R-first plotting and data processing
- Markdown-based plot skills
- Generated R code when no skill matches
- Static plot previews
- Dynamic plot-specific controls
- Language and panel refinement
- Publication validation
- Immutable plot versions
- SVG, PDF, PNG, and TIFF export
- Reproducibility and methods records

The MVP defers:

- Authentication, authorization, roles, and multi-tenancy
- Real-time collaboration
- Mobile-first editing
- Distributed queues and multi-server scaling
- Third-party plugin marketplaces
- Comprehensive journal-specific preset libraries
- User-facing generated notebooks
- Guaranteed parsing of every uploaded format

Any file may be uploaded, but it can only be inspected or plotted after a compatible parser is available.

The initial foundation implementation uses a deterministic coordinator and marks its output as demo_only. This validates the complete application contract without representing placeholder output as a scientific result. Production plot validation begins only after isolated R execution is connected.

## 4. System overview

~~~mermaid
flowchart LR
    UI[React frontend] -->|REST API| API[FastAPI backend]
    API -->|Progress events| UI
    API --> ORCH[Plot-run coordinator]
    ORCH --> IA[Intent agent]
    ORCH --> DA[Data agent]
    ORCH --> PA[Plot agent]
    ORCH --> RA[Review agent]
    DA --> DATA[Data tools and profiles]
    PA --> SKILLS[Markdown plot skills]
    PA --> RUNNER[Isolated R workers]
    RUNNER --> STORE[Shared file storage]
    API --> DB[(SQLite)]
    API --> STORE
~~~

The frontend never accesses models, analysis-platform data, physical files, or R workers directly. All communication crosses the backend API.

## 5. Frontend

### 5.1 Technology

- React and TypeScript
- Vite
- React Router
- TanStack Query for server state
- Native EventSource for progress events
- Zod for runtime API validation
- CSS variables and a small project-specific component system

### 5.2 Main workspace

The desktop workspace uses:

- Top: project, plot version, navigation, and export
- Far left, collapsible: the saved conversations (see [Saved work and sessions](#saved-work-and-sessions))
- Left, approximately 65%: plot canvas
- Right, approximately 35%: conversation and contextual controls

The desktop workspace fits the current viewport. The figure and its controls never scroll as one long main panel; only overflowing control lists and conversation history scroll locally. On narrow screens, Figure and Conversation tabs share the available viewport instead of stacking into a long page. A planner question selects Conversation, and a completed figure selects Figure.

The left side contains the current static preview, run status, version history access, Adjust action, and collapsed data-used and data-preparation summaries.

The right side contains the initial language request, concise progress, essential questions, scientific approvals, a brief data-selection summary, language refinement, and dynamic parameters.

### 5.3 Interaction modes

- language: conversation only
- panel: dynamic controls are primary
- hybrid: conversation and controls are both available

Hybrid is the default. Plot-specific controls appear in a tabbed inspector beneath the figure. Parameters contains the dynamic form; Data shows the selected logical inputs and mappings; Results shows the caption, artifacts, and validation. Conversation remains available alongside the figure. Draggable dividers adjust conversation width and control-panel height within viewport bounds. Arrow keys adjust a focused divider; double-click or Enter restores its default. Sizes are remembered for the browser session. Narrow windows retain separate Figure / Conversation views.

The MVP uses an explicit Apply action for parameter changes. Ephemeral previews may be added later. Interpretation-sensitive changes require confirmation, and every applied change creates a version.

### Dynamic parameter and history contract

The model chooses the initial output dimensions and relevant parameter definitions together with the rendering code, using the original user request, object profiles, and current figure settings. A rendering plan must supply explicit width and height; missing dimensions trigger schema correction rather than a shared canvas default. Analysis-only plans have no figure size. The backend validates dimensions and adds the standard editable size controls using those chosen values. Illustration demos ask the size recommender once during plot planning, using the original user request and figure description. New demos have no hard-coded initial dimensions; parameter edits and history retain their recorded values. Each plot version records its control definitions and actual values. The backend validates supported IDs, types, limits, choices, and update strategies before accepting changes. The frontend renders a common form for number, choice, text, and boolean controls, honoring groups and visibility conditions. Figure width and height occupy a persistent size area on the left, or a compact strip above the settings in narrow panels. Other controls appear together in named, compact groups using the backend group definitions. Only schemas with more than 24 plot-specific controls and multiple populated groups use sub-tabs; figure size stays outside that navigation. Counting the schema rather than currently visible fields avoids rearranging navigation during edits. Settings scroll within the inspector while figure size and Apply remain accessible. A model cannot enable arbitrary parameters merely by returning a control definition; execution support belongs to the renderer or script contract.

Draft edits do not modify the saved figure. Apply submits only changed values and the base version ID, then follows the normal plot-run lifecycle. Language fine-tuning uses the same parameter validation and execution path. New versions preserve the original data/rendering context, so a visual change does not repeat endpoint questions or choose a different data source.

History is scoped to the project and plot. A collapsible strip to the left of the canvas expands into a version list that stays open while working and switching versions. Its visibility is remembered for the browser session. Browsing an old version loads its saved figure and parameters without mutating the current-version pointer. Restore creates a new immutable version. Repeated network requests use idempotency keys to prevent duplicate runs; failed renders leave existing artifacts and versions intact.

### 5.4 Frontend states

- empty
- generating
- question_required
- approval_required
- ready
- adjusting
- refining
- failed
- exporting

Each assistant request has one collapsible Activity block showing actual agent, tool, routing, question, and render steps. Running steps update in place; completed activity remains with the response. Brief decision summaries are user-visible; raw prompts and private reasoning remain outside the public activity contract. The current plot stays visible during refinement, and failures never remove the last valid version.

Empty, adjusting, and exporting are local frontend states. Backend queued or running maps to generating, awaiting_input maps to question_required, awaiting_approval maps to approval_required, and completed maps to ready.

## 6. Backend

### 6.1 Technology

- Python and FastAPI for API and orchestration
- SQLite in write-ahead logging mode
- Shared filesystem for data, scripts, previews, and exports
- Isolated R processes or containers
- renv for the locked R package environment

Redis, distributed queues, and object storage are deferred. Module boundaries remain explicit so these can be added later.

### 6.2 Modules

- Project and plot storage
- Plot-run coordinator
- Agent runtime
- Data registry
- Analysis-platform adapter
- Data profiler
- Markdown skill registry
- R capability registry
- R worker manager
- Publication validator
- Version manager
- Export manager
- Progress event store

## 7. Multi-agent orchestration

Every frontend message first enters the assistant-turn gateway. The browser requests asynchronous planning so it receives a stable turn ID before model execution and can observe live activity. The intent agent receives the latest request, up to twelve completed prior turns from the same project, the active version's saved context, and backend-owned capability information. History is bounded, excludes unfinished and current turns, and survives backend restarts. Active-version ownership is checked before any context is sent to the model.

Intent and execution readiness are separate decisions. A plot intent may reply, ask for context, or decline unavailable work instead of starting execution. The gateway preserves the model's request-specific reply for conversational routes. Executable requests carry the normalized goal and explicit mode choices into the coordinator, whose capability gate also protects direct API calls. Missing context prevents execution; unavailable capabilities never authorize a change of data source or plotting method.

The coordinator supports real-data analysis and plotting when the restricted R runtime is available, as well as explicitly requested demonstration previews. Dataset and result selection are validated before execution. Computational changes create new analysis results; display controls reuse saved results. Skills, galleries, and automated publication review remain unconnected. Missing capabilities never authorize a demonstration substitute.

~~~text
Frontend
→ assistant-turn gateway
→ intent agent
→ message response OR plot-run coordinator
~~~

The coordinator owns plot workflow state. Agents do not freely hand control to one another.

| Agent | Responsibility |
| --- | --- |
| Coordinator | State, routing, retries, questions, approvals, and version commits |
| Intent agent | Structured scientific intent and unresolved information |
| Data agent | Data discovery, selection, resolution, and profiling |
| Plot agent | Skill selection, plot planning, R generation, and repair |
| Review agent | Scientific, visual, artifact, and publication review |

Skill search, data inspection, R execution, and validation are tools rather than autonomous agents.

DeepSeek V4 Flash Vision Exp is the single model used by all agents. It handles text, tools, R-code generation, and visual review. The review agent receives a rendered PNG preview and compact plot context, not SVG or raw research data.

### Assistant execution and questions

Assistant execution has its own persistent lifecycle: running, awaiting_input, completed, failed, or cancelled. It is distinct from the plot run that a ready plan may create. SQLite stores activity, the original request, pending question groups, answers, final responses, and failures. Reconnection reads an authoritative snapshot; interruptions terminate running work while unanswered questions remain resumable.

The coordinator calls `get_current_data` and `get_current_results` before the planner. They read the project dataset registry, reusable analysis results, and recent saved figures. Data inspection expands actual object profiles through the data agent. Platform connection status is separate from local data availability; physical resolution remains backend-only.

The planner returns structured questions only for unresolved decisions. A question group may contain up to four questions with single choice, multiple choice, or free-text input. Choice labels and descriptions explain the decision; a recommendation does not submit an answer. The backend validates the complete answer group, stores it once, and resumes the original turn with the previous planner question followed by the new user answer. This ordering makes the answer the latest input rather than repeating the initial request as a new instruction. Stale or conflicting answers cannot resume a different question or create duplicate work.

Public activity contains step IDs, actor labels, status, concise summaries, timings, and tool names. Protected developer diagnostics remain separate and can be opened inside the expanded Activity block. Provider reasoning and raw model request/response payloads are excluded from public activity.

### 7.1 Run flow

Run status and execution stage are separate. Public statuses are queued, running, awaiting_input, awaiting_approval, completed, failed, and cancelled. Stages are:

~~~text
received
→ understanding_intent
→ selecting_data
→ profiling_data
→ planning_transformations
→ planning_plot
→ checking_capabilities
→ generating_code
→ running_r
→ validating_plot
→ committing_version
~~~

Stages may move backward during repair, so the ordered event stream is authoritative. The shared R executor now allows up to three automatic code-repair attempts per run, after the initial execution; analysis and rendering share this budget. Quality repair remains a planned capability with a two-attempt limit. Internal attempts do not count as user interactions.

### 7.2 Context readiness

R generation begins only when:

- Scientific intent is sufficiently clear.
- Relevant logical data objects are selected.
- Compact profiles are available.
- Variable mappings are resolved.
- Interpretation-sensitive transformations are approved.
- Skill or raw-code mode is resolved.
- R packages and runtime limits are known.
- Required outputs are defined.

Missing context routes back to the responsible agent or tool before the user is asked.

### 7.3 Developer observability

Developer traces are append-only and separate from user conversation. They record sanitized LLM request messages, final structured response content, parsed intent, concise decision summaries, routing, stage timing, tool summaries, R execution summaries, retries, and errors.

Private chain-of-thought and provider reasoning_content are never stored or returned. Trace APIs require a dedicated developer token and are disabled by default because the MVP has no user authentication.

## 8. PlotRunContext

Every run has one backend-owned structured context. Agents submit schema-validated patches to their assigned sections.

~~~text
PlotRunContext
├── run identity and state
├── request and interaction preferences
├── scientific intent
├── candidate and selected data objects
├── compact data profiles
├── selected skill or raw-code mode
├── transformations and approvals
├── plot plan and variable mappings
├── R capabilities and execution plan
├── dynamic controls
├── execution results and artifacts
├── publication review
├── questions and approvals
├── retry counters
└── provenance events
~~~

Raw datasets never appear in PlotRunContext. Profiles, scripts, images, and exports are referenced by stable IDs when large.

PlotRunContext is internal. The public plot-run snapshot is a curated contract that excludes model prompts, physical paths, raw data, internal logs, retry details, and hidden reasoning.

Refinement creates a child run from an immutable base version. Parameter changes can bypass agents when the existing script supports rerunning. Language refinement updates only affected context sections and then passes through the readiness gate.

## 9. Data architecture

The [dataset and analysis-result design](DATASETS_DESIGN.md) extends this baseline. The connected implementation, API, runtime setup, and remaining limits are documented in [DATA_WORKFLOW.md](DATA_WORKFLOW.md).

### 9.1 Identities

The system distinguishes:

- Data bundle: one uploaded or external analysis
- Data file: one physical file
- Logical object: a usable object inside a file
- Data profile: a compact local description

Frontend and agents use bundle_id, file_id, and object_id. Physical paths are visible only to the backend and R job.

### 9.2 Analysis-platform contract

Integration has two stages:

1. Discover datasets and logical objects through a semantic JSON-like contract.
2. Resolve physical data_file locations only after selection.

The discovery contract should provide stable identifiers, scientific descriptions, object types, formats, dimensions when known, capabilities, annotations, reductions, analysis results, and relationships.

Domain-specific metadata may live under extensions. A backend adapter normalizes the platform contract so the rest of Vis Platform remains provider-independent.

### 9.3 Uploaded files

Uploads accept one or many files without extension restrictions. Finalization creates a bundle and reports parser status:

- unknown
- available
- unsupported
- failed

Unsupported files remain stored and may become usable when a parser is added.

### 9.4 Compact profiles

R inspects selected data locally. Agents may receive object descriptions, dimensions, variable names and types, scientific meanings, missing-value counts, numeric summaries, low-cardinality scientific categories, group candidates, relationships, and available results.

Profiles exclude raw rows, free text, sample or patient identifiers, and other high-cardinality values.

## 10. Plot skills and gallery

Existing Markdown skills are used directly:

~~~text
plot-skills/
└── example-skill/
    ├── SKILL.md
    ├── scripts/
    ├── references/
    └── assets/
~~~

The registry discovers folders containing SKILL.md and exposes their instructions and supporting files to the plot agent.

A skill is executable plotting knowledge. A gallery entry is an optional example associated with a skill and preset.

Requests separate:

- generation_mode: auto, skill, or raw_code
- gallery_mode: off, auto, or selected
- controls_mode: language, panel, or hybrid

Skill mode may include skill_id to pin a specific skill. Selected gallery mode requires gallery_reference_id. Auto generation prefers a matching skill and permits raw R as a fallback.

When no skill matches, the plot agent may generate constrained R code following the same job contract.

## 11. R execution

The plot agent or skill produces an R script and a structured job. The R worker only executes it.

Every script implements:

~~~r
plot_main <- function(inputs, params, output_dir) {
  # Load selected data.
  # Apply recorded transformations.
  # Build and save the plot.

  list(
    artifacts = list(),
    data_used = list(),
    transformations = list(),
    calculated_statistics = list(),
    caption = "",
    methods = ""
  )
}
~~~

The job includes IDs, execution mode, skill version, script hash, resolved read-only inputs, object selectors, parameters, requested outputs, required packages, random seed, and resource limits.

The result includes status, artifacts, actual parameters, data and transformations used, calculated statistics, R warnings and errors, caption, methods, and environment versions.

Controls specify:

- rerun: execute the current script with new values
- regenerate: return to the plot agent
- confirm: require approval because interpretation may change

## 12. Execution isolation

Generated R code runs with:

- Read-only inputs
- One writable output directory
- No network access
- Restricted environment variables
- Time and memory limits
- Limited concurrency
- No access to backend configuration or unrelated projects

Packages are installed at deployment and locked with renv. Plot jobs cannot install packages.

## 13. Storage and versions

SQLite stores projects, bundles, files, objects, profiles, plots, runs, versions, artifacts, exports, and events. The shared filesystem stores large content.

Every immutable version records:

- Parent version and originating run
- User request and intent
- Data and object references
- Source fingerprints
- Data profile version
- Transformations
- Skill and skill version
- R script and hash
- Parameters
- Preview and publication artifacts
- Validation report
- R environment
- Reproducibility record

A version is committed only after execution and required validation succeed. Failed runs never replace the current version. Concurrent refinements create branches.

Platform import registers metadata and logical references first. Selected objects are materialized and retained as managed inputs. Fingerprints detect changes; cached historical inputs remain reproducible. Uncached old inputs are rejected when their source revision cannot be verified. Provider-side subset retrieval is deferred.

Successful runs are saved automatically. The MVP does not require a separate Save action after completion.

## 14. API

The base path is /api/v1.

~~~text
POST /assistant-turns
GET  /assistant-turns/{turn_id}
GET  /assistant-turns/{turn_id}/events
POST /assistant-turns/{turn_id}/answer
POST /assistant-turns/{turn_id}/cancel

POST /projects
GET  /projects
GET  /projects/{project_id}

GET  /projects/{project_id}/workspace-sessions
POST /projects/{project_id}/workspace-sessions
GET  /projects/{project_id}/workspace-sessions/{session_id}

POST /data-bundles
POST /data-bundles/{bundle_id}/files
POST /data-bundles/{bundle_id}/finalize
GET  /data-bundles/{bundle_id}

POST /plot-runs
GET  /plot-runs/{run_id}
GET  /plot-runs/{run_id}/events
POST /plot-runs/{run_id}/questions/{question_id}/answer
POST /plot-runs/{run_id}/approvals/{approval_id}
POST /plot-runs/{run_id}/cancel

POST /plots/{plot_id}/refine
POST /plots/{plot_id}/parameters
GET  /projects/{project_id}/plots/{plot_id}/versions
POST /plots/{plot_id}/restore

POST /plots/{plot_id}/exports
GET  /artifacts/{artifact_id}
~~~

Long operations return 202 Accepted and a run ID. Server-Sent Events carry progress, questions, approvals, preview readiness, completion, failure, and cancellation. Polling is the fallback.

Mutations accept idempotency keys. Refinements require a base version. Public responses exclude raw data, physical paths, hidden reasoning, and internal stack traces.

Data selection uses an explicit data_scope object. Auto scope requests intent-based discovery across project and analysis-platform data; it never means demo data. Selected scope requires one or more bundle IDs. Demo scope explicitly requests illustrative data. In assistant turns, an explicit language request for demonstration data can resolve auto scope to demo; selected bundles and pinned engines are preserved. Direct plot-run calls with unsupported capabilities return HTTP 409 and PLOT_CAPABILITY_UNAVAILABLE before creating a run. Parameter updates use a separate typed endpoint, preserve the selected version's inputs, and validate every changed value against that version's executable controls.

A preview.ready event is provisional unless its payload explicitly states otherwise. Only a completed run identifies a committed immutable version.

## 15. Publication validation

Validation has four layers:

1. Scientific preflight
2. R warnings and errors
3. Artifact and export checks
4. Visual and scientific review

Safe automatic fixes include margins, label wrapping, legend placement, minimum text size, export resolution, and accessible colors when the user did not request a palette.

Outlier removal, imputation, normalization, statistical-test changes, aggregation, endpoint selection, and switching between raw and adjusted values require an explicit request or approval.

A plot is publication-ready only when no blocking issue remains. Warnings remain visible and enter the reproducibility record.

## 16. Reliability

The backend records stage timing, tool outcomes, compact decision summaries, hashes, executed R code, R diagnostics, resource use, validation, questions, approvals, and version commits.

General logs exclude raw data, physical paths, and hidden reasoning.

Primary metrics include success rate, time to first preview, total generation time, user interaction count, retries, validation pass rate, parser failures, R failures, cache reuse, and cancellation.

## 17. Testing

Required test layers:

- Schema and contract tests
- Analysis-platform adapter tests
- Profile privacy tests
- Agent routing tests with fixed tool responses
- Context-readiness tests
- R isolation and resource-limit tests
- Publication validator tests
- API and progress-event tests
- Immutable-version tests
- End-to-end scientific scenarios

Required scenarios:

1. Clinical CSV to grouped distribution plot without questions
2. Multi-file single-cell contract to UMAP
3. Ambiguous survival endpoints producing one question
4. Raw-code mode bypassing skills and gallery
5. Missing dependency selecting an installed fallback
6. Visual parameter rerun without an agent
7. Language refinement creating a child version
8. Interpretation-sensitive change requiring approval
9. Unsupported upload retained without a parser
10. Large data profiled without exposing raw rows
11. Cancellation of active R
12. Concurrent refinements creating branches
13. Progress reconnection
14. Retry-limit enforcement
15. Invalid exports never becoming saved versions

## 18. Implementation inputs

Implementation still requires:

- A representative analysis-platform contract
- Access to the existing plot-skills folder
- The initial R package environment
- The target deployment environment and isolation capabilities

These inputs may refine adapters and deployment configuration without changing the core architecture.


### Figure export boundary

A dedicated backend exporter derives PNG (300 dpi), vector PDF, and SVG from the selected immutable version's saved SVG, rather than reexecuting analysis or generated drawing code. The version-scoped download API checks project/plot/version ownership. Conversion uses measured physical dimensions, rejects external resources, and publishes complete cached files atomically. Presentation chrome belongs to the frontend stage; new illustration SVGs use a plain canvas, and exports of historical illustration cards remove their old outer framing without mutating the original. The frontend's shared Export menu sits in the plot toolbar beside the figure title and handles format selection, download progress, keyboard interaction, and API errors. A secondary entry remains in Results.

### Canvas presentation

The frontend also provides an infinite plotting canvas at `/canvas`, alongside the existing `/workspace` interface. Nodes and positions are browser-local presentation state over existing Datasets, assistant turns, runs, and immutable versions. The versioned API adds a read-only plot source endpoint and optional typed parameter drafts on assistant turns. See [CANVAS_UI.md](CANVAS_UI.md) for the model and persistence boundary.

### Intent-driven report editing

The `/report` interface uses report content v2: ordered first- and second-level
sections, stable IDs, and typed text, figure, and table blocks. Documents,
revisions, and conversations belong to the backend. A report planner infers
operations and placement from one message; selection is an optional hint.

Atomic document edits and resumable write/plot steps execute in the backend.
Writing uses the data agent over recorded metadata and results. Plotting delegates
to the existing shared assistant and R pipeline, and figures reference shared
versions and descriptions. Version-1 pre-reports remain importable. See
[REPORT_UI.md](REPORT_UI.md) for the contract, migration, and APIs.


### Automatic R execution repair

Analysis and rendering pass runtime diagnostics back to a code-repair agent using
the configured model connection. It receives the failing code, original request,
plan, parameters, and measured object descriptions. Its typed response contains
only replacement code; the executor keeps dataset references, output names,
relationships, settings, and random seed fixed. Repairs run in the same restricted
R worker and rendering must still pass SVG validation.

A rendering failure retries only rendering against the saved analysis result.
Corrected analysis code is saved with its result provenance; corrected rendering
code is saved in the shared plot version and reused by subsequent parameter edits.
The run stays active during recovery and emits a short progress message. A shared,
persisted three-repair budget prevents loops. Cancellation interrupts model repair
and R execution. Exhaustion marks the run failed without replacing a previous plot.
The same behavior applies to Workspace, Canvas, and Report. Without a configured
model connection, execution retains its normal failure behavior. An already-failed
request is not replayed automatically; submit a new request after updating the server.


### Slides and shared figure placements

The Slides adapter reuses the report document engine for persistence and orchestration,
with a separate slide-deck import/export contract, flat slide ordering, layout frames,
and speaker notes. Explicit shared figure selections are separate from plot branch
history. Per-block bindings resolve linked placements while pinned references and
revision snapshots retain immutable versions. See [SLIDES_UI.md](SLIDES_UI.md).


### Figure compositions

A figure composition is a separate versioned document that places shared plot
versions, uploaded images, and planned slots on a publication page. Like a report,
it has its own datasets, so a figure can be built from data and a description
alone. Panels store millimetre
positions and a scale over each content's natural size; the backend resolves
geometry, reading-order labels, and page height, and composes exports from the
saved drawings without re-execution. Panels stay pinned to their versions and
report newer ones as available updates. A layout solver turns row/column arrangements
into geometry, and plots can be re-rendered at their panel size through the existing
parameter update. These placement renders never become a plot's current version.
Non-blocking checks report margins, overlaps, small text, image resolution, label
order, and unused space. A separate figure planner turns messages into edits,
additions, plot steps through the shared assistant and plot pipeline, and
arrangement trees. To build from data, it lays out the whole page as slots; the
runtime then fills them one at a time in reading order through the shared plot agent,
at each slot's size, continuing past slots that fail. It reviews remaining warnings
for at most two rounds. See [FIGURE_UI_DESIGN.md](FIGURE_UI_DESIGN.md).

### Pointing at plots

Pinpoint, a separate interface at `/pinpoint`, lets researchers mark numbered points
and areas on a plot and refer to them in a request. Marks are fractions of the saved
image and travel on the ordinary assistant turn as `plot_marks`. The backend draws
them on a PNG of the plot for both planners and, from the plotting regions the R
worker records while drawing, adds each mark's data coordinates. Requests without
marks are unchanged. See [PINPOINT_UI.md](PINPOINT_UI.md).

### Saved work and sessions

All six interfaces work in one study (project). The browser remembers it in local
storage, so a later visit reopens the same work; the frontend checks that the
backend still has it and starts a new study only when it does not.

Each interface lists its saved work in a fixed, collapsible sidebar beside the open
item: conversations in Workspace, canvases in Canvas, and reports, presentations,
or figures in the document interfaces, and plots in Pinpoint. The selected item is
part of the URL. Each
interface remembers whether its list is open. By default it opens on wide windows;
the Workspace, whose figure, controls, and conversation share the width, opens it
from 1600 px and otherwise shows a narrow strip with the list and New buttons. On
narrow screens the open list covers the work and closes after a choice.

- **Workspace conversations** are backend records. A conversation is created with
  its first message, named after it, and every assistant turn it sends carries its
  `session_id`. The model's conversation context is limited to earlier turns of the
  same conversation; turns sent outside one, such as report and figure plot steps,
  keep their own shared history. Opening a conversation rebuilds its messages,
  answered questions, activity, and figure from the saved turns and runs, and
  reconnects to a request or run that is still in progress. Its figure is the
  current version of the latest plot it made, so later parameter changes and
  restores are included. Opening the Workspace continues the latest conversation.
- **Canvases** stay browser-local presentation state, as before; a project can
  now have several, and the latest one opens by default.
- **Reports, presentations, and figures** were already separate backend documents;
  the sidebar lists them next to the open one.
