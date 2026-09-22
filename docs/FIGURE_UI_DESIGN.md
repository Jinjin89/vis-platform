# Figure composer design

Status: agreed design; Phases 1–5 implemented (backend foundation, editor, fitting and checks, figure agent, building from data)
Last updated: 2026-09-21

The fifth interface, **Figure**, builds one publication figure: typically a full A4
page, or an A4-width panel whose height follows its content. Like Report and Slides,
it stands on its own: a figure can start from data and a description, from saved
plots and uploaded images, or from both. Panels are created and refined by the
existing shared plot agent. A figure agent plans the composition, and the user can adjust the result
directly, like moving and resizing objects in an illustration editor. Every change,
by agent or by hand, is a validated edit of one versioned JSON document.

## 1. Decisions

| Topic | Decision |
| --- | --- |
| Structure | A figure is its own document type with its own storage and revisions. It is not a Report or Slides document. It shares plot versions and uploaded images by reference, and it uses the same plot agent. Report and Slides may later embed a whole figure as one block. |
| Plot updates | Panels are pinned to an immutable plot version. When a newer version of that plot exists, the panel reports an available update. The user can apply or ignore it. Figure edits never publish shared figure selections. |
| Minimum plot size | `FigureSize` accepts 1–30 in in every interface, so small panels render at their true size. |
| Page presets | A4 full page (210 × 297 mm), A4 width with automatic height, journal widths of 89, 120, and 183 mm with automatic height, and custom. Presets are frontend choices; the backend validates page dimensions. |
| Starting point | A figure is standalone. It has its own datasets and can be built from data and a description, without saved plots. |
| Build flow | Slots first. The assistant lays out the whole page as labelled slots, then fills them one at a time with the shared plot agent, each at its slot size. A slot that fails stays on the page with its error and can be retried. |

A figure and a slide deck have different content. A figure has a page, panels
labelled A, B, C, and a legend with one entry per panel. A slide deck has ordered
slides with elements and notes. A slide can show panels 1a and 1b by referencing
the same plot versions; the two documents never share placement or text.

## 2. Content contract

The public contract is `FigureCompositionContent` (schema
`contracts/figure-composition-v1.schema.json`). All lengths are millimetres,
measured from the top-left corner of the page.

~~~json
{
  "schema_version": "1.0",
  "title": "Figure 2",
  "page": { "width_mm": 210, "height_mm": 297, "height_mode": "auto", "margin_mm": 5 },
  "labels": { "case": "upper", "size_pt": 10, "bold": true, "font_family": "Arial" },
  "panels": [
    {
      "id": "umap",
      "content": { "type": "plot", "version_id": "version_123" },
      "x_mm": 5, "y_mm": 5, "scale": 1,
      "label": null, "show_label": true, "locked": false
    },
    {
      "id": "micrograph",
      "content": { "type": "image", "image_id": "ref_456" },
      "x_mm": 110, "y_mm": 5, "scale": 0.4
    }
  ],
  "legend": {
    "title": "Cell populations in treated samples.",
    "entries": { "umap": "UMAP of all cells coloured by cluster." }
  }
}
~~~

### Geometry

- **Natural size.** A plot's natural size is its version's recorded `figure_size`.
  Older versions without one use their saved SVG dimensions. An uploaded image's
  natural size is its pixel size at 300 dpi.
- **Scale.** A panel's displayed size is its natural size multiplied by `scale`
  (default 1, meaning the content appears at the size it was rendered). The stored
  panel has a position and scale only; width and height are derived, so a panel
  can never disagree with its content's aspect ratio.
- **Changing shape.** A proportional resize changes `scale`. Changing a plot's
  aspect ratio requires rendering the plot at the new size (Phase 3), which keeps
  fonts at their true size.
- **Page height.** `height_mode: "fixed"` uses `height_mm`. `"auto"` treats
  `height_mm` as a maximum and ends the page one margin below the lowest panel.
- **Bounds.** Every panel must lie within the page width and the page's height
  limit. Overlap is allowed, because insets are legitimate. Margin and spacing
  problems are reported by checks rather than rejected.
- **Drawing order.** The `panels` array is the drawing order; later panels are
  drawn on top.

### Labels and legend

- Panels with `show_label` receive labels in reading order: panels are grouped
  into rows when a panel starts above the middle of the row's shortest panel, and
  each row is read left to right.
- `label: null` means automatic. A custom label overrides automatic labelling for
  that panel, and automatic labels skip letters already used by custom labels.
  Custom labels must be unique.
