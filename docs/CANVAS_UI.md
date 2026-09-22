# Infinite plotting canvas

The existing **Workspace** and the new **Canvas** are available from the header.
The routes are `/workspace` and `/canvas`; the default entry remains Workspace.
Both interfaces use the same project and dataset APIs. Their layouts and selections
are independent.

## Using the canvas

1. Open **Canvas**, then **Data**. Upload a dataset or select an existing collection.
2. Select its Data card and describe a plot in the composer.
3. A connected Plot card appears immediately. Its status follows planning and R
   execution, and the image appears after the run completes.
4. Select any completed Plot card to create a refinement. Select the Data card
   again to start another independent branch.
5. Click a card to open its preview on the right. Dataset previews show object
   descriptions, dimensions, columns, and available profile information.
6. Use the existing Parameters / Data / Results panel to inspect a completed plot.
   Edits stay in that node's draft until **Create refinement** is pressed. The
   composer can submit natural-language instructions and parameter drafts together.
   Reset discards only the parameter draft. Changing selection preserves drafts.
7. Use **Export** for PNG, PDF, or SVG. **R code → Export .R** downloads the selected
   immutable version's complete plotting function and recorded parameters.

Drag a card to reposition it. Drag empty space, use the hand tool, or scroll to pan.
Ctrl/Cmd + scroll and touch pinch zoom around the pointer. The toolbar provides
zoom buttons and **Fit**. Keyboard controls are F to fit, +/- to zoom, arrow keys
to pan, and Escape to close the preview. A focused card can be moved with arrow
keys. **Outline** provides an accessible list for finding off-screen nodes.

## Node and execution model

A Data node wraps the existing Dataset contract; it has a canvas ID, short label,
title, position, Dataset value, and compact summary. Plot nodes record their own
ID, label, position, source Data node and dataset reference, optional parent Plot
node ID, creation prompt, parameter snapshot, execution status, run/version
references, complete saved R source, and preview artifact.

Edges are derived from each Plot node's immutable source or parent relationship.
They describe creation history and cannot be manually rewired. A refinement
always creates a new node and backend version. Parent parameters, code, and images
remain intact. Independent branches can run concurrently.

Each active node polls its own assistant and plot-run state. Questions and
scientific approvals appear in that node's right panel; they resume the same
request. Errors remain on the failed node while successful branches stay visible.
Interrupted polling exposes a reconnect action. Reusing a failed request's
instructions returns them to the source node's draft for a new submission.
Requests carry stable idempotency keys for recovery after navigation or refresh.

A project can have several canvases. The **Canvases** sidebar lists them, most
recently edited first, with **New canvas** to start another; the open canvas is
the `id` search parameter, and the latest one opens by default. Each canvas's
layout, nodes, source snapshots, selections, and drafts are stored in browser local
storage, keyed by the project and canvas. The project is remembered in local
storage shared with the other interfaces, so a later visit reopens the same
canvases. A canvas saved before canvases were listed becomes the project's first.
Reloading or switching interfaces resumes recorded requests. Canvas layouts are
local to this browser; they are not synchronized to another browser and are not
reconstructed from Workspace figure history. Clearing browser storage clears the
local canvases. Dataset records and committed plot versions remain in backend
storage.

## Small API additions

All business logic and R execution remain in the backend. No new graph database,
execution engine, or dataset class was introduced.

### Saved plotting source

`GET /api/v1/projects/{project_id}/plots/{plot_id}/versions/{version_id}/source`

Returns the version-scoped `PlotSource` contract:

- `code`: complete R plotting function with recorded parameters, geometry, seed,
  and demonstration-data labeling where applicable.
- `render_code`: the exact saved generated plotting body.
- `parameters`: the committed parameter snapshot.
- `input_objects`: logical source object revision references.
- `result_bindings`: named saved analysis object references required by the plot.
- `message`: execution context or an explanation when the version has no R source.

The exported `plot_main(results, output_file = "plot.svg")` function expects the
saved analysis objects as a named R list. Its dependencies must be installed in
the target R environment. It never executes a parent Plot node. Within the app,
the existing restricted R runner resolves saved objects and renders each version
independently. Legacy illustrative SVG figures that did not run R return null
code; the UI explains this.

The endpoint validates project, plot, and version ownership. Responses contain
logical references and code, never backend storage paths.

### Parameter drafts with natural language

`POST /api/v1/assistant-turns` accepts an optional `parameter_changes` map.
Nonempty drafts require `base_version_id` and are validated against that version's
supported controls before planning. Drafts are included in planner context.
Explicit panel values take precedence over values inferred from language.

For a parameter refinement, the map is merged into the existing typed parameter
update. For a regenerated rendering plan, drafts are revalidated against the new
controls and applied before execution. Unsupported or incompatible values produce
an error instead of being silently dropped. Both paths create one new version.
Requests without drafts retain their existing behavior.

## Verification

- Frontend model tests cover independent branches, immutable parameter snapshots,
  collision-free placement, project-isolated recovery, and zoom anchoring.
- Browser tests use real uploads, persistence, and restricted R execution to cover
  branching, combined language/draft refinements, code downloads, navigation,
  dragging, zoom, questions after refresh, failed rendering, and phone layout.
- Backend regression tests cover typed draft validation and precedence, immutable
  parents, idempotency, source ownership, and saved-analysis reuse.
