# Figure interface

Choose **Figure** in the header to build a publication figure. Like Report and
Slides, a figure stands on its own: describe it and let the assistant build it
from your data panel by panel, arrange plots and images you already have, or mix
both. The design, contract, and remaining phases are described in
[FIGURE_UI_DESIGN.md](FIGURE_UI_DESIGN.md).

## Building a figure from data

1. Choose **+ New figure**, pick the page, choose the figure's data under **Data
   for this figure**, and describe the figure, for example "Figure 2: treatment
   response, with tumour growth over time, final volumes by group, and marker
   expression". Then choose **Create and build**.
2. The assistant plans the panels and lays out the whole page as dashed **slots**,
   one per plot, labelled A, B, C… in reading order.
3. It then fills the slots one at a time, in reading order, with the same
   plotting agent used in Workspace. Each plot is made at its slot's size, so its
   text prints as designed. The slot shows **Waiting**, **Creating the plot…**, or
   **Could not be created**, and the conversation lists the progress.
4. A slot that fails keeps its place and description. Select it, adjust the
   description in the **Panel** tab, and choose **Retry**. Other slots are not
   affected.
5. Once the plots exist, the assistant reviews the layout and writes legend
   entries when you asked for a legend.

You can also describe a figure later in the **Assistant** tab, or build one by
hand: **+ Slot** adds an empty slot in the first free space, you describe the plot
it should hold, and **Create plot** makes it. Drag a slot's corner to change its
width and height freely; a slot has no fixed proportions until its plot exists.

The **Data** button in the toolbar sets the figure's datasets. New plots use
exactly these datasets. Without any, the plotting agent chooses from the
project's data. Refining an existing plot always uses that plot's own data.
Empty slots are reported by the checks and left out of exports.

## Figure assistant

The **Assistant** tab beside the page plans the figure from one message, for
example "Build a four-panel figure of the treatment response", "Put the UMAP
first, then the two violin plots side by side", "Add a survival curve for the
treated group", or "Write the legend".

- **What it does:**
  - plans new panels as slots and creates each plot from the figure's data
  - arranges panels as nested rows and columns, then renders plots at their new
    sizes
  - refines plots with the same plotting agent used by Workspace, including its
    data selection, questions, and approvals
  - adds saved plots or images, and edits labels, page settings, and the legend
- **Selected panels:** they are sent as a hint ("About panel A"), and a panel
  named in the message takes precedence.
- **Questions:** the assistant asks only when a choice matters, and answers
  continue the same request. A plotting step's questions and approvals appear
  in the conversation.
- **Checks:** after arranging or plotting, the assistant reviews the remaining
  layout warnings, for up to two rounds. Failed slots are left for you to retry.
- **Safety:** every change is a figure revision, so **History** can restore
  anything the assistant did. **Stop** cancels a running request.

Clicking a panel keeps the conversation open. Double-click a panel, or choose the
**Panel** tab, to edit its properties.

## Composing existing plots and images

1. Choose **+ New figure**, enter a title, and pick a page: A4 page, A4 width with
   automatic height, or a single (89 mm), 1.5 (120 mm), or double (183 mm)
   journal column. Automatic height ends the page one margin below the lowest
   panel, which suits figures shorter than a full page. Leave the description
   empty to start with a blank page.
2. Add content with **+ Plot** (any plot saved in Workspace, Canvas, Report, or
   Slides) or **+ Image** (PNG, JPEG, or WebP; placed at 300 dpi). New panels
   take up to half of the printable width and go to the first free spot in
   reading order.
3. Panels are labelled A, B, C… in reading order: panels in the same row are read
   left to right, and rows top to bottom.

**Import figure** creates a figure from exported figure JSON in the current
project. Its plot versions and images must belong to that project.

## Arranging panels

- Drag a panel to move it. Edges and centres snap to the page margins, the page
  centre, other panels, and a 4 mm gutter beside them; hold Alt to move freely.
- Drag the corner handle to scale a panel. Its proportions always follow its
  content; plots are never stretched. Slots are the exception: dragging their
  corner changes width and height independently.
- Shift-click selects several panels, which then move together. The Panel tab
  aligns them by their edges or centres, and distributes three or more evenly.
- With a panel focused, arrow keys move it by 0.5 mm, or 5 mm with Shift. Arrow
  keys on the corner handle change its scale by 1%, or 5% with Shift. A burst of
  key presses is saved as one revision. Delete removes the selection, and
  Escape clears it.
