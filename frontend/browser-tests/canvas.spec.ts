import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import type { CanvasGraph } from "../src/features/infinite-canvas/model";

test.use({ actionTimeout: 10000 });

async function graph(page: Page): Promise<CanvasGraph> {
  return page.evaluate(() =>
    JSON.parse(
      localStorage.getItem(
        "vis-platform.canvas.v1." +
          sessionStorage.getItem("vis-platform.project-id"),
      )!,
    ),
  );
}
async function addDataset(page: Page) {
  await page.goto("/canvas");
  await page.getByRole("button", { name: "Choose data" }).click();
  await page.getByRole("tab", { name: "Upload", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Dataset name" })
    .fill("Treatment study");
  await page.getByLabel(/^Data files/).setInputFiles([
    {
      name: "observations.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("sample_id,value\ns1,1\ns2,3\ns3,5\ns4,7\n"),
    },
    {
      name: "samples.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("sample_id,group\ns1,A\ns2,A\ns3,B\ns4,B\n"),
    },
  ]);
  await page.getByRole("button", { name: "Upload & inspect" }).click();
  await expect(
    page.getByRole("tab", { name: "Datasets", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await expect(
    page.getByRole("textbox", { name: "Describe a new plot" }),
  ).toBeEnabled();
}
async function createPlot(page: Page, text = "Compare treatment group means") {
  await page.getByRole("textbox", { name: "Describe a new plot" }).fill(text);
  await page
    .getByRole("form", { name: "Canvas plot instructions" })
    .getByRole("button", { name: "Create plot", exact: true })
    .click();
}
async function selectNode(page: Page, label: string) {
  const toggle = page.getByRole("button", { name: "Outline", exact: true });
  if ((await toggle.getAttribute("aria-pressed")) !== "true")
    await toggle.click();
  await page
    .getByRole("navigation", { name: "Canvas nodes" })
    .getByRole("button")
    .filter({
      has: page.locator("b", { hasText: new RegExp("^" + label + "$") }),
    })
    .click();
}
async function expectReady(page: Page, count: number) {
  await expect(
    page.locator(".canvas-node .canvas-node-status[data-status=completed]"),
  ).toHaveCount(count, { timeout: 25000 });
}

test("canvas creates independent R branches, preserves drafts and parents, and exports code", async ({
  page,
}, info) => {
  test.setTimeout(60000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await addDataset(page);
  await expect(page.locator(".canvas-dataset-preview")).toContainText(
    "sample_id",
  );
  await createPlot(page);
  await expect(
    page.locator(".canvas-node .canvas-node-status[data-status=running]"),
  ).toHaveCount(1);
  await page.reload();
  await expectReady(page, 1);
  await expect.poll(async () => (await graph(page)).nodes.length).toBe(2);
  // Canvas persists after rendering; wait for the completed snapshot before capturing it.
  await expect
    .poll(async () => {
      const node = (await graph(page)).nodes.find((n) => n.type === "plot");
      return node?.type === "plot" ? node.snapshot?.result?.version_id : null;
    })
    .toBeTruthy();
  const original = (await graph(page)).nodes.find((n) => n.type === "plot")!;
  if (original.type !== "plot") throw new Error("Missing plot");

  await page
    .getByRole("combobox", { name: "Color", exact: true })
    .selectOption("steelblue");
  await page
    .getByRole("textbox", { name: "Describe a refinement" })
    .fill("Use blue for the groups");
  await selectNode(page, "D1");
  await createPlot(page, "Create a second independent comparison");
  await expectReady(page, 2);
  await selectNode(page, "P1");
  await expect(
    page.getByRole("combobox", { name: "Color", exact: true }),
  ).toHaveValue("steelblue");
  await expect(
    page.getByRole("textbox", { name: "Describe a refinement" }),
  ).toHaveValue("Use blue for the groups");
  await page
    .getByRole("form", { name: "Canvas plot instructions" })
    .getByRole("button", { name: "Create refinement" })
    .click();
  await expectReady(page, 3);
  await expect(page.locator(".canvas-connections g")).toHaveCount(3);
  await expect
    .poll(
      async () =>
        (await graph(page)).nodes.filter(
          (n) => n.type === "plot" && n.status === "completed",
        ).length,
    )
    .toBe(3);
  const saved = await graph(page);
  const plots = saved.nodes.filter((n) => n.type === "plot");
  expect(plots[0]!.parameters.color).toBe("purple");
  expect(plots[1]!.parentPlotId).toBeNull();
  expect(plots[2]!.parentPlotId).toBe(plots[0]!.id);
  expect(plots[2]!.parameters.color).toBe("steelblue");
  const history = await page.request.get(
    `/api/v1/projects/${saved.projectId}/plots/${original.snapshot!.result!.plot_id}/versions`,
  );
  const versions = (await history.json()).versions;
  expect(versions).toHaveLength(2);
  expect(versions[0].parent_version_id).toBe(
    original.snapshot!.result!.version_id,
  );

  await page.getByRole("button", { name: "R code", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "Complete R plotting code" }),
  ).toContainText("plot_main");
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export .R", exact: true }).click();
  const download = await downloadEvent;
  const code = await readFile((await download.path())!, "utf8");
  expect(code).toContain("barplot");
  expect(code).toContain("steelblue");
  expect(code).toContain("grDevices::svg");

  await page.getByRole("link", { name: "Workspace", exact: true }).click();
  await expect(
    page.getByRole("textbox", { name: "Describe the plot you want" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Canvas", exact: true }).click();
  await expectReady(page, 3);
  await page.getByRole("button", { name: "Close node preview" }).click();
  await page.getByRole("button", { name: "Fit all nodes" }).click();
  await page.screenshot({ path: info.outputPath("plot-canvas.png") });
  expect(errors).toEqual([]);
});

test("canvas drag, pan, zoom, and refresh retain positions", async ({
  page,
}) => {
  await addDataset(page);
  const card = page.locator(".canvas-node[data-kind=data]");
  const box = (await card.boundingBox())!;
  await expect.poll(async () => (await graph(page)).nodes.length).toBe(1);
  const before = (await graph(page)).nodes[0]!.position;
  await page.mouse.move(box.x + 40, box.y + 20);
  await page.mouse.down();
  await page.mouse.move(box.x + 140, box.y + 70, { steps: 5 });
  await page.mouse.up();
  await expect
    .poll(async () => (await graph(page)).nodes[0]!.position.x)
    .toBeCloseTo(before.x + 100);
  await page.getByRole("button", { name: "Zoom in canvas" }).click();
  await expect(page.getByLabel("Canvas zoom")).toHaveText("120%");
  const viewport = page.getByRole("region", {
    name: "Infinite plotting canvas",
  });
  await viewport.focus();
  await page.keyboard.press("ArrowLeft");
  await expect.poll(async () => (await graph(page)).viewport.zoom).toBe(1.2);
  const saved = await graph(page);
  await page.reload();
  await expect(card).toBeVisible();
  await expect(page.getByLabel("Canvas zoom")).toHaveText("120%");
  expect((await graph(page)).nodes[0]!.position).toEqual(
    saved.nodes[0]!.position,
  );
});

test("planner questions survive refresh and failed R execution stays on its own node", async ({
  page,
}) => {
  test.setTimeout(60000);
  await addDataset(page);
  await createPlot(
    page,
    "Compare means, but ask me about the comparison first",
  );
  await expect(
    page.getByRole("form", { name: "Question from the planner" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("form", { name: "Question from the planner" }),
  ).toBeVisible();
  await page.getByRole("radio", { name: /The full distribution/ }).check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expectReady(page, 1);
  await selectNode(page, "D1");
  await createPlot(page, "Fail execution to exercise R error handling");
  await expect(
    page.locator(".canvas-node .canvas-node-status[data-status=failed]"),
  ).toHaveCount(1, { timeout: 25000 });
  await expectReady(page, 1);
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Reuse these instructions" }),
  ).toBeVisible();
});

test("canvas and right panel remain usable on a narrow screen", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await addDataset(page);
  await expect(
    page.getByRole("textbox", { name: "Describe a new plot" }),
  ).toBeInViewport();
  await expect(
    page.getByRole("complementary", { name: "Node preview" }),
  ).toBeInViewport();
  await createPlot(page);
  await expectReady(page, 1);
  await expect(
    page.getByRole("textbox", { name: "Describe a refinement" }),
  ).toBeInViewport();
  const metrics = await page.locator(".canvas-shell").evaluate((element) => ({
    width: element.clientWidth,
    scrollWidth: element.scrollWidth,
    height: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }));
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.width + 1);
  expect(metrics.scrollHeight).toBeLessThanOrEqual(metrics.height + 1);
  await page.screenshot({ path: info.outputPath("canvas-mobile.png") });
});
