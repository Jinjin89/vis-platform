# Transcriptomic demos and figure stage

Open **Choose data → Analysis platform** to select either built-in collection. They are available without an external connection and use the same import, object-resolution, analysis, and figure-version APIs as platform data. Selecting a demo is explicit; no request silently substitutes demo data for an unavailable research source.

## Collections

| Collection                         | Contents                                                                                                                                                                                                    |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Single-cell transcriptomics · Demo | 360 cells, 24 genes, four simulated populations, three donors, balanced condition labels, integer counts, normalized expression, cell annotations, gene annotations, and illustrative embedding coordinates |
| Spatial transcriptomics · Demo     | 404 tissue-shaped spots, 24 genes, four simulated tissue domains, integer counts, normalized expression, spot annotations, gene annotations, and spatial coordinates in micrometers                         |

Generation is deterministic, with seeds recorded in the generator and a versioned source identity. Expression values use `log1p(count / observation total × 10,000)`. Identifiers link each count/expression row to its matching cell or spot metadata and coordinates; gene identifiers are consistent across the two collections. Counts and QC summaries describe only the small demonstration gene panel.

These are independent simulations, not real studies or matched single-cell/spatial samples. Cell embedding coordinates are illustrative and are not the output of a UMAP or t-SNE calculation. Gene associations encode the simulation, not biological validation. The object descriptions preserve these distinctions for the agent.

The collection structure follows familiar [single-cell expression/embedding conventions](https://scanpy.readthedocs.io/en/latest/tutorials/plotting/core.html) and the separation of expression and [spatial spot coordinates](https://www.10xgenomics.com/support/software/space-ranger/4.0/analysis/outputs/spatial-outputs). The data itself is generated locally; no source dataset is copied.

`contains_demo_data` is retained on datasets, analysis results, and figures. Any result that uses a demo input keeps the flag. The picker, result cards, figure stage, and exported R figure disclose demo provenance. External sources cannot use the reserved built-in identifiers or locators.

## Figure dimensions

Every newly rendered figure exposes **Figure width** and **Figure height**. They use inches, accept hundredth-inch increments, and support 2–30 inches per side. Both controls are supplied by the backend even when the model returns no other controls.

`ResearchPlan.figure_size` supplies explicit initial width and height chosen by the model for the requested plot, its panels, and its labels and legends. It is required for rendering; width and height have no shared default. Analysis-only plans may omit it. The model also chooses the relevant presentation controls, initial values, bounds, choices, and named groups. The original request and current figure settings are included in its planning context. The renderer owns the reserved `figure_width` and `figure_height` controls. Changes rerun rendering at the requested R device dimensions, reuse the saved analysis result, and create a new figure version. SVG output declares physical inch dimensions explicitly while retaining the renderer's coordinate viewBox. History restores the saved dimensions along with the figure and its inputs.

The legacy illustrative SVG renderer also exports the selected page size, preserving its existing vector layout. Historical versions without a recorded physical size remain viewable using the image's intrinsic aspect ratio.

Generated control schemas expose only the supported rendering update strategy. Analysis expressions receive `inputs` and `analysis_parameters`; rendering expressions receive `results` and presentation `params`. The previous `params` analysis alias remains available for existing saved scripts.

## Figure stage

The preview now sits on a separate page over a subtle stage grid. The toolbar provides **Fit**, **Zoom out**, **Zoom in**, and a percentage control that returns to **100%**. Drag the stage to pan; arrow keys also move the view. Press **F** or double-click to fit the figure again.

Viewing controls change only the local camera. They do not change export dimensions, create versions, or rerun analysis. The footer shows the recorded output size, and the surrounding workspace stays within the window. The stage keeps page geometry separate from the viewport so additional figure interactions can be added later.
