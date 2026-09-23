# Datasets and reusable analysis results

Implemented 2026-09-11. This document describes the connected workflow and its current limits.

## Using the workspace

Open **Choose data** above the conversation input. The **Analysis platform** tab includes selectable [single-cell and spatial demo collections](TRANSCRIPTOMIC_DEMOS.md), alongside any configured external platform. Upload related files as one collection, or import a collection from a configured analysis platform. Uploaded tables are profiled locally; the configured model adds concise object descriptions and proposes relationships. Failed interpretation leaves the measured objects available. Unsupported files remain visible without executable capabilities.

The dataset catalog exists before any figure. Select one or more datasets, then describe the requested figure or analysis. The backend plans against exact object revisions and checks project scope, source availability, and declared joins before executing R code. Requests for statistics without a figure produce saved analysis results and conversation cards.

Every newly rendered figure includes width and height controls, saved in inches with its version. The figure stage provides independent fit, zoom, and pan controls. **Export** in the plot toolbar downloads the selected version as PNG (300 dpi), PDF, or SVG at that saved size; stage zoom and pan do not affect the download. The exported drawing has no workspace card or background framing.

**Results** contains reusable tables, scalar statistics, and fitted models. **Use in a figure** selects an exact saved result and prepares a conversation request. This does not add a dataset. Presentation controls rerender from the saved result. Computational refinements create another result; figure history keeps the corresponding input, result, and parameter references.

Dataset descriptions can be edited in the library. Object meanings, units, and relationships can also be corrected through the metadata API. Corrections create a revision without modifying the original values. Failed source refreshes preserve the previous published revision.

## API

All routes are under `/api/v1`. See `contracts/openapi-v1.json` for the complete request and response types.

| Route                                                                  | Behavior                                                        |
| ---------------------------------------------------------------------- | --------------------------------------------------------------- |
| `GET /projects/{project_id}/datasets`                                  | Paginated dataset catalog, independent of figures               |
| `POST /data-bundles`                                                   | Create an upload collection or register a platform import       |
| `POST /data-bundles/{dataset_id}/files?project_id=...&name=...`        | Upload a binary file body using `application/octet-stream`      |
| `POST /data-bundles/{dataset_id}/finalize?project_id=...`              | Start background inspection; returns 202                        |
| `GET /data-bundles/{dataset_id}?project_id=...`                        | Read authoritative ingestion state and the current manifest     |
| `GET /data-bundles/{dataset_id}?project_id=...&revision_id=...`        | Read a saved manifest revision                                  |
| `POST /data-bundles/{dataset_id}/refresh?project_id=...`               | Check a platform source for a new revision                      |
| `PATCH /data-bundles/{dataset_id}`                                     | Correct metadata using `project_id` and `base_revision_id`      |
| `GET /objects/{object_id}?project_id=...&revision_id=...`              | Inspect the common object description                           |
| `GET /objects/{object_id}?project_id=...&revision_id=...&profile=true` | Resolve and profile a selected platform object                  |
| `GET /projects/{project_id}/analysis-results`                          | Paginated saved computations, including results without figures |
| `GET /analysis-results/{result_id}?project_id=...`                     | Read a specific reusable result                                 |
| `GET /projects/{project_id}/data-sources/analysis-platform`            | Discover configured platform collections                        |

The existing `bundle_ids` selection field refers to dataset IDs; there is no duplicate bundle registry. Assistant requests can additionally pin `result_ids`. The coordinator verifies that reused results descend from the selected datasets, including when results depend on other results.

The assistant invokes data interpretation and planning through a common interface. The public object contract contains logical identities, types, profiles, and provenance. Credentials, content locations, and job paths stay in backend provider bindings.

Real execution uses the existing plot-run lifecycle. A completed result-only run has `result: null` and a nonempty `analysis_results` list. Completed events can omit figure identifiers in that case. A failed figure render may still expose an already committed analysis result. Artifact roles now include data, model, script, and methods in addition to preview and publication.

## Supported inputs and execution

Initial parsers support CSV, TSV, JSON arrays of flat records, JSON objects containing named record arrays, JSON Lines, and RDS objects that the installed R runtime can inspect. R containers can yield several related objects. Platform object selectors address JSON keys/list indices or R list/slot paths. Indices are zero-based at the provider boundary.

Current intake limits are 32 MB per file, 30 uploaded files per collection, 100 logical objects per collection, and 250,000 rows / 2,000 columns per tabular object. Catalog pages default to 30 records. Large or partial catalog responses include totals and completeness information.

