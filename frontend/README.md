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

Open `/figure` or choose **Figure** in the header to compose saved plots and images into a publication figure. `features/figures/` holds the page canvas (dragging, snapping, scaling, keyboard nudges), the inspector, the legend editor, and dialogs; `figureGeometry.ts` holds the pure layout helpers. Edits are sent as figure operations, and labels, bounds, and page height come from the backend. See [the figure guide](../docs/FIGURE_UI.md).

## Canvas interface

The header switches between `/workspace` and `/canvas`. The canvas reuses the dataset picker and figure inspector, adds directional plotting branches and pan/zoom navigation, and keeps parameter edits as per-node drafts. Layout and pending request references persist in this browser. See [the canvas guide](../docs/CANVAS_UI.md) for details and API additions.

## Figure workspace

Completed figures expose a tabbed panel beneath the canvas. Parameters renders the selected version's backend-provided control definitions; Data shows recorded provenance and logical inputs; Results shows the caption, validation, and downloadable artifact. Parameter edits are drafts until Apply and are submitted as typed changes, not rewritten as chat instructions.

History loads saved versions for the current project and figure. Browsing a version also loads its recorded parameter values. Restore creates a new version; execution failures keep the previous figure visible. Older versions without supported control metadata remain read-only.

## Window layout and planner activity

The main workspace fits the viewport. The figure scales within its canvas; the grouped parameter panel keeps Apply visible. Only long control lists or conversation history scroll. Smaller screens use Figure and Conversation tabs, while the message composer stays within the window.

Each request displays an inline Activity block with real backend actor/tool information and brief decision summaries. Planner questions use explicit choices or custom text and resume the same request. Pending requests are saved in browser session storage and recovered through the backend's authoritative state after refresh. Developer diagnostics remain inside expanded Activity and require the server trace token.

## Browser verification

Install the browser once, then run the isolated end-to-end suite:

```sh
npx playwright install --with-deps chromium
npm run test:browser
```

The tests start their own backend on port 18188 and frontend on port 5178, using temporary storage and a deterministic test agent. They exercise the real HTTP, activity, question, persistence, and rendering paths at desktop, laptop, and phone viewport sizes. Browser artifacts stay in ignored test-results directories.

`VIS_PLATFORM_BACKEND_ORIGIN` can override Vite's development proxy target; its default remains `http://localhost:18080`. Local browser-test traffic should bypass any external proxy configured on the host.
