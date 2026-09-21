# Dataset and analysis-result design

Status: core workflow implemented; see [DATA_WORKFLOW.md](DATA_WORKFLOW.md) for verified behavior and current limits.
Updated: 2026-09-11

## Starting decisions

A dataset is a collection of related objects. Its initial sources are an analysis platform and user uploads. The platform already describes its objects and relationships. Uploads need parsing, profiling, and assistance interpreting their meaning. Agents may join, transform, calculate statistics, and run analysis code, but these operations do not register new datasets.

The dataset registry describes available inputs even when the project has no figures. Saved figures describe what was used, and are not the source of truth for what data is available.

The foundation is a versioned catalog of usable objects. Datasets organize imported objects; analysis results organize computed objects. Both expose the same object description and inspection tools. Providers supply access to source data, and artifacts retain saved outputs.

This extends the existing [architecture baseline](ARCHITECTURE.md). The existing data-bundle concept becomes the dataset concept in the product; there should be one underlying entity, with existing `bundle_ids` mapped at the API boundary when contracts evolve.

## 1. Responsibilities and ownership

| Concept          | Responsibility                                                                    | Example                                                                         |
| ---------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| Dataset          | Group related imported objects and their source provenance                        | An expression analysis with counts, sample annotations, and imported statistics |
| Dataset revision | Pin the collection's object revisions, descriptions, and relationships            | The exact collection used for a saved figure                                    |
| Object           | Describe one usable table, matrix, embedding, model, or other supported structure | Counts matrix or sample-annotation table                                        |
| Analysis result  | Retain validated outputs and the method that produced them                        | A joined table, statistical summary, or fitted model                            |
| Artifact         | Store a saved representation of an output                                         | Table file, serialized model, script, or SVG                                    |
| Figure version   | Bind a rendered figure and its parameters to exact inputs and results             | Version 3 using a particular fitted model                                       |

An object has one owner: an imported dataset or a local analysis result. An imported statistical result belongs to its source dataset; Vis does not invent a local execution record for it. A locally calculated result belongs to its execution run and references its actual input objects.

One file can contain several objects, and one object can require several files. Storage layout is an execution concern and does not define dataset identity. Original imported data is read-only. Only ingestion registers datasets; analysis records outputs as results.

## 2. A small provider interface, a shared object contract

Use a provider interface for source-specific discovery, description, and resolution. The codebase already uses Python protocols for agent interfaces; the same approach fits here. A dataset itself is a structured domain record, rather than a source-specific subclass with plotting and analysis methods.

The backend has two initial providers:

- Analysis-platform provider: preserve the platform's identifiers and semantic descriptions, normalize them into the common contract, and resolve selected source revisions.
- Upload provider: retain uploaded files, use compatible parsers to extract objects, and assemble the validated description of the uploaded collection.

Parsing is separate from provider access: a table file has the same parsing rules regardless of where it came from. Missing provider operations are explicit capabilities, rather than placeholder implementations that pretend to support every format or query.

After an object is registered, agents use a common catalog and object tools. They do not branch on provider classes. The registry maps stable local IDs to source references; backend code alone resolves credentials, paths, object selectors, and temporary job locations.

## 3. What an object must say

The common descriptor should provide the following information when known:

- Stable identity, revision, owner, name, and scientific role.
- Object kind and schema: columns or axes, dimensions, types, units, and category definitions.
- Observation unit: what a row, column, or matrix axis represents.
- Compact profile: missingness, distributions, key properties, and limitations.
- Relationships to exact object revisions, with relevant axes or keys.
- Available operations and readiness for inspection, materialization, or execution.
- Provenance and which descriptions were supplied, measured, inferred, or corrected by the user.

Domain-specific descriptions belong in extensions. The common contract should not grow a new required field for each scientific domain. Tables, matrices, and fitted models retain their different structures; the interface supplies a common way to discover and inspect them.

Descriptions are data for the agent to interpret, not instructions that can change tool permissions or workflow rules. Model context receives compact profiles and permitted semantic metadata, following the baseline's exclusion of raw rows and identifiers.

## 4. Relationships carry usable meaning

A generic link between two objects is insufficient for reliable execution. Relationships should identify their role and the evidence supporting them. Examples include:

- An annotation table describes the sample axis of a matrix, matched by a particular identifier namespace.
- Two tables can join on specified keys, with a declared one-to-one or many-to-one relationship.
- An imported result was calculated from specified source objects, when the platform supplies that provenance.