- Labels are drawn at the panel's top-left corner in the figure's label style.
- The legend is manuscript text, not part of the exported image. Entries are keyed
  by panel ID, so moving a panel relabels its legend entry automatically. Legend
  keys must refer to existing panels.

### Panel content and updates

- `plot` content references one immutable plot version owned by the project.
- `image` content references an uploaded project image. The figure retains
  referenced images so they are not cleaned up.
- The newest version of a plot is its explicitly shared selection when one exists,
  and otherwise the plot's current version. When that differs from the panel's
  version and from `ignored_version_id`, the document response lists it under
  `updates`. Applying an update replaces the version through a normal edit;
  ignoring it records `ignored_version_id`.

## 3. Operations and revisions

Every committed change creates a revision with a short summary. Edits carry the
revision they were based on, and a stale base revision is rejected with a
conflict. Repeating the same request ID returns the original result.

Operations are applied atomically, up to 50 per request:

| Operation | Purpose |
| --- | --- |
| `set_title` | Rename the figure. |
| `set_page` | Change page size, height mode, or margin. |
| `set_label_style` | Change label case, size, weight, or font. |
| `set_min_font` | Change the smallest printed text size the checks accept. |
| `add_panel` | Add a panel at an optional drawing-order position. |
| `replace_panel` | Replace a panel's content, label, position, scale, or lock state. |
| `move_panel` | Change a panel's drawing order. |
| `remove_panel` | Remove a panel and its legend entry. |
| `set_panel_geometry` | Move and scale several panels at once (drag, align, arrange). |
| `set_legend` | Replace the legend title and entries. |

A drag or resize in the editor becomes one `set_panel_geometry` operation. An
agent's arrangement is converted to concrete positions before it is saved, so every
revision records exact geometry.

## 4. Rendering and export

The backend composes one page SVG:

1. A white page of the resolved size, in millimetre units.
2. Each panel in drawing order: plot SVGs are nested at their position and scale,
   and images are embedded as PNG data.
3. Panel labels.

Plot SVGs are validated before composition. Each panel's internal IDs, such as the
clip paths R writes, are prefixed so identical IDs from different panels cannot
collide. The same exporter used for single plots converts the page to SVG, vector
PDF, 300 dpi PNG, or 300 dpi LZW TIFF. Outputs are cached by content, so repeated
exports are immediate. Exports never create plot versions.

## 5. API

The base path is `/api/v1/projects/{project_id}/figure-compositions`.

~~~text
GET  /                            list figures (newest first, 30 per page)
POST /                            create or import (request_id + content)
GET  /{composition_id}            document with resolved geometry and references
PUT  /{composition_id}            save full content (base_revision)
POST /{composition_id}/operations apply operations (request_id + base_revision)
GET  /{composition_id}/history    revision summaries
GET  /{composition_id}/revisions/{revision}   content of one revision
GET  /{composition_id}/content    JSON export
GET  /{composition_id}/exports/{format}       svg | pdf | png | tiff
~~~

The document response adds resolved information that the frontend should not
recompute:

- the resolved page height
- per-panel label, frame (x, y, width, height), and natural size
- the plot results and image records referenced by panels
- available updates

Responses never include storage paths. Ownership of every referenced plot version
and image is checked against the project.

## 6. Figure agent (Phase 4)

The figure conversation uses its own planner, separate from the report planner.
The planner decides what the figure should contain and how it is organised. Code
computes the geometry, and the shared plot agent makes every plot.

~~~text
message → figure planner → reply | question | steps
  edit     → figure operations (title, page, labels, legend, locking, removal, …)
  add      → place a saved plot version or uploaded image as a new panel
  plot     → shared plot agent: create a plot for a new panel, or refine a panel's plot
  arrange  → layout solver → exact geometry, then renders at panel size
  review   → remaining warnings return to the planner (at most two rounds)
→ one or more figure revisions, each recorded in history
~~~

- **Planner context:**
  - the page, label style, and minimum text size
  - each panel's label, frame, natural size, plot title, description, data
    summary, whether it can be re-rendered, and its legend entry
  - the current checks, and saved plots not yet in the figure
  - project datasets, the recent conversation, and the selected panels as a hint
- **Plot steps:**
  - They start an assistant turn with project data discovery (`data_scope: auto`),
    so questions, approvals, and data selection work exactly as in Workspace.
  - An intended printed size is passed in the request text; the plot agent's size
    step honours explicit dimensions.
  - Refining an image panel passes the image as a reference.
  - A finished plot replaces its panel's content, keeping the panel's width, or
    becomes a new panel placed below the existing content. An arrange step then
    decides the final layout.
