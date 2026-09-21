# Slides MVP

Choose **Slides** in the header, then **New presentation**. The editor starts with
three editable slides: a title, key findings, and takeaways. Add existing datasets
using Data, reuse saved figures, or ask the assistant to create a figure and a
concise summary. Selection is optional context for the same document planner used
by Report; the planner receives the document format and slide layout settings.

## Editing and presenting

- The left filmstrip selects slides. Add, delete, and move slides with stable IDs.
- Choose Title, Figure + summary, Two columns, Statement, or Table layouts.
- Paper and Midnight themes share a 16:9 stage.
- Add Markdown text, uploaded images, saved R figures, and pasted spreadsheet tables.
- Double-click text or figures to edit. Right-click a figure for refinement, code,
  export, and link/pin actions. Figure parameters reuse the existing inspector.
- Selected elements have move and resize handles. Alt + arrow keys move a focused
  element; arrow keys on the resize handle change its size. Frames use fractions
  of the slide dimensions and are validated against the slide bounds.
- Speaker notes are saved separately from displayed content.
- Present opens the presentation view. Arrow keys navigate and Escape exits.
- History preserves document revisions. JSON export freezes resolved plot versions;
  imported JSON creates a new deck in the current project. Print / Save PDF uses a
  slide-only 16:9 stylesheet.

This MVP is an online slide editor. Native PowerPoint import/export, animations,
collaborative cursors, and automatic report-to-slides conversion are not included.
Tables pasted into slides are authored document content; analytical table references
are a future extension. R figures remain shared, editable scientific plot records.

## Contracts and shared document services

The external [slide-deck v1 schema](../contracts/slide-deck-v1.schema.json) describes
`title`, `datasets`, `presentation`, and an ordered `slides` array. Each slide has
`id`, `title`, typed `elements`, and `settings` containing layout, notes, and frames.
An [importable example](../contracts/slide-deck-v1.example.json) is provided.

A small backend adapter converts this contract to the existing document engine:
`ReportContent.kind = slides`, with each top-level section representing a slide and
each block representing an element. The shared format rejects nested slide sections.
Report documents keep their first- and second-level headings. Legacy reports default
to `kind = report`. Library queries keep the two formats separate.

This deliberately reuses the existing persistence, revision checks, atomic operations,
conversation history, clarification recovery, writing, and plotting orchestration.
The transport retains `/reports/{document_id}` for shared document operations rather
than duplicating these services. The new creation/import and export routes are:

- `GET /api/v1/projects/{project_id}/slides` — list decks.
- `POST /api/v1/projects/{project_id}/slides` — create/import `CreateSlideDeck`.
- `GET /api/v1/projects/{project_id}/slides/{deck_id}/content` — export the slide contract.
  `freeze=true` is the default; `freeze=false` retains live references.

Shared document operations add `set_slide_settings` and `set_presentation_settings`.
Other operations retain their stable section/block identifiers. Rendering, dragging,
and layout are frontend responsibilities; intent routing and scientific operations
remain backend responsibilities. No browser receives backend storage paths.

## Linked and pinned figures

Plot identity, immutable versions, analysis results, and Dataset revisions are reused.
A figure block keeps `version_id` as its saved anchor, and optionally has
`follow_plot_id`. The shared current selection is a separate database pointer from
`plots.current_version_id`: experimental Canvas/Workspace branches do not implicitly
publish changes into documents.

- New figures generated in Report or Slides are linked by default.
- Saved-figure insertion offers “Link updates across documents”.
- Refining a linked placement publishes the successful new version and updates all
  linked appearances in Report and Slides. Document polling refreshes their previews.
- Creating a separate variation does not publish a shared update.
- Pinning resolves and stores the currently displayed immutable version.
- Local element position, size, and slide theme do not modify the scientific figure.

The response includes `figure_bindings`, mapping block IDs to displayed version IDs,
plus `figures`, keyed by immutable version ID. This lets a linked and a pinned
appearance of the same original figure coexist without overwriting either preview.
Consumers must use the binding for display, refinement, code, and export.

`POST /api/v1/projects/{project_id}/shared-figures/{plot_id}` initializes a shared
selection once and returns the selected figure. `PUT` publishes an explicit selection
with `expected_version_id` for conflict checking. Both validate project ownership.
A document refinement commits publication and document revision atomically. If another
editor published first, it fails with a conflict instead of overwriting that choice.
Saved revisions freeze the resolved versions inside the same transaction. Pinned
historical figures and immutable Canvas nodes are preserved.

Image bytes, R code, parameter controls, and scientific descriptions remain in the
existing backend plot/artifact stores. Document placements do not duplicate them.
Writing stores evidence version references; changing analysis results can mark prose
stale, while a rendering-only change reusing the same analysis does not.
