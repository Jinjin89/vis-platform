# Plot reference images

The workspace has two separate input actions:

- **Data**, above the conversation, opens the existing dataset and analysis selector. Uploads here create scientific inputs through the data workflow.
- **Add image**, inside the message composer, attaches a plot reference. The same flow accepts pasted images and images dropped onto the composer.

Choose data, add an example plot, and describe the result you want. There are no image-purpose or style-mode selectors. The assistant interprets the requested appearance from your message and the image; numerical results still come from the selected data or saved analysis.

## Current behavior

Reference uploads accept PNG, JPEG, and static WebP, up to 10 MiB each and three images per message. Each upload is decoded and checked for size, animation, and corruption. Orientation is applied, transparency is placed on white, metadata is removed, and a PNG with a longest side of at most 2048 pixels is saved with a thumbnail. Decoded inputs are limited to 25 million pixels and each model image to 4 MiB.

The composer shows upload status, retry, removal, and a larger image preview. Send waits until all attached images are ready. A failed submission preserves the text and images. Upload and submission retries use stable idempotency keys. Data selection remains after Send.

An image-only message asks for a plot based on the reference, or restyles an active figure. Missing data never authorizes invented research values or implicit demonstration data. Fixed demonstration renderers cannot reproduce arbitrary reference images; reference-guided generation requires a real dataset or a saved analysis and the restricted R runtime.

Both the intent model and the R planning model receive prepared image content blocks. The planner records visible design details in its existing appearance/description fields, and keeps the actual pixels available during code generation. Rendering changes that cannot be expressed through saved controls regenerate the rendering plan while reusing the figure's analysis result. A visual refinement cannot introduce a new analysis result.

Requests, pending questions, and saved figure versions retain image IDs. Clarification after refresh or a backend restart reloads the same images. Parameter changes inherit references and restore copies the selected version's references. Recent conversation image IDs remain available for explicit follow-ups. New unrelated figures do not automatically inherit an earlier figure's images.

## API

All paths are under `/api/v1`.

| Method and path                                                         | Behavior                                                                                    |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `POST /projects/{project_id}/plot-reference-images?name=example.png`    | Upload a binary body using `application/octet-stream`; returns image metadata with HTTP 201 |
| `GET /projects/{project_id}/plot-reference-images/{image_id}`           | Read public metadata                                                                        |
| `GET /projects/{project_id}/plot-reference-images/{image_id}/content`   | Read the normalized PNG                                                                     |
| `GET /projects/{project_id}/plot-reference-images/{image_id}/thumbnail` | Read the thumbnail PNG                                                                      |
| `DELETE /projects/{project_id}/plot-reference-images/{image_id}`        | Remove an unused upload; referenced images return 409                                       |

Pass an optional `Idempotency-Key` on uploads and assistant submissions. Repeating an identical request returns the original image or turn. Reusing a key for a different payload returns 409.

The normal assistant request adds image IDs to the shared request object:

```json
{
  "schema_version": "1.0",
  "project_id": "project_example",
  "request": {
    "text": "Make a plot like this using my measurements.",
    "reference_image_ids": ["ref_example"]
  },
  "data_scope": {
    "mode": "selected",
    "bundle_ids": ["dataset_example"]
  }
}
```

An omitted/null image list permits reference inheritance for refinement; an empty list explicitly clears reference guidance. A nonempty list selects those images for the operation. The intent planner can resolve explicitly referenced earlier images from the supplied project context. `request.text` can be empty only when the request contains images.

`AssistantTurnSnapshot.reference_images` provides submitted-image descriptors for recovery. `PlotResultSummary.reference_images` records the effective images for a saved version. Old records default to empty lists. Descriptors contain IDs, project ID, name, dimensions, byte count, creation time, and scoped API links.

Public direct plot-run calls cannot bypass image planning: requests containing reference images must enter through the assistant gateway. The coordinator validates image ownership again before executing the resulting plan. The existing parameter and restore endpoints preserve reference context.

## Storage and model boundary

Image metadata and retention links live in SQLite. Prepared PNGs and thumbnails live in backend-managed storage, separately from the dataset registry. The frontend receives only IDs and versioned API links. Images are supplied directly to the model by the backend; API image URLs are not handed to an external provider for retrieval.

Reference IDs are pinned transactionally with accepted requests and runs. Deleting a used image is blocked so history remains reproducible. Unused uploads older than 24 hours are eligible for cleanup at startup and after uploads. Project ownership is checked on upload, lookup, deletion, and execution. The project's existing lack of user authentication is unchanged.

Image bytes and encoded content are excluded from public progress events and developer traces. Reference pixels are not R inputs. The R worker continues to render actual saved data/results using its existing isolation and artifact checks.

## Remaining design work

This first implementation combines visual understanding with the existing intent and code-planning calls. A separate inspection service, persistent structured visual briefs, automatic reference/result comparison, and a bounded visual repair loop remain proposed in [PLOT_REFERENCES_DESIGN.md](PLOT_REFERENCES_DESIGN.md).

Original full-resolution files are not retained in this first version; the normalized image is the durable reference. Cropping, SVG/PDF/GIF reference input, digitizing values from screenshots, and provider-side file caching are not implemented. A reference match is not a scientific/publication review or a guarantee of pixel-identical reproduction.

Backend and frontend must be deployed together because frontend response validators are strict. Pydantic models and generated OpenAPI/TypeScript contracts define the implemented fields; examples in the extended proposal are future design sketches.