- **Arrangement:** the planner returns a nested tree of rows and columns rather
  than coordinates (section 7). Each leaf names a panel with an optional preferred
  aspect for rendered plots. Unlike a fixed grid, rows can hold different numbers
  of panels, groups can nest, and area follows importance.
- **Review:** after steps that add, plot, or arrange, any remaining warning checks
  go back to the planner with `review: true`. It can add fixing steps or accept
  the figure, for at most two rounds. Edits alone are not reviewed, because they
  are precise user instructions.
- **Questions:** the planner asks only consequential questions, and answers
  resume the same message. Questions and approvals from the shared plot agent
  appear in the message's `active_step` and are answered through the existing
  assistant-turn and plot-run endpoints.
- **Reliability:**
  - Every step uses a stable request key, so a step that committed before a
    server restart is not applied twice.
  - Messages resume after a restart, except those waiting for a planner answer.
  - Cancelling stops the planner and any running plot.
- **Rules:** agent instructions describe composition principles: reading order,
  visual weight, shapes chosen from content, alignment, printed text size, and
  whitespace. They do not encode layouts for specific plot types.

API: `POST .../messages` (`FigureMessageRequest`, 202), `POST .../messages/{id}/answer`,
and `POST .../messages/{id}/cancel`. The document lists messages under `messages`.

## 7. Fitting plots to panels and checks (Phase 3)

### Rendering at panel size

`POST .../renders` renders one or more plot panels at a size in millimetres. It
uses the existing `figure_width` and `figure_height` parameter update, so there is
no model call and the saved analysis is reused. Only versions whose renderer
accepts those controls can be rendered; other content is scaled.

- Each panel render is a job that follows its plot run. When the run completes,
  the panel's `version_id` becomes the new version, `source_version_id` records
  the version it was sized from, and its scale becomes 1, so the panel keeps its
  frame.
- If the panel changed while the render ran, the result is not applied and the
  job is marked `discarded`.
- Sizes are rounded down to the control's 0.01 in step. Plots render at 1 in or
  more; `arrange` renders smaller panels larger and scales them down.
- **Placement versions do not become the plot's current version.** Workspace,
  the saved-plot library, and update checks in other documents are unaffected.
  The version still appears in the plot's history, marked "Render at figure panel
  size".
- Update checks compare the newest version against both the panel's version and
  its `source_version_id`.
- Demonstration drawings use a fixed canvas, so their text scales with the render
  size. R drawings keep their point sizes, so rendering at the printed size keeps
  their text as designed.

### Arranging

`POST .../arrange` accepts an arrangement tree (section 6) or none. Without a
tree, the current reading-order rows are tidied: each row shares a height and
fills the printable width.

- Locked panels keep their positions and cannot appear in the tree. The
  arrangement starts below them.
- The result is one `set_panel_geometry` revision.
- With `render: true`, plots are then rendered at their assigned frames, and a
  leaf's `aspect` sets the shape of a rendered plot. Scaled content keeps its
  natural proportions.

### Checks

Every document response lists checks. They never block saving.

| Check | Severity | Rule |
| --- | --- | --- |
| `outside_margin` | warning | A panel extends into the page margin. |
| `overlap` | warning | Two panels partly overlap. A panel entirely inside another is an inset and is not reported. |
| `small_text` | warning | A plot's smallest text, multiplied by its scale, is below `min_font_pt` (default 5 pt). Sizes are measured from SVG text elements. Drawings that draw text as outlines, such as R's SVG device, are assumed to have 8 pt smallest text, and the message says "about". |
| `low_resolution` | warning | An image is enlarged beyond its 300 dpi placement. |
| `label_order` | info | Custom labels do not follow the reading order. |
| `unused_space` | info | Panels cover less than half of the printable area. |

## 8. Frontend (Phase 2)

`/figure` joins the interface switcher. The layout follows the other interfaces:
the page on the left and the conversation on the right.

- **Page:**
  - millimetre rulers, zoom to fit, and snapping to margins and panel edges
  - single and multiple selection, dragging, and proportional resizing
  - align and distribute commands
  - arrow-key nudges of 0.5 mm, or 5 mm with Shift
- **Inspector:** label, position, size, scale, available update, and checks.
- **Panel menu:** refine with the plot agent, replace, apply or ignore an update,
  fit to panel, lock, and remove.
- **Toolbar:**
  - a figure tray for dragging saved plots and images onto the page
  - page presets, history, JSON import and export, and file exports
- **Legend:** editable text shown beside the page with resolved labels.

The frontend draws panels from their preview artifacts and the backend's resolved
geometry. While a drag is in progress it previews positions locally; the saved
revision's labels, bounds, and page height always come from the backend. Usage is
documented in [FIGURE_UI.md](FIGURE_UI.md).