Large tables and images have their own path. Parquet files, and CSV or TSV files over 32 MB or 250,000 rows, are read by column with pyarrow and stored as Parquet (format `parquet`), up to 20 million rows and 2,000 columns; their profiles are measured the same way. PNG, JPEG, TIFF, and WebP files become `image` objects, such as tissue sections, recording their pixel size; images over 8,192 pixels on the long side are stored downsampled, with the scale in `extensions.stored_scale`, and Pillow's limit of about 179 million pixels applies. These formats may be up to 2 GB per file (`large_upload_limit_bytes`). R analysis here reads CSV and RDS objects, so large tables and images are shown as point maps in Pinpoint; an R plan that names one is refused with `INPUT_NOT_SUPPORTED`. See [PINPOINT_UI.md](PINPOINT_UI.md#point-maps).

Analysis code receives named, read-only inputs and returns declared named outputs. Rendering code receives saved result objects and figure parameters on an already opened SVG device. The initial execution environment includes base R, stats, graphics, grDevices, utils, methods, and jsonlite. It does not install packages during jobs. Random seeds, code hashes, actual parameters, and R/jsonlite versions are saved with results.

The backend independently reopens generated R objects to check their structure and build profiles. Downloadable tables come from that independent inspection. It validates SVG structure and excludes active content and external references. This is structural and rendering validation; automated scientific/publication review and the plot-skill registry remain separate work.

## Restricted R runtime

The connected worker requires Linux with Landlock ABI 3 or newer, seccomp, a C compiler for provisioning, and R with jsonlite. A missing or unusable restricted runtime disables real-data execution; the backend never starts an unrestricted fallback. The runtime verifies a small render during application startup before advertising availability.

For Ubuntu 24.04, provision a repository-local runtime without changing system packages:

```sh
mkdir -p /tmp/vis-r-packages
cd /tmp/vis-r-packages
apt-get download r-base-core r-cran-jsonlite
cd /path/to/vis-platform/backend
uv run python scripts/setup_r_runtime.py /tmp/vis-r-packages
```

This extracts packages under `backend/.runtime` and compiles the launcher and R restriction library. Shared system libraries required by R and Cairo must also be installed. The runtime directory is ignored by Git. In this workspace, the local runtime has been provisioned and exercised with real analysis, models, and SVG rendering.

The backend detects that local runtime automatically. A separately provisioned installation can use `VIS_PLATFORM_R_HOME` and `VIS_PLATFORM_R_SANDBOX`; the matching restriction library must be beside the launcher with the `.so` suffix.

The launcher restricts filesystem access and network calls before R starts. Trusted R packages initialize within that boundary. Before reading data or evaluating generated code, the worker adds process-creation restrictions across threads. Renderer threads inherit the restrictions. Inputs and runtime files are read-only; only the job output directory is writable. Jobs have a 45-second wall limit, 30-second CPU limit, 1.5 GB address-space limit, 64 MB per-file limit, and two execution slots. Cancellation terminates the process group.

The runtime design follows the [Linux Landlock interface](https://www.kernel.org/doc/html/latest/userspace-api/landlock.html) and the [R installation and administration guidance](https://stat.ethz.ch/CRAN/doc/manuals/R-admin.html).

## Analysis-platform connection

Set `VIS_PLATFORM_ANALYSIS_PLATFORM_URL` and optionally `VIS_PLATFORM_ANALYSIS_PLATFORM_TOKEN`. The provider currently implements the explicit [source contract](ANALYSIS_PLATFORM_CONTRACT.md). The actual platform URL and response example have not yet been supplied, so the live platform mapping is not assumed to match this contract. The adapter is verified against contract fixtures; uploads and real local execution are connected independently.

Import reads metadata first. Object bytes are fetched only when selected for profiling or execution, then retained as immutable managed inputs. A provided SHA-256 fingerprint is checked on retrieval. Without a fingerprint, the provider must still report the recorded source revision before and after retrieval. An uncached old revision that cannot be verified is reported unavailable; the latest data is never substituted silently.

Previously materialized inputs, result objects, and figure artifacts remain usable independently of later platform updates. The current implementation materializes complete selected logical objects; provider-side subset pushdown is not implemented. Broad automatic result caching is also deferred: reuse is explicit through saved result identities and renderer dependencies.

## Verification

`backend/tests/test_datasets.py` covers both provider paths, lazy retrieval, scope checks, revisions, source changes, invalid joins, R containers, matrices, scalar results, fitted models, result-only runs, cancellation, and preservation of completed analysis after render failure. R integration tests require the provisioned runtime.

Browser tests cover uploading related files, selection after reload, computed values, and reuse without adding datasets on desktop and narrow windows. A live-model verification also completes upload interpretation, data planning, R analysis, and rendering against a small synthetic collection.
