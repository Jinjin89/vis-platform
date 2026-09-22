# Vis Platform frontend

The frontend is a separate React application. It communicates with the backend only through the versioned API under /api/v1.

## Development

```sh
npm install
npm run dev
```

Vite proxies /api requests to http://localhost:18080 during development.

The development server listens on 0.0.0.0. Open http://SERVER_IP:5173 from another computer on the same trusted network.

## Report interface

Open `/report` or choose **Report** in the header. Use one natural-language input
to write, plot, or reorganize the report. The backend chooses intent and placement;
clicking a section or figure supplies an optional context hint. The v2 report
contract supports first-level sections and second-level subsections with stable
IDs, atomic document operations, and shared plot metadata. Legacy pre-reports
remain importable. See [the report guide](../docs/REPORT_UI.md).

## Figure interface

Open `/figure` or choose **Figure** in the header to build a publication figure from data, from saved plots and images, or both. `features/figures/` holds the page canvas (dragging, snapping, scaling, keyboard nudges, free reshaping of slots), the inspector, the legend editor, and dialogs; `figureGeometry.ts` holds the pure layout helpers. A slot's progress comes from the figure conversation, and **Create plot** or **Retry** sends a message that fills the slot without planning. Edits are sent as figure operations, and labels, bounds, and page height come from the backend. `FigureAssistantPanel` shows the figure conversation and reuses the report status card for plot-agent questions and approvals. See [the figure guide](../docs/FIGURE_UI.md).

## Pinpoint interface

Open `/pinpoint` or choose **Pinpoint** in the header to mark points and areas on a plot and talk about them. `features/pinpoint/` holds the stage (click to mark a point, drag to mark an area; positions are fractions of the image), the conversation, the request tracker, and the browser-local conversation per plot. Requests are assistant turns with `plot_marks` (`api/pinpoint.ts`); the report status card shows plot-agent questions and approvals. See [the Pinpoint guide](../docs/PINPOINT_UI.md).

## Canvas interface

The header switches between `/workspace` and `/canvas`. The canvas reuses the dataset picker and figure inspector, adds directional plotting branches and pan/zoom navigation, and keeps parameter edits as per-node drafts. A project can have several canvases; their layouts and pending request references persist in this browser. See [the canvas guide](../docs/CANVAS_UI.md) for details and API additions.

## Figure workspace

Completed figures expose a tabbed panel beneath the canvas. Parameters renders the selected version's backend-provided control definitions; Data shows recorded provenance and logical inputs; Results shows the caption, validation, and downloadable artifact. Parameter edits are drafts until Apply and are submitted as typed changes, not rewritten as chat instructions.

History loads saved versions for the current project and figure. Browsing a version also loads its recorded parameter values. Restore creates a new version; execution failures keep the previous figure visible. Older versions without supported control metadata remain read-only.

## Window layout and planner activity

The main workspace fits the viewport. The figure scales within its canvas; the grouped parameter panel keeps Apply visible. Only long control lists or conversation history scroll. Smaller screens use Figure and Conversation tabs, while the message composer stays within the window.

Each request displays an inline Activity block with real backend actor/tool information and brief decision summaries. Planner questions use explicit choices or custom text and resume the same request. After a refresh, the saved conversation is rebuilt from the backend's authoritative state and reconnects to a request still in progress. Developer diagnostics remain inside expanded Activity and require the server trace token.

## Saved work

`app/useProject.ts` remembers the study in browser local storage for every interface and checks that the backend still has it. `components/SessionSidebar.tsx` is the fixed, collapsible list of saved work beside each interface: Workspace conversations, canvases, reports, presentations, and figures. The open item is a search parameter (`session` in Workspace, `id` elsewhere); the document libraries open their create dialog for `new`. `features/plot-run/conversationHistory.ts` rebuilds a saved Workspace conversation, and `WorkspacePage` keeps a new conversation on screen when its first message saves it.

## Browser verification

Install the browser once, then run the isolated end-to-end suite:

```sh
npx playwright install --with-deps chromium
npm run test:browser
```

The tests start their own backend on port 18188 and frontend on port 5178, using temporary storage and a deterministic test agent. They exercise the real HTTP, activity, question, persistence, and rendering paths at desktop, laptop, and phone viewport sizes. Browser artifacts stay in ignored test-results directories.

`VIS_PLATFORM_BACKEND_ORIGIN` can override Vite's development proxy target; its default remains `http://localhost:18080`. Local browser-test traffic should bypass any external proxy configured on the host.
