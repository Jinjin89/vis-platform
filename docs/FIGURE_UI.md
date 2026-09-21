# Figure interface

Choose **Figure** in the header to compose saved plots and images into a
publication figure. The design, contract, and remaining phases are described in
[FIGURE_UI_DESIGN.md](FIGURE_UI_DESIGN.md).

## Creating a figure

1. Choose **+ New figure**, enter a title, and pick a page: A4 page, A4 width with
   automatic height, or a single (89 mm), 1.5 (120 mm), or double (183 mm)
   journal column. Automatic height ends the page one margin below the lowest
   panel, which suits figures shorter than a full page.
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
  content; plots are never stretched.
- Shift-click selects several panels, which then move together. The Panel tab
  aligns them by their edges or centres, and distributes three or more evenly.
- With a panel focused, arrow keys move it by 0.5 mm, or 5 mm with Shift. Arrow
  keys on the corner handle change its scale by 1%, or 5% with Shift. A burst of
  key presses is saved as one revision. Delete removes the selection, and
  Escape clears it.
- Right-click a panel to bring it to the front, lock it, or remove it.
- Zoom with − / + at the bottom right. The percentage button fits the page to
  the window; at 100% a millimetre on the page is a physical millimetre.

## Panel, page, and legend settings

- **Panel tab (with a panel selected):**
  - a custom label (leave it empty for automatic letters) and label visibility
  - exact position, width, and scale
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
re-run analyses.

## Verification

- Frontend unit tests cover presets, snapping, group moves and scale limits,
  alignment and distribution, placement of new panels, legend text, keyboard
  nudges batched into one operation, update application, and label and removal
  operations.
- Browser tests create plots, compose a double-column figure, drag and nudge
  panels, relabel a panel, write its legend, export a PDF, reopen the figure
  from the library, and restore a revision from history.
- Backend tests cover the contract, geometry, labels, operations, revisions,
  conflicts, project isolation, update notices, and all export formats.