## 9. Building a figure from data (Phase 5)

A figure can be built from a description of what it should show. The assistant
designs the whole page first, then creates the plots one at a time, so the layout
is visible from the start and each plot is made at the size it will print.

### Contract additions

- **`datasets`:** `[{ "dataset_id": "..." }]`, the figure's data, changed with the
  `set_datasets` operation. Plots created in the figure use exactly these datasets
  (`data_scope: selected`). With none selected, the plot agent discovers project
  data (`data_scope: auto`). Refining an existing plot uses that plot's own inputs.
- **Slots:** panel content `{ "type": "slot", "prompt": "...", "width_mm": 90,
  "height_mm": 60 }` is a planned panel: a size and a description of the plot it
  will hold. Its natural size is `width_mm × height_mm`, and `scale` applies as for
  any panel. Slots are labelled, arranged, checked, and given legend entries like
  other panels, so the composition is complete before any plot exists.

~~~json
{
  "id": "response",
  "content": {
    "type": "slot",
    "prompt": "Tumour volume over time by treatment group, mean ± SEM.",
    "width_mm": 120, "height_mm": 70
  },
  "x_mm": 5, "y_mm": 80, "scale": 1
}
~~~

### Building

~~~text
"Figure 2: treatment response in the tumour study"
→ planner: slots step
    slots: one prompt and preferred aspect per new panel
    arrangement: a row/column tree over the new slots and any existing panels
→ slots are added, then arranged by the layout solver (each a figure revision)
→ fill queue, in reading order, one slot at a time:
    shared plot agent (figure datasets, slot size in the request)
    → the plot replaces the slot, fitted inside the slot's frame
    → a plot that can be re-rendered and differs from the slot's size is rendered
      at the slot size (section 7)
    → a failure leaves the slot with its error, and the queue continues
→ review round for layout warnings; legend steps where requested
~~~

- **Slots step:** `{kind: "slots", slots: [{panel_id, prompt, aspect}], arrangement,
  summary}`. The arrangement must include every new slot. Saved plots that already
  show what is needed are placed with `add` steps instead of being made again.
- **Plot steps on a slot** fill that slot at its size. Plot steps on a plot panel
  refine it, as before.
- **Filling without planning:** `FigureMessageRequest.fill` lists slots to fill
  directly from their prompts. The editor uses it for **Create plot** and **Retry**.
  Each listed panel must be a slot with a description.
- **Refining without planning:** `FigureMessageRequest.refine` names one plot panel
  with `instructions`, `parameter_changes`, or both. The editor uses it for
  **Refine this plot** in the panel menu. Parameter changes alone update the plot
  version directly; with instructions, the shared plot agent refines the plot and
  receives the changes as parameter drafts. `fill` and `refine` cannot be combined,
  and a direct refinement has no review round.
- **Progress:** `FigureMessage.panels` lists each queued slot as `waiting`,
  `plotting`, `completed`, or `failed`, with the failure message. Questions and
  approvals from the plot agent appear in `active_step` as before.
- **Review:** rounds address layout warnings only. Slots that are still empty are
  left to the user, who can edit the description and retry.

### Editing slots

- **+ Slot** adds an empty slot. The inspector edits its description and size, and
  **Create plot** fills it.
- A slot has no content proportions yet, so dragging its resize handle changes its
  width and height independently.
- On the page, a slot shows its label, description, and status.

### Checks and export

- `empty_slot` (warning): a slot has no plot yet.
- Exports leave empty slots out.

### Creating a figure

- The **New figure** dialog asks for the title, page, data, and an optional
  description of the figure. With a description, the assistant starts building
  immediately.
- An empty page offers four starts: describe the figure to the assistant, add a
  slot, add a saved plot, or add an image.

## 10. Phases

1. **Backend foundation (done):**
   - content contract, storage, operations, revisions, and API
   - page composition and export
   - the 1 in minimum plot size
2. **Frontend editor (done):**
   - library, page editor, inspector, and legend
   - history and exports
3. **Fitting and checks (done):** the layout solver, arranging, rendering plots at
   panel size, and checks.
4. **Figure agent (done):** the planner, plot steps through the shared plot agent,
   additions, arrangement, review rounds, questions, and the Assistant tab.
5. **Building from data (done):** figure datasets, slots, the fill queue, and
   creating a figure from a description.
6. **Later:**
   - visual review of the composed page
   - axis alignment between neighbouring panels
   - consistent fonts across panels
   - embedding figures in Report and Slides

Each phase updates tests, contracts, and user documentation.