Preserve the platform's relationship definitions. Validate the parts used by a run against the selected data: compatible identifier domains, actual matches, key uniqueness, alignment, and changes in row count. Joining identically named columns is not enough evidence that their entities match. Cross-dataset joins use the same checks.

The descriptor distinguishes declared relationships from relationships verified on the selected revision. Unknown information stays unknown. A meaningful unresolved choice goes through the existing question mechanism; it does not require a new approval system.

## 5. Import and upload flows

Platform import follows this sequence:

1. Discover compact collection summaries within the configured project/source scope.
2. Read and normalize the selected platform description, retaining source identities and relationships.
3. Register a dataset revision and expose its objects for inspection.
4. Resolve and inspect only the objects required by an execution plan.

The platform's existing semantic description is the starting point. An LLM may help select relevant objects or explain their meaning, but it should not rewrite an already useful source contract on every import. Re-importing the same source identity and revision is idempotent.

Upload follows this sequence:

1. Collect one or more files into an upload session and retain the originals.
2. Supported parsers extract object structures; local code calculates profiles.
3. The LLM proposes names, meanings, and relationships from these profiles and user context.
4. Validate the proposed manifest and any executable mappings. Ask only for consequential ambiguity that available evidence cannot resolve.
5. Register the dataset revision with the origin and validation state of its descriptions.

The import session groups files provisionally; uploading several files does not prove that they belong to the same cohort. Unsupported objects remain visible with their parser status and can become usable when support is added. Model-generated parsing code, when supported, uses the same isolated execution and validation path as other generated code.

Resolution may materialize only a selected subset when the provider supports it. The selected axes, filters, source revision, and resolved input identity are recorded so lazy access does not erase provenance.

Catalog visibility and execution readiness are separate. A described object may still need local profiling, may require a parser, or may be temporarily unavailable. Readiness is tracked per object so one unsupported file does not hide the useful objects in its dataset.

## 6. Computation produces reusable results

A run can produce an analysis result without producing a figure. Each result records its exact input references, operation, code, parameters, environment, random seed when relevant, and validated output objects. Output files are artifacts; a file alone does not provide the meaning and structure needed for reuse.

Intermediate filtering and joins can remain temporary. Outputs needed by a saved figure, explicitly requested by the user, or declared as reusable outputs of the execution plan are retained. Retention is decided as part of the plan, not by saving every temporary file. Small statistics may be stored as structured values; larger outputs use artifact references.

Successful analysis outputs can be committed before figure rendering. If rendering fails, the validated result remains available and the last successful figure stays visible. Failed or incomplete outputs are not presented as successful reusable results.

Later runs may consume result objects through the same inspection and materialization interface as dataset objects. This supports “use that model for another figure” without creating another dataset. The Results view exposes these outputs, including ones without a plot.

## 7. Data versions are part of figure history

A stable source ID does not guarantee stable content. Dataset revisions pin object content and the semantic description used to interpret it. A correction to units or relationships creates a new revision even when the underlying bytes are unchanged. Earlier results retain their original references.

Prefer immutable revisions supplied by the analysis platform. When a source cannot retrieve a previous revision, retain a managed snapshot of selected inputs if supported, or report that historical recomputation is unavailable. A fingerprint can detect a change but cannot reconstruct old data. Cached profiles must be tied to the revisions they describe.

Saved artifacts can remain viewable even when historical inputs cannot be retrieved. Browsing or restoring an old figure uses its recorded artifacts and context; recomputation has a separate readiness check and must never substitute the latest source data silently.

References from saved figures protect the analysis results and artifacts they need from cleanup. Temporary execution files can be removed. Removing a source connection can affect future resolution without erasing an already saved figure.

## 8. Reuse follows actual dependencies

Separate analysis inputs and parameters from figure presentation settings. A change to title, colors, or label size can reuse an existing analysis result when the renderer's declared dependencies permit it. A change to the selected observations, statistical method, or analysis parameters requires a corresponding new result.

Begin with explicit result references and recorded execution dependencies inside the existing run coordinator. A new general workflow engine is unnecessary. Broader caching can follow once input revisions, code, parameters, environment, and determinism are represented accurately.

A model's claim that an output is reusable is insufficient by itself. The coordinator validates its dependencies and capability declarations. Unknown dependencies cannot support an automatic reuse decision.

