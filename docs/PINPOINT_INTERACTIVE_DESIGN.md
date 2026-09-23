# Pinpoint MVP 2: interactive plots

Status: point maps (section 5) implemented; Vega-Lite renderer (sections 3–4) proposed
Last updated: 2026-09-22

MVP 1 ([PINPOINT_UI.md](PINPOINT_UI.md)) marks places on a static R image; the
planners see the picture and axis coordinates. MVP 2 makes the drawn elements
themselves selectable: a click identifies the data row behind a point or bar, and a
drag selects the rows inside it. The request then says exactly which data the user
means, not only where they clicked.

## 1. The decision is about what the agent writes

Today the plot agent writes R drawing code, and R produces an SVG. An SVG from base
R carries no link from a drawn shape to its data row, which is why MVP 1 works with
positions. For element-level identity, the drawing must be declarative: the agent
describes how saved result tables map to marks, and a renderer draws them, keeping
each mark's datum. R keeps doing all analysis (`analysis_code` is unchanged); the
new renderer only presents saved results.

So the framework is chosen as a **specification language for the agent** and a
renderer for both the backend (saved artifacts, exports) and the browser
(interaction), not only as a browser widget.

## 2. Options

Checked in this workspace on 2026-09-22:

| | Vega-Lite (+ Vega) | Plotly.js | deck.gl |
|---|---|---|---|
| What it is | Grammar of graphics: JSON that maps named data fields to marks | Chart library: JSON traces with data arrays | WebGL layers for very large or geographic data |
| Click → data row | `item.datum` for every mark, including aggregates | `points[].pointIndex` / `customdata` | `info.object` / `info.index` |
| Drag → selection | interval `params` give data ranges | box/lasso `plotly_selected` | picking in a rectangle |
| Data in the spec | By name (`{"data": {"name": "summary"}}`); the backend injects rows, so the model never sees them | Arrays inside each trace; the backend would have to build traces | Arrays or URLs in layers |
| Saving on the backend | **vl-convert** (Python wheel, no browser): SVG 0.8 s for 2,000 points, PNG, PDF. External data URLs are blocked, and its SVG passed the platform's SVG checks | **Kaleido needs Google Chrome** (failed here without it) | Browser canvas only; raster |
| Publication output | Vector SVG/PDF with text as text; full control of fonts and sizes | Vector SVG through Chrome | No axes, legends, or titles; raster |
| Safety of model output | Declarative; its expression language is sandboxed; URLs can be refused | Declarative; text allows limited HTML links | Layer JSON, but accessors are usually code |
| Browser size | vega-embed + vega + vega-lite, loaded only on `/pinpoint` | ~4.6 MB minified (partial bundles smaller) | ~6.5 MB unpacked, plus a base map for geography |
| Large data | SVG to ~20k marks, canvas to ~100k | `scattergl` to about 1M points, with axes and lasso | Millions of points on the GPU, with picking |
| Weak spots | No native violin (density transform), 3D, dendrograms; slow above ~100k marks | Harder to theme to journal style; heavier | Not a charting library |

