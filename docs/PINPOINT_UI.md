# Pinpoint

Status: MVP 1 (static plots) and point maps for large data
Last updated: 2026-09-22

Pinpoint is the sixth interface. You point at places on a plot and say what you
want, so "this", "here" or "1" means exactly the place you marked. It is separate
from Workspace, Canvas, Report, Slides and Figure: its own route (`/pinpoint`),
feature folder (`frontend/src/features/pinpoint/`), page, and `pinpoint-` CSS
classes. The other interfaces send no marks, so they behave as before.

## Using it

- The **Plots** list shows every plot in the study, from any interface. Choose one
  to open it; **New plot** asks for a plot from the study's data.
- Click the plot to mark a point, or drag to mark an area. Marks are numbered 1–9;
  a removed number is used again first. Remove a mark with its × below the request
  box, or by clicking its badge on the plot.
- Refer to marks by number: "label 1", "why is 2 so high?", "zoom into 3", "make
  1 and 2 the same colour". Enter sends; Shift+Enter starts a new line.
- Marks stay while you keep talking about the same version. A new version of the
  plot replaces the image and clears them, because they were places on the old one.
- Questions and approvals from the plot agent appear in the conversation, using the
  same status card as Report and Figure. The request can be cancelled there.
- Each plot keeps its conversation in this browser, as canvases do. A conversation
  started with **New plot** moves to the plot it made.

## How a mark reaches the assistant

A mark is a place on the image, not on the screen: `x` and `y` are fractions of
the image from its top-left corner, and an area adds `width` and `height`. They
hold at any zoom. The request is an ordinary assistant turn with
`AssistantTurnRequest.plot_marks` and the `base_version_id` the marks were placed
on (see [the contract](../contracts/README.md#pointing-at-a-plot)).

The backend gives both planners, the intent planner and the data and code planner,
two things:

1. **The marked image.** The saved SVG is rasterised to a PNG (1600 px on its long
   side) with numbered rings for points and outlines for areas, in a colour plots
   rarely use. It is labelled as the current plot with the user's marks, apart from
   reference images, and is never offered as one.
2. **Data coordinates.** While R draws a plot, the worker records each plotting
   region (the area inside the axes) in image fractions, with its axis ranges and
   log scales, in `plot-map.json` beside the saved preview. It hooks
   `before.plot.new` and `plot.new`, so several panels (`par(mfrow)`, `layout`)
   and overlays each get a region, numbered in drawing order. `plot_marks` in the
   planner context gives each mark's image position and, for each region it falls
   in, its data values (`x`, `y`, or `x_from`…`y_to` for an area). A mark outside
   every region, such as a title or legend, has none, and the image decides.

The prompts state one principle: marks show where the user points; they are not a
style reference or part of the figure, and are never drawn in the output.

Plots saved before regions were recorded, and demonstration plots, have no
`plot-map.json`; their marks reach the planners through the image alone. A
restored version copies the regions with its drawing.

## Point maps

Embeddings and spatial maps can have millions of cells, too many for a vector figure
or for R here. A **point map** draws a table's rows at two coordinates, optionally over
an image such as a tissue section. The assistant plans one when a Pinpoint request
suits it (see [the contract](../contracts/README.md#point-maps)); large tables and
section images come from uploads (see [DATA_WORKFLOW.md](DATA_WORKFLOW.md)).

- **The saved figure** keeps axes, text, and legend as vector and embeds the points,
  and the image under them, as a picture at print resolution. It works in every
  interface and export like any plot. Point size, opacity, image, and figure size are
  controls; changing them re-draws without the model or R.
- **The interactive view** in Pinpoint draws the points on the GPU with deck.gl, over
  the image, with axes that follow pan and zoom. **Click a point** marks that cell;
  **Drag an area** marks the cells in a box, with their count shown on the map.
  Hovering shows a cell's colour value and position. **Image** hides the image, and
  **Fit** shows the whole map again.
- Finding the point under the pointer uses a grid index in the browser, not a GPU
  read, so hovering and clicking stay immediate with millions of points.
- The assistant receives, besides the marked picture, what each mark holds in the full
  source table: a clicked cell's values, or a box's count, make-up by colour, most
  different numeric columns, and example rows.
- Without WebGL2 the page shows the saved figure with image marks instead.

Measured on 2026-09-22 with 2 million cells on a 2,000 × 1,500 section: upload
inspection 4.7 s; first drawing 4.6 s; a parameter change 1.8 s; 24 MB of positions
to the browser; resolving a click and a box of 118,000 cells for the assistant 1.9 s.
Hovering and clicking took 50 ms in the browser. First display took 41 s, but that
was in software-only WebGL on a server; a graphics card is much faster.

## Limits

- Image-mark data values are axis coordinates. Categorical axes (bar positions, box
  groups) report the drawing's positions; the image and the render code resolve which
  category is meant.
- Pinpoint turns are not Workspace conversations, so the Workspace list is
  unchanged. Like Report and Figure plot steps, they share the history of turns sent
  outside a conversation.
- Only the current version of each plot can be marked.
- Point maps show one layer of points; images above about 179 million pixels must be
  uploaded downsampled, with `units_per_pixel` to line them up.

## Next

Interactive statistical plots (bars, boxes, heatmaps) with element marks are proposed
in [PINPOINT_INTERACTIVE_DESIGN.md](PINPOINT_INTERACTIVE_DESIGN.md).
