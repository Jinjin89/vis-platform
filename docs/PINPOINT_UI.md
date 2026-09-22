# Pinpoint

Status: MVP 1 (static plots)
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

## Limits of MVP 1

- Data values are axis coordinates. Categorical axes (bar positions, box groups)
  report the drawing's positions; the image and the render code resolve which
  category is meant. Finding the nearest data rows is left to the planner, which
  has the saved results.
- Pinpoint turns are not Workspace conversations, so the Workspace list is
  unchanged. Like Report and Figure plot steps, they share the history of turns sent
  outside a conversation.
- Only the current version of each plot can be marked.

## Next: interactive plots (MVP 2)

Interactive rendering (for example plotly) would identify the exact data point or
element under the pointer instead of a place on an image. It changes how plots are
drawn, so it should arrive as its own renderer beside the static one, keeping the
other interfaces on static plots.
