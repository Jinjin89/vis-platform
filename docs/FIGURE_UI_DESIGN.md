# Figure composer design

Status: agreed design; Phases 1 (backend foundation) and 2 (editor) implemented
Last updated: 2026-09-21

The fifth interface, **Figure**, combines saved plots and uploaded images into one
publication figure: typically a full A4 page, or an A4-width panel whose height
follows its content. Panels are created and refined by the existing shared plot
agent. A figure agent plans the composition, and the user can adjust the result
directly, like moving and resizing objects in an illustration editor. Every change,
by agent or by hand, is a validated edit of one versioned JSON document.

## 1. Decisions

| Topic | Decision |
| --- | --- |
| Structure | A figure is its own document type with its own storage and revisions. It is not a Report or Slides document. It shares plot versions and uploaded images by reference, and it uses the same plot agent. Report and Slides may later embed a whole figure as one block. |
| Plot updates | Panels are pinned to an immutable plot version. When a newer version of that plot exists, the panel reports an available update. The user can apply or ignore it. Figure edits never publish shared figure selections. |
| Minimum plot size | `FigureSize` accepts 1–30 in in every interface, so small panels render at their true size. |
| Page presets | A4 full page (210 × 297 mm), A4 width with automatic height, journal widths of 89, 120, and 183 mm with automatic height, and custom. Presets are frontend choices; the backend validates page dimensions. |

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
The planner decides what the figure should contain and how it is organized. Code
computes exact geometry.

~~~text
message → figure planner → steps
  plot     → shared plot agent (create or refine a panel's plot)
  arrange  → layout solver → exact positions and scales
  fit      → render plots at their assigned sizes (no model call)
  check    → bounds, overlap, minimum font, empty space, label order
             → issues return to the planner (at most two rounds)
→ one new figure revision
~~~

- **Arrangement.** The planner returns a nested tree of rows and columns rather
  than coordinates. Each leaf names a panel with an optional relative weight and
  aspect preference. For example: a square UMAP beside a column of two small
  plots, above a wide heatmap next to a survival curve. Unlike a fixed grid, rows
  can hold different numbers of panels, groups can nest, and weights express
  importance.
- **Solver.** Panels in a row share a height and panels in a column share a width.
  The solver respects each panel's natural aspect ratio or its permitted range, and
  distributes remaining space by weight. With automatic height, the page height
  follows the content.
- **User control.** Locked panels, and panels the user positioned by hand, keep
  their geometry unless the user asks the agent to rearrange them. Direct requests
  such as "put C to the right of B" can become direct geometry operations.
- **New plots.** Plots created for a figure receive their target size and the
  figure's font size in the plot request.
- **Rules.** Agent instructions describe composition principles: reading order,
  visual weight, alignment, consistent type, and whitespace. They do not encode
  layouts for specific plot types.

## 7. Fitting plots to panels (Phase 3)

Rendering a plot at its panel size uses the existing `figure_width` and
`figure_height` parameter update. This involves no model call and reuses the saved
analysis. The resulting version replaces the panel's version and records the
version it was derived from, so update checks compare against the source. Fitting
never publishes a shared figure selection. Phase 3 also decides whether these
versions should move a plot's current version in Workspace.

Checks report, without blocking:

- panels outside margins
- unintended overlap
- effective font size below the figure minimum
- large empty areas
- labels out of reading order

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

## 9. Phases

1. **Backend foundation:**
   - content contract and storage
   - operations, revisions, and API
   - page composition and export
   - the 1 in minimum plot size
2. **Frontend editor:**
   - route, library, page editor, and inspector
   - figure tray, history, and exports
3. **Fitting and checks:** the layout solver, fitting plots to panels, and
   checks shown in the editor.
4. **Figure agent:** the planner, plot steps through the shared plot agent,
   arrangement, and the check loop.
5. **Later:**
   - visual review of the composed page
   - axis alignment between neighbouring panels
   - consistent fonts across panels
   - embedding figures in Report and Slides

Each phase updates tests, contracts, and user documentation.