## 9. Agent interaction

The agent should receive a compact workspace index and expand only the relevant parts:

| Tool responsibility | Information returned                                                          |
| ------------------- | ----------------------------------------------------------------------------- |
| Current data        | Scoped dataset summaries, current selection, readiness, and candidate objects |
| Describe dataset    | Objects, scientific descriptions, revisions, and relationships                |
| Inspect object      | Schema, compact profile, relevant relationships, and supported operations     |
| Current results     | Reusable analysis results and saved figures, with input provenance            |
| Execute plan        | Validated result references, artifacts, summaries, and execution status       |

These are source-independent responsibilities, not a separate tool set for each provider. Large catalogs are filtered and paginated; a result includes scope and completeness information so an empty or partial response is not mistaken for proof that no data exists.

The coordinator validates project scope and execution readiness. A run explicitly records its selected object revisions, rather than relying on a mutable “current dataset.” Selection does not discard other compatible objects needed for a join. Asking a question or discussing an existing result does not require starting an execution run.

The data agent resolves selection and mappings. The plot agent can request transformations and analysis through the existing controlled code-execution path. The backend checks that produced objects actually match their declared output descriptions before exposing them for reuse.

## 10. Workspace behavior

Datasets belong to the project; a figure's Data tab explains the exact subset and revisions it used. Add a compact data selector near the conversation input, opening an import/upload and selection panel without adding another permanently open workspace column.

The existing Data tab shows object names, relationships used, input revision, and relevant transformations. Results shows saved analysis outputs with actions to inspect, download, or use in another figure. Figure history restores the corresponding input and result references along with the plot parameters.

New inputs do not silently replace the inputs of an existing figure. Demo use stays explicit and labeled. Missing or unsupported research data produces a specific readiness explanation, never a demonstration substitute.

## 11. Example: one dataset, several figures

An imported treatment study contains an expression matrix, a sample-annotation table, and existing analysis outputs. The platform already declares how sample identifiers connect the matrix and annotations.

For a request to compare expression by treatment, the agent selects the relevant objects and mapping. The backend validates their alignment, then executes the required transformation and calculation. A validated analysis result retains the comparison table and its provenance. The figure references that result and the selected source revisions.

Changing colors creates another figure version using the same valid result. Changing the grouping variable creates another analysis result and a corresponding figure version. A request for a second plot can reuse the comparison table explicitly. The project's dataset library still contains the one imported study.

## 12. Implementation sequence

1. Establish the common dataset/object contract and registry. Normalize one representative platform collection and one uploaded collection containing related objects. Preserve existing selected bundle references through the API boundary.
2. Connect discovery, profiling, object relationships, and selection to agent tools and the data selector. Validate that the same object tools serve both sources.
3. Connect isolated execution to exact input references and typed result outputs. Exercise one real request requiring a join or calculation followed by a plot. Support a result-only request through the same run machinery.
4. Connect result reuse, parameter dependency handling, and figure history to pinned revisions. Add further formats and operations through parser and capability implementations.

Discovery alone does not complete real-data plotting. The first usable delivery must include retrieval, execution, validation, and saved results for representative supported objects. Public request/response schemas and OpenAPI must be updated alongside their backend and frontend implementations.

The registry, both provider interfaces, upload interpretation, lazy platform resolution, restricted R execution, result contracts, and workspace integration are implemented. The live platform connection still requires its API URL and representative response; the adapter is tested against the documented source contract. Provider-side subset pushdown, broad automatic caching, additional parsers, and automated scientific/publication review remain outside this initial connected workflow.

## 13. Evidence the design should pass

- A platform collection and an uploaded collection can satisfy the same scientific request through the same agent tools.
- Imported results remain distinguishable from locally computed results while sharing object inspection.
- An invalid or ambiguous join is detected before it produces a misleading successful result.
- A completed analysis result can be reused by another figure without adding a dataset.
- A presentation change reuses its valid analysis inputs; a changed analysis dependency produces a new result.
- A source update or metadata correction does not silently change a historical figure's inputs.
- An unsupported object or unavailable source is reported accurately, while other usable objects remain discoverable.
- Failed rendering preserves valid analysis results and the previous successful figure.
- Large or partially available catalogs report what was searched without flooding the model context.

A representative platform manifest and its revision/retrieval behavior will refine the adapter implementation. They should not change these domain boundaries.