- Right-click a panel to bring it to the front, lock it, or remove it.
- Zoom with − / + at the bottom right. The percentage button fits the page to
  the window; at 100% a millimetre on the page is a physical millimetre.

## Tidying and printed size

- **Arrange → Tidy rows** keeps the current rows and gives the panels in each row
  one height, filling the printable width with 4 mm gutters. Locked panels stay
  where they are, and tidied rows start below them.
- **Arrange → Tidy rows and render plots at size** also re-renders each plot at
  its new frame, so text and lines print at their designed size.
- A plot panel's **Print size** section renders it at its current panel size, or
  at a new width and height to change its shape. Only plots with size controls can
  be rendered; images and other plots are scaled. A rendering overlay shows while
  it runs. The finished render replaces the panel at scale 100% and does not
  change the plot's current version in Workspace. If you change the panel before
  the render finishes, the result is discarded and a notice explains why.

## Checks

The Page tab lists layout and print checks, and the Panel tab lists the checks
for the selected panel. Clicking a check selects its panels, and panels with
warnings have a dashed outline.

- **Warnings:** panels that extend into the margin, panels that partly overlap
  (an inset fully inside another panel is fine), text that prints below the
  smallest size set on the Page tab (5 pt by default), images enlarged beyond
  300 dpi, and slots that have no plot yet.
- **Notes:** custom labels out of reading order, and pages that are mostly empty.

Plots whose text is drawn as outlines, as R's SVG device does, are estimated
from an assumed 8 pt smallest text.

## Panel, page, and legend settings

- **Panel tab (with a panel selected):**
  - a custom label (leave it empty for automatic letters) and label visibility
  - exact position, width, and scale (a slot: width and height)
  - for a slot: the description of its plot, and **Create plot** or **Retry**
  - lock position, drawing order, and removal
- **Page tab (nothing selected):**
  - page preset, width, height or maximum height, and margin
  - automatic height
  - label letters (A or a), size, font, and weight
- **Legend tab:** a figure summary and one entry per panel. The preview joins
  them as `Figure 1. Summary. (A) … (B) …`, and **Copy legend** copies that text
  for the manuscript. Legend entries follow their panels when labels change. The
  legend is not drawn into the exported image.

## Plot updates

Panels keep the exact plot version they were given. When that plot has a newer
version (its explicitly shared selection, otherwise its current version), the
panel shows **Update available**. **Apply update** swaps in the new version and
keeps the panel's width on the page; **Keep current** dismisses the notice for
that version. Nothing in a figure changes without one of these actions.

## History and export

Every change is saved immediately as a new revision. **History** restores an
earlier revision as a new one. **Preview** shows the server-rendered page.
**Export** downloads a vector PDF or SVG, a 300 dpi PNG or LZW-compressed TIFF, or
the figure JSON. Exports are composed from the saved plot drawings and never
re-run analyses. Empty slots and their labels are left out.

## Verification

- Frontend unit tests cover presets, snapping, group moves and scale limits,
  alignment and distribution, placement of new panels and slots, panel IDs,
  legend text, keyboard nudges batched into one operation, update application,
  label and removal operations, describing, resizing, and retrying a slot, and
  starting the assistant from the New figure dialog.
- Browser tests create plots, compose a double-column figure, drag and nudge
  panels, relabel a panel, write its legend, export a PDF, reopen the figure
  from the library, restore a revision from history, tidy rows while rendering
  plots at their printed size, and use the assistant to answer a question,
  arrange the figure, and write its legend. They also build a figure from a
  description slot by slot, fill a hand-drawn slot, and add several images on a
  plain-http address.
- Backend tests cover the contract, geometry, labels, operations, revisions,
  conflicts, project isolation, update notices, and all export formats. They
  also cover the arrangement solver (shared row heights, nested groups, page
  limits), tidying around locked panels, every check, text measurement,
  rendering at panel size without changing the current version, and discarding
  renders for panels that changed. They also cover the assistant's replies and
  questions, ordered steps, plot steps through the shared plot agent, review
  rounds, failures, cancellation, and project isolation. They also cover slots
  and figure datasets, slot shapes from the arrangement, exports without empty
  slots, filling slots in reading order at their size, continuing after a failed
  slot, and filling slots directly without planning.
