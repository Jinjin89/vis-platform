# Intent-driven Report interface

Report uses one natural-language composer. The backend infers whether the user
wants a figure, prose, a structural edit, or a conversational answer, and chooses
the target and placement from the report and recent conversation.

Examples:

- “Add an abstract at the beginning.”
- “Create a treatment-comparison subsection under Results, add a figure, and explain it.”
- “Move Discussion before Results.”
- “Shorten the second paragraph.”
- “Refine Figure 1 with a softer palette.”

Clicking a section, paragraph, figure, or table adds an optional context hint. A
named target in the request takes precedence. There is no required section picker
or Discuss / Write / Figure mode. The assistant asks only when it cannot resolve
a consequential ambiguity from the available context; answers resume the same
saved message. The existing parameter popup and direct editing shortcuts remain
available.

## Document contract v2

See [the schema](../contracts/report-content-v2.schema.json) and
[the importable example](../contracts/report-content-v2.example.json).

`ReportContent` has:

- `schema_version: "2.0"`
- A separate report `title`.
- Versioned `datasets` references using the existing Dataset registry.
- An ordered `sections` array.

Each section has a stable `id`, `title`, `level`, `parent_id`, and ordered
`blocks`.

- Level **1** is a first-level section and has no parent.
- Level **2** is a subsection referencing a level-1 section.
- Sections appear in document order, with a parent's subsections immediately
  after it. The array defines sibling order; there is no second numeric ordering
  field to keep synchronized.
- Section and block IDs are unique within a report. Parent/level consistency,
  depth, ordering, and all reference ownership are validated by the backend.
- Moving a first-level section moves its subsections as a unit. Subsections can
  move between first-level parents. A section with children cannot be demoted
  to a subsection because that would create a third heading level.

The report title renders as an h1, level-1 section headings as h2, and level-2
subsections as h3.

### Blocks and shared figures

Blocks are typed text, figure, or table records with stable IDs.

A text block contains Markdown prose and the version references supplied to its
writer. A table contains its columns, rows, and an optional source description.
A figure references either a shared `version_id` or an uploaded `image_id`.

**A report plot does not own a copy of its description, R code, parameters, data,
or execution state.** These come from the same immutable plot version and services
used by Workspace and Canvas. The report displays that version's shared caption
(or preview description). To change a plot, use the shared plot agent; the report
references the resulting version. Supplementary report interpretation is a text
block. The `caption` field is reserved for standalone uploaded images and must
be empty for a shared plot.

## Targeted document operations

The [operation contract](../contracts/report-operations-v1.schema.json) supports:

- Rename the report and update its dataset references.
- Insert, rename, move, or remove a section.
- Insert, replace, move, or remove a content block.
- Place new content before or after a specific sibling ID, or append it.

A mutation request carries `request_id`, `base_revision`, an operation batch,
and a short change summary. It sends only the affected nodes/references, not a
rewritten document. The backend applies the batch to a copy, validates each
transition and reference, then commits it atomically with an immutable revision.
A failed operation cannot leave half of that batch applied. Repeated request IDs
are idempotent; stale revisions return a conflict. Running edits protect their
targets, and new outputs reserve their IDs.

The full-content PUT endpoint remains available for legacy clients and restoring
saved revisions. Interactive report controls use the targeted operation endpoint.

## Intent, planning, and execution

The report-specific planner receives a compact, ordered outline: IDs, heading
levels, text excerpts, figure numbers, shared descriptions, selected hints,
available project figures, and recent conversation. It can request expanded
section context automatically. It produces validated document operations,
writing steps, plotting steps, a reply, or a clarification.

Plotting steps delegate to the existing `AssistantTurnService`, data planner,
plot coordinator, and restricted R worker. There is no report-specific R
generator or alternative plotting pipeline. Writing adds report prose such as
abstracts and summaries using the saved results and report context.

A plan may contain a short sequence. For example, the backend can first create a
subsection, then generate a shared figure in it, then write a paragraph after that
figure using its completed results. New IDs declared in earlier steps can be used
as anchors by later steps. Generated content is inserted at the validated anchor,
and refinements preserve the existing block ID.

The backend stores the original message, plan, completed steps, exact child
requests, and shared run references. A refresh or restart resumes saved progress.
Operation and child-request keys prevent duplicate changes during recovery.
If a later step fails, earlier completed steps remain in history and the assistant
reports them. A single operation batch is atomic; an entire sequence containing
R execution may span several revisions.

Discussion replies do not publish report content. Clarification questions preserve
the original goal, and only unresolved choices are shown to the user.

## Migration and import

Version-1 pre-reports with a flat `topics` array remain importable. Existing
stored reports and historical revisions are projected into v2 when read:

- Topic IDs become section IDs and retain their content order.
- Existing headings become level-1 sections.
- Dataset and plot-version references are preserved.
- An old copied plot caption matching the shared description is omitted.
- An independently authored old report caption is preserved as a separate text
  block next to the figure, with a stable generated ID and its evidence reference.

Stored old revision snapshots are not rewritten. New saves use v2. The v1 schema
remains available for import compatibility.

References must belong to the current project. Data from an external analysis
platform is registered through the existing Dataset adapter first. Imports do
not execute R code. The JSON export is a structured document containing references,
not a self-contained archive of every dataset and image.

## API

All routes are under `/api/v1/projects/{project_id}/reports`.
The transport API remains v1; the nested report content declares version 2.0.

| Method | Suffix | Purpose |
| --- | --- | --- |
| GET / POST | empty | List, create, or import reports |
| GET | /figures | Discover current shared project figure versions |
| GET / PUT | /{report_id} | Read report / replace content with revision checking |
| POST | /{report_id}/operations | Apply an atomic batch of targeted operations |
| POST | /{report_id}/messages | Send one message with an optional selection hint |
| POST | /{report_id}/messages/{message_id}/answer | Resume a clarification |
| POST | /{report_id}/messages/{message_id}/cancel | Cancel planning or active execution |
| POST | /{report_id}/edits | Direct typed writing/plot requests used by detailed controls |
| POST | /{report_id}/edits/{edit_id}/cancel | Cancel direct edits or dismiss errors |
| GET | /{report_id}/revisions | List saved revisions |
| GET | /{report_id}/revisions/{revision} | Read an upgraded historical snapshot |

A message request contains only `request_id`, `message`, and optional
`selection: { section_id?, block_id? }`. The backend chooses action types and
placement. Direct edit requests accept canonical `section_id`; legacy
`topic_id` remains an input alias. The returned document includes persistent
messages and direct edit status; message-owned child edits are not duplicated in
the conversation.

## Presentation and export

The document keeps publication-style paragraphs, numbered figures, and restrained
controls. Dataset status and execution details stay outside the paper. The
assistant can be resized or hidden; narrow screens show either the report or
assistant at full width. Print / Save PDF uses a document-only stylesheet.
Figure image and R-code exports retain the existing shared endpoints.


## Shared documents and linked figures

Report now shares its document engine and assistant with Slides. The additive `kind`
field defaults to `report`; Slides uses a format adapter and flat containers. New
report figures are linked by default through `follow_plot_id`. Read `figure_bindings`
for each placement’s displayed version; pinned and linked placements can coexist.
Right-click a figure to pin its current version or link updates. Revisions freeze
resolved figure versions. See [SLIDES_UI.md](SLIDES_UI.md) for the shared selection
API, atomic publication, and the distinction from experimental plot branches.