Also considered: **ECharts** (strong interaction, but backend SVG needs a Node
service and specs often embed JavaScript formatters); **Observable Plot / D3**
(the agent would write JavaScript that runs in the user's browser, so no);
**R ggiraph** (keeps R, adds data IDs to SVG elements, but needs ggplot2 and
htmlwidgets in the restricted runtime, which has base R only).

## 3. Recommendation

Use **Vega-Lite** as the interactive renderer, beside R, not replacing it.

- It matches the platform's rule that raw data stays out of the model: the spec
  names result tables and the backend fills them in.
- The saved `preview.svg` is still an ordinary SVG, rendered on the backend. Report,
  Slides, Figure, Canvas, Workspace, and every export keep working unchanged.
- Parameter edits re-render without the model or R, in under a second.
- Click and drag give data rows directly, including for aggregated marks such as bars.

Keep **R** for plots Vega-Lite does not express well (survival curves with risk
tables, dendrogram heatmaps, complex annotations); those keep MVP 1 image marks.
For **large point clouds**, draw the same description with **deck.gl** (section
5). **Plotly** is the better choice only if 3D exploration becomes more important
than publication export.

## 4. Design

### Contract (additive)

- `ResearchPlan.renderer`: `"r"` (default) or `"vega-lite"`. With `vega-lite`,
  `render_spec` holds a Vega-Lite v6 spec and `render_code` is null.
- Spec rules, checked before rendering: data only by `{"name": <output key>}`; no
  `url`, inline `values`, `href`, image URLs, or `usermeta`; size and nesting
  limits; compiled by vl-convert with no allowed base URLs.
- Controls stay typed controls. The spec reads them as top-level `params` with the
  same IDs (`{"expr": "point_size"}`); the backend sets their values from the
  version's parameters. `figure_size` sets the overall width and height with
  `autosize: fit`.
- `PlotResultSummary.renderer` tells clients which kind a version is.
- `GET /api/v1/projects/{project_id}/plots/{plot_id}/versions/{version_id}/view`
  returns the resolved spec with its rows. Each row carries `__row`, its index in
  the saved result table.
- `PlotMark` gains `kind: "element"` (a clicked mark: `table` and `rows`, or the
  datum's grouping fields for an aggregate) and `kind: "selection"` (a dragged
  interval: `table` and field ranges). Point and area marks remain for R plots.

### Backend

- A `vega_lite` renderer service beside the R render step: validate, inject rows,
  render `preview.svg` with vl-convert, and save the resolved `view.json` beside it.
  Render errors go through the existing repair loop.
- The data agent may plan `renderer: "vega-lite"` when the request asks for an
  interactive plot. Pinpoint asks for one; the other interfaces do not, so their
  plans are unchanged. The prompt principle: R computes; the spec presents saved
  results by name.
- For element and selection marks, the backend resolves rows from the saved
  result and gives the planners the marked image as today, plus the selected rows'
  values, capped (for example 20 rows and a count).

### Frontend (Pinpoint only)

- Load vega-embed lazily on `/pinpoint`, so the other interfaces' bundles do not
  change.
- A version with a view opens in an interactive stage: hover tooltips; click marks
  an element; drag marks a selection through an interval param the frontend adds
  (the model never has to). Numbered badges sit on the marked items' bounds.
- R versions open in the MVP 1 image stage. The conversation, pins list, and request
  flow are shared.

## 5. Large data (implemented)

Built first, because the lab's data has millions of cells and needs tissue images. As
built, point maps have their own small description (`ResearchPlan.point_map`: table,
x, y, colour, image placement) instead of a Vega-Lite subset: a point layer over an
image is one well-bounded plot family, and a dedicated description is easier for the
model to write and for the backend to check. The renderer, rather than the agent,
handles scale. Usage and measurements are in [PINPOINT_UI.md](PINPOINT_UI.md#point-maps)
and the contract in [contracts/README.md](../contracts/README.md#point-maps).

Choices made while building:

- **No R.** The platform reads the named columns with pyarrow and saves positions,
  colours, and source rows as the analysis result; no generated code runs.
- **Saved figure.** Points are splatted onto the pixel grid and widened to their disc
  by shifting the grid, so drawing costs depend on the figure's pixels, not on the
  number of points (5 million points: 0.6 s at the default size).
- **Picking in the browser.** deck.gl only draws. A grid index finds the point under
  the pointer, because GPU picking re-draws every point and stalls without a fast GPU.
- **Selections on the backend.** A box is resolved over the full source table, as its
  browser count predicts.

The measurements and trade-offs that led here:

Measured with the local R runtime on 2026-09-22: a base-R SVG costs about 230 bytes
per point (10,000 points: 2.3 MB; 100,000: 23 MB; 500,000: 115 MB), while a 300 dpi
PNG of the same plot stays under 100 KB. The backend refuses previews over 10 MB, so
**today any vector scatter above roughly 45,000 points fails**, in every interface.
Vega-Lite's SVG is similar (about 300 bytes per point). Large data therefore needs
two changes, whichever browser library draws it.

**Saved figures: vector frame, raster points.** Axes, text, and legends stay vector;
a dense point layer is embedded as a high-resolution image inside the SVG, as
journals expect for large scatter plots. This fixes the limit for R plots too.

**Interactive view: deck.gl above a threshold.** The agent still writes one
Vega-Lite description; the renderer, not the agent, decides by size.

| Marks in a layer | Browser view | Saved figure |
|---|---|---|
| Up to ~20,000, or any non-point mark | Vega-Lite (SVG) | Vector SVG |
| Point layers above ~20,000 (embeddings, spatial maps, large volcano plots) | deck.gl `ScatterplotLayer` for the points; axes and legend from the description's scales, drawn around it | Vector frame with a raster point layer |

- Points reach the browser as binary columns (x, y, colour, row index; Apache
  Arrow), not JSON: one million points is about 16 MB before compression.
- GPU picking gives the row of a clicked point at any size. Drag selections are
  resolved on the backend over the full saved table, and return a count, a summary,
  and a capped sample of rows, so all columns never have to reach the browser.
- deck.gl also suits spatial data: a tissue image under the spots (`BitmapLayer`),
  polygons for cell boundaries, and hexagon or grid binning at overview zoom.
- Prior art: Microsoft's SandDance rendered Vega with deck.gl (`vega-deck.gl`),
  but that package has not been updated since 2023; this design uses deck.gl
  directly for point layers only.

## 6. Phases

0. **Spike.** Ask the configured model for Vega-Lite specs of the lab's usual plots
   (volcano, UMAP, grouped box and violin, heatmap, bars with error bars, survival
   curve) against saved results. Check validity, publication look with a journal
   theme, and click identity on aggregated marks. Decide per plot type which renderer
   the agent should prefer.
1. **Renderer.** Contract, spec checks, vl-convert rendering, `view.json`,
   parameter updates without the model, exports, restore.
2. **Agent.** Planning and repairing specs; choosing the renderer.
3. **Interactive stage.** Element and selection marks in Pinpoint; row resolution
   for the planners.
4. **Large data (done for point maps).** Raster point layers in saved figures, binary
   point columns, a deck.gl point view, and backend resolution of selections over the
   full table. R plots with dense layers still produce vector SVGs and remain subject to
   the 10 MB preview limit.

## 7. Open questions

- Answered 2026-09-22: millions of cells, with tissue images; large data came first.

- Planners now receive a clicked point's values and five example rows of a box, besides
  counts and summaries. This relaxes "raw data stays out of the model" for data the
  user points at; confirm, or reduce it to summaries only.
- vl-convert adds about 84 MB to the backend environment (it bundles a JavaScript
  engine). Acceptable for deployment? (Not needed for point maps, which use pyarrow and
  numpy.)
- Should other interfaces ever show the interactive view, or stay static?
