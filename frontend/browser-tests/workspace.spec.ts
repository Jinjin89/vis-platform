import { readFile } from "node:fs/promises";
import { expect, test, type Page, type TestInfo } from "@playwright/test";
import type { PlotRunSnapshot } from "../src/api/schemas/plotRun";

async function generate(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /Compare distributions/ }).click();
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.locator(".plot-preview")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Apply as new version" }),
  ).toBeVisible();
  await page.waitForFunction(() => {
    const image = document.querySelector<HTMLImageElement>(".plot-preview");
    return image?.complete && image.naturalWidth > 0;
  });
}

async function fitsWindow(page: Page) {
  const metrics = await page.evaluate(() => {
    return [
      "html",
      "body",
      ".app-shell",
      ".workspace-layout",
      ".plot-area",
      ".canvas-workbench",
      ".figure-panels",
    ].map((selector) => {
      const element = document.querySelector<HTMLElement>(selector)!;
      return {
        selector,
        width: element.clientWidth,
        height: element.clientHeight,
        scrollWidth: element.scrollWidth,
        scrollHeight: element.scrollHeight,
      };
    });
  });
  for (const metric of metrics) {
    expect(
      metric.scrollWidth,
      metric.selector + " horizontal overflow",
    ).toBeLessThanOrEqual(metric.width + 2);
    expect(
      metric.scrollHeight,
      metric.selector + " vertical overflow",
    ).toBeLessThanOrEqual(metric.height + 2);
  }
}

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 1024, height: 768 },
  { width: 390, height: 844 },
]) {
  test(`figure and controls fit ${viewport.width} × ${viewport.height}`, async ({
    page,
  }, info) => {
    await page.setViewportSize(viewport);
    await generate(page);
    await fitsWindow(page);
    const apply = await page
      .getByRole("button", { name: "Apply as new version" })
      .boundingBox();
    expect(apply!.y + apply!.height).toBeLessThanOrEqual(viewport.height);
    await expect(
      page.getByRole("spinbutton", { name: "Figure width", exact: true }),
    ).toBeInViewport({ ratio: 1 });
    await expect(
      page.getByRole("spinbutton", { name: "Figure height", exact: true }),
    ).toBeInViewport({ ratio: 1 });
    if (viewport.width >= 1280) {
      await expect(
        page.getByRole("combobox", { name: "Palette" }),
      ).toBeInViewport({ ratio: 1 });
      const fieldsFit = await page
        .locator(".parameter-fields-scroll")
        .evaluate(
          (element) => element.scrollHeight <= element.clientHeight + 2,
        );
      expect(fieldsFit).toBe(true);
    }
    const before = await page.locator(".figure-stage-viewport").boundingBox();
    await page
      .getByRole("button", { name: "Collapse figure controls" })
      .click();
    const expanded = await page.locator(".figure-stage-viewport").boundingBox();
    expect(expanded!.height).toBeGreaterThan(before!.height);
    await page.getByRole("button", { name: "Expand figure controls" }).click();
    await page.screenshot({ path: info.outputPath("workspace.png") });
    if (viewport.width <= 820)
      await page
        .getByRole("button", { name: "Conversation", exact: true })
        .click();
    const input = await page
      .getByRole("textbox", { name: "Describe the plot you want" })
      .boundingBox();
    expect(input!.y + input!.height).toBeLessThanOrEqual(viewport.height);
    await page
      .getByRole("textbox", { name: "Describe the plot you want" })
      .fill("Explain the distribution in detail");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(
      page.getByText("Shape and spread", { exact: true }),
    ).toBeVisible();
    await fitsWindow(page);
    const messageSize = await page
      .locator(".message-content")
      .last()
      .evaluate((element) => parseFloat(getComputedStyle(element).fontSize));
    expect(messageSize).toBeGreaterThanOrEqual(14);
    const composer = await page.locator(".conversation-compose").boundingBox();
    expect(composer!.y + composer!.height).toBeLessThanOrEqual(viewport.height);
  });
}

test("agent activity comes from the backend and questions resume after reload", async ({
  page,
}, info) => {
  await page.goto("/");
  await page
    .getByRole("textbox", { name: "Describe the plot you want" })
    .fill("Use demonstration data, but ask me about the comparison first");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(
    page.getByRole("form", { name: "Question from the planner" }),
  ).toBeVisible();
  await page.locator(".agent-activity > summary").last().click();
  await expect(page.getByText("Intent planner", { exact: true })).toBeVisible();
  await expect(
    page.getByText("get_current_data", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("get_current_results", { exact: true }),
  ).toBeVisible();
  const identity = await page.evaluate(
    () =>
      JSON.parse(sessionStorage.getItem("vis-platform.pending-assistant")!)
        .accepted.turn_id,
  );
  await page.screenshot({ path: info.outputPath("planner-question.png") });
  await page.reload();
  await expect(
    page.getByRole("form", { name: "Question from the planner" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () =>
        JSON.parse(sessionStorage.getItem("vis-platform.pending-assistant")!)
          .accepted.turn_id,
    ),
  ).toBe(identity);
  const option = page.getByRole("radio", { name: /The full distribution/ });
  await expect(option).not.toBeChecked();
  await option.check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.locator(".plot-preview")).toBeVisible();
  await page.locator(".agent-activity > summary").last().click();
  await expect(page.getByText("Plot renderer", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Save figure version", { exact: true }),
  ).toBeVisible();
  await fitsWindow(page);
  await page.screenshot({ path: info.outputPath("planner-completed.png") });
});

async function resize(page: Page, name: string, dx: number, dy: number) {
  const handle = page.getByRole("separator", { name });
  const rect = (await handle.boundingBox())!;
  await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2);
  await page.mouse.down();
  await page.mouse.move(
    rect.x + rect.width / 2 + dx,
    rect.y + rect.height / 2 + dy,
    { steps: 8 },
  );
  await page.mouse.up();
}

async function panelSize(
  page: Page,
  selector: string,
  dimension: "width" | "height",
) {
  return (await page.locator(selector).boundingBox())![dimension];
}

test("panel dividers resize independently, respect bounds, and retain preferences", async ({
  page,
}, info) => {
  await generate(page);
  const initialWidth = await panelSize(page, ".conversation-panel", "width");
  const initialHeight = await panelSize(page, ".figure-inspector", "height");
  await resize(page, "Resize conversation panel", -100, 0);
  await expect
    .poll(() => panelSize(page, ".conversation-panel", "width"))
    .toBeCloseTo(initialWidth + 100, 0);
  expect(await panelSize(page, ".figure-inspector", "height")).toBeCloseTo(
    initialHeight,
    0,
  );
  await resize(page, "Resize figure controls", 0, -80);
  await expect
    .poll(() => panelSize(page, ".figure-inspector", "height"))
    .toBeCloseTo(initialHeight + 80, 0);
  await page.getByRole("button", { name: "Collapse figure controls" }).click();
  expect(await panelSize(page, ".figure-inspector", "height")).toBeCloseTo(
    44,
    0,
  );
  await page.getByRole("button", { name: "Expand figure controls" }).click();
  expect(await panelSize(page, ".figure-inspector", "height")).toBeCloseTo(
    initialHeight + 80,
    0,
  );
  await fitsWindow(page);
  await page.reload();
  await expect
    .poll(() => panelSize(page, ".conversation-panel", "width"))
    .toBeCloseTo(initialWidth + 100, 0);
  await generate(page);
  expect(await panelSize(page, ".figure-inspector", "height")).toBeCloseTo(
    initialHeight + 80,
    0,
  );
  const horizontal = page.getByRole("separator", {
    name: "Resize conversation panel",
  });
  const vertical = page.getByRole("separator", {
    name: "Resize figure controls",
  });
  await horizontal.focus();
  await page.keyboard.press("ArrowRight");
  await expect
    .poll(() => panelSize(page, ".conversation-panel", "width"))
    .toBeCloseTo(initialWidth + 84, 0);
  await vertical.focus();
  await page.keyboard.press("ArrowDown");
  await expect
    .poll(() => panelSize(page, ".figure-inspector", "height"))
    .toBeCloseTo(initialHeight + 64, 0);
  await page.screenshot({ path: info.outputPath("resized-workspace.png") });
  await resize(page, "Resize conversation panel", -2000, 0);
  await resize(page, "Resize figure controls", 0, -2000);
  expect(await panelSize(page, ".plot-area", "width")).toBeGreaterThanOrEqual(
    360,
  );
  expect(
    await panelSize(page, ".canvas-workbench", "height"),
  ).toBeGreaterThanOrEqual(159);
  await page.setViewportSize({ width: 900, height: 600 });
  await fitsWindow(page);
  expect(
    await panelSize(page, ".canvas-workbench", "height"),
  ).toBeGreaterThanOrEqual(159);
  await resize(page, "Resize conversation panel", 2000, 0);
  await resize(page, "Resize figure controls", 0, 2000);
  expect(await panelSize(page, ".conversation-panel", "width")).toBeCloseTo(
    310,
    0,
  );
  expect(await panelSize(page, ".figure-inspector", "height")).toBeCloseTo(
    160,
    0,
  );
  await fitsWindow(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await horizontal.dblclick();
  await vertical.dblclick();
  await expect
    .poll(() => panelSize(page, ".conversation-panel", "width"))
    .toBeCloseTo(initialWidth, 0);
  await expect
    .poll(() => panelSize(page, ".figure-inspector", "height"))
    .toBeCloseTo(initialHeight, 0);
});

for (const width of [1440, 390]) {
  test(`history stays beside the figure and switches saved values at ${width}px`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await generate(page);
    await expect(
      page.getByRole("tablist", { name: "Parameter sections" }),
    ).toHaveCount(0);
    const originalTitle = await page
      .getByRole("textbox", { name: "Title", exact: true })
      .inputValue();
    const originalPreview = await page
      .locator(".plot-preview")
      .getAttribute("src");
    await page
      .getByRole("textbox", { name: "Title", exact: true })
      .fill("Adjusted treatment response");
    await page.getByRole("button", { name: "Apply as new version" }).click();
    await expect(page.locator(".plot-preview")).not.toHaveAttribute(
      "src",
      originalPreview!,
    );
    const newerPreview = await page
      .locator(".plot-preview")
      .getAttribute("src");
    await page.getByRole("button", { name: "History", exact: true }).click();
    const newer = page.getByRole("button", { name: /Version 2 · Current/ });
    const older = page.getByRole("button", { name: /Version 1/ });
    await expect(newer).toHaveAttribute("aria-pressed", "true");
    await older.click();
    await expect(
      page.getByRole("textbox", { name: "Title", exact: true }),
    ).toHaveValue(originalTitle);
    await expect(page.locator(".plot-preview")).toHaveAttribute(
      "src",
      originalPreview!,
    );
    await expect(older).toHaveAttribute("aria-pressed", "true");
    await newer.click();
    await expect(
      page.getByRole("textbox", { name: "Title", exact: true }),
    ).toHaveValue("Adjusted treatment response");
    await expect(page.locator(".plot-preview")).toHaveAttribute(
      "src",
      newerPreview!,
    );
    await page.locator(".plot-preview").click();
    await expect(
      page.getByRole("region", { name: "Figure history" }),
    ).toBeVisible();
    const history = (await page.locator(".figure-history").boundingBox())!;
    const figure = (await page.locator(".plot-canvas").boundingBox())!;
    expect(history.x + history.width).toBeLessThanOrEqual(figure.x);
    await fitsWindow(page);
    if (width < 820) {
      await expect(
        page.getByRole("separator", { name: "Resize conversation panel" }),
      ).toBeHidden();
      const before = await panelSize(page, ".figure-inspector", "height");
      await resize(page, "Resize figure controls", 0, -50);
      expect(await panelSize(page, ".figure-inspector", "height")).toBeCloseTo(
        before + 50,
        0,
      );
      await fitsWindow(page);
    }
    await page.screenshot({ path: info.outputPath("history-sidebar.png") });
    await page.getByRole("button", { name: "Collapse figure history" }).click();
    expect(await panelSize(page, ".plot-canvas", "width")).toBeGreaterThan(
      figure.width,
    );
    await expect(
      page.getByRole("button", { name: "History", exact: true }),
    ).toBeVisible();
  });
}

for (const width of [1440, 390]) {
  test(`uploads related data and reuses a real analysis at ${width}px`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await page
      .getByRole("button", { name: "Choose data", exact: true })
      .click();
    const library = page.getByRole("dialog", { name: "Data & analysis" });
    await expect(library).toBeVisible();
    await library.getByRole("tab", { name: "Upload", exact: true }).click();
    await library.getByLabel("Dataset name").fill("Treatment study");
    await library.getByLabel("Data files").setInputFiles([
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
    await library.getByRole("button", { name: "Upload & inspect" }).click();
    await expect(library.getByText("Ready", { exact: true })).toBeVisible();
    await library.getByText("Objects & relationships", { exact: true }).click();
    await expect(
      library.getByText("observations", { exact: true }),
    ).toBeVisible();
    await expect(library.getByText("samples", { exact: true })).toBeVisible();
    await page.screenshot({ path: info.outputPath("dataset-library.png") });
    await library.getByRole("button", { name: "Done", exact: true }).click();
    await page.reload();
    await expect(page.locator(".conversation-data")).toContainText(
      "Treatment study",
    );
    await page
      .getByRole("textbox", { name: "Describe the plot you want" })
      .fill("Calculate treatment group means without a plot");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    const analysis = page.getByRole("article", {
      name: "Treatment comparison",
      exact: true,
    });
    await expect(analysis).toBeVisible();
    await expect(page.locator(".plot-preview")).toHaveCount(0);
    const download = analysis.getByRole("link", {
      name: "Download table",
      exact: true,
    });
    const csv = await page.request.get((await download.getAttribute("href"))!);
    expect(await csv.text()).toContain('"A",2');
    expect(await csv.text()).toContain('"B",6');
    const projectId = await page.evaluate(() =>
      sessionStorage.getItem("vis-platform.project-id"),
    );
    const before = await (
      await page.request.get(`/api/v1/projects/${projectId}/analysis-results`)
    ).json();
    expect(before.total).toBe(1);
    await analysis.getByRole("button", { name: "Use in a figure" }).click();
    await expect(
      page.getByRole("textbox", { name: "Describe the plot you want" }),
    ).toHaveValue(/saved analysis/);
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(page.locator(".plot-preview")).toBeVisible();
    await page.getByRole("tab", { name: "Results", exact: true }).click();
    await expect(
      page
        .locator(".figure-inspector")
        .getByRole("article", { name: "Treatment comparison" }),
    ).toBeVisible();
    const after = await (
      await page.request.get(`/api/v1/projects/${projectId}/analysis-results`)
    ).json();
    expect(after.total).toBe(1);
    expect(after.results[0].result_id).toBe(before.results[0].result_id);
    expect(
      (
        await (
          await page.request.get(`/api/v1/projects/${projectId}/datasets`)
        ).json()
      ).total,
    ).toBe(1);
    await fitsWindow(page);
    await page.screenshot({ path: info.outputPath("real-data-figure.png") });
  });
}

for (const example of [
  {
    name: "Single-cell transcriptomics · Demo",
    request: "Plot the cell embedding colored by cell type",
    width: 1440,
    outputWidth: 7,
    outputHeight: 7,
  },
  {
    name: "Spatial transcriptomics · Demo",
    request: "Plot the spatial coordinates colored by tissue domain",
    width: 390,
    outputWidth: 8,
    outputHeight: 6,
  },
]) {
  test(`selects ${example.name}, resizes output, and navigates the stage`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width: example.width, height: 900 });
    await page.goto("/");
    await page
      .getByRole("button", { name: "Choose data", exact: true })
      .click();
    const library = page.getByRole("dialog", { name: "Data & analysis" });
    await library
      .getByRole("tab", { name: "Analysis platform", exact: true })
      .click();
    const collection = library.getByRole("article", { name: example.name });
    await expect(collection).toBeVisible();
    await expect(
      collection.getByText("Demo collection", { exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: info.outputPath("platform-demo-collections.png"),
    });
    await collection
      .getByRole("button", { name: "Use demo collection" })
      .click();
    await expect(library.getByText("Ready", { exact: true })).toBeVisible();
    await library.getByRole("button", { name: "Done", exact: true }).click();
    await page
      .getByRole("textbox", { name: "Describe the plot you want" })
      .fill(example.request);
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(page.locator(".plot-preview")).toBeVisible();
    const stage = page.getByRole("region", {
      name: "Figure stage",
      exact: true,
    });
    await expect(stage.getByText("Demo data", { exact: true })).toBeVisible();
    await expect(
      page.getByRole("spinbutton", { name: "Figure width", exact: true }),
    ).toHaveValue(String(example.outputWidth));
    await expect(
      page.getByRole("spinbutton", { name: "Figure height", exact: true }),
    ).toHaveValue(String(example.outputHeight));
    await expect(
      stage.getByText(`${example.outputWidth} × ${example.outputHeight} in`, {
        exact: true,
      }),
    ).toBeVisible();
    const projectId = await page.evaluate(() =>
      sessionStorage.getItem("vis-platform.project-id"),
    );
    const resultBefore = await (
      await page.request.get(`/api/v1/projects/${projectId}/analysis-results`)
    ).json();
    const originalPreview = await page
      .locator(".plot-preview")
      .getAttribute("src");
    await stage
      .getByRole("button", { name: "Actual size", exact: true })
      .click();
    await expect(stage.getByLabel("Figure zoom", { exact: true })).toHaveText(
      "100%",
    );
    await stage.getByRole("button", { name: "Zoom in", exact: true }).click();
    await expect(stage.getByLabel("Figure zoom", { exact: true })).toHaveText(
      "125%",
    );
    const imageBefore = (await page.locator(".plot-preview").boundingBox())!;
    const viewport = stage.getByRole("group", {
      name: /Pan figure with arrow keys/,
    });
    await viewport.focus();
    await page.keyboard.press("ArrowRight");
    expect((await page.locator(".plot-preview").boundingBox())!.x).toBeCloseTo(
      imageBefore.x + 24,
      0,
    );
    const surface = (await viewport.boundingBox())!;
    await page.mouse.move(
      surface.x + surface.width / 2,
      surface.y + surface.height / 2,
    );
    await page.mouse.down();
    await page.mouse.move(
      surface.x + surface.width / 2 - 40,
      surface.y + surface.height / 2 + 24,
      { steps: 6 },
    );
    await page.mouse.up();
    expect((await page.locator(".plot-preview").boundingBox())!.x).toBeCloseTo(
      imageBefore.x - 16,
      0,
    );
    await stage
      .getByRole("button", { name: "Fit figure", exact: true })
      .click();
    await expect(stage).toHaveAttribute("data-view-mode", "fit");
    expect(await page.locator(".plot-preview").getAttribute("src")).toBe(
      originalPreview,
    );
    await fitsWindow(page);
    await page.screenshot({
      path: info.outputPath("transcriptomic-figure-stage.png"),
    });
    const pngExport = await downloadFigure(page, info, "PNG");
    expect(pngExport.readUInt32BE(16)).toBe(example.outputWidth * 300);
    expect(pngExport.readUInt32BE(20)).toBe(example.outputHeight * 300);
    const pdfExport = await downloadFigure(page, info, "PDF");
    expect(pdfExport.subarray(0, 5).toString()).toBe("%PDF-");

    await page
      .getByRole("spinbutton", { name: "Figure width", exact: true })
      .fill("12");
    await page
      .getByRole("spinbutton", { name: "Figure height", exact: true })
      .fill("4");
    await page.getByRole("button", { name: "Apply as new version" }).click();
    await expect(stage.getByText("12 × 4 in", { exact: true })).toBeVisible();
    await expect(page.locator(".plot-preview")).not.toHaveAttribute(
      "src",
      originalPreview!,
    );
    const svg = await (
      await page.request.get(
        (await page.locator(".plot-preview").getAttribute("src"))!,
      )
    ).text();
    expect(svg).toContain('width="12in"');
    expect(svg).toContain('height="4in"');
    const resultAfter = await (
      await page.request.get(`/api/v1/projects/${projectId}/analysis-results`)
    ).json();
    expect(resultAfter.total).toBe(1);
    expect(resultAfter.results[0].result_id).toBe(
      resultBefore.results[0].result_id,
    );
    await fitsWindow(page);
    await page.getByRole("button", { name: "History", exact: true }).click();
    await page.getByRole("button", { name: /Version 1/ }).click();
    await expect(
      stage.getByText(`${example.outputWidth} × ${example.outputHeight} in`, {
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("spinbutton", { name: "Figure width", exact: true }),
    ).toHaveValue(String(example.outputWidth));
    const savedExport = (
      await downloadFigure(page, info, "SVG", "historical-figure")
    ).toString();
    expect(savedExport).toContain(`width="${example.outputWidth}in"`);
    expect(savedExport).toContain(`height="${example.outputHeight}in"`);
    await fitsWindow(page);
  });
}

test("expanded parameter panels keep a clear size area and bounded groups", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await generate(page);
  await resize(page, "Resize conversation panel", 300, 0);
  await resize(page, "Resize figure controls", 0, -190);
  const size = page.getByRole("group", { name: "Figure size", exact: true });
  const appearance = page.getByRole("group", {
    name: "Appearance",
    exact: true,
  });
  const distribution = page.getByRole("group", {
    name: "Distribution",
    exact: true,
  });
  const sizeBounds = (await size.boundingBox())!;
  const appearanceBounds = (await appearance.boundingBox())!;
  const distributionBounds = (await distribution.boundingBox())!;
  expect(sizeBounds.x + sizeBounds.width).toBeLessThan(appearanceBounds.x);
  expect(appearanceBounds.x + appearanceBounds.width).toBeLessThan(
    distributionBounds.x,
  );
  expect(appearanceBounds.width).toBeLessThanOrEqual(480);
  await expect(
    page.getByRole("tablist", { name: "Parameter sections" }),
  ).toHaveCount(0);
  await fitsWindow(page);
  await page
    .locator(".figure-inspector")
    .screenshot({ path: info.outputPath("expanded-parameters.png") });
});

for (const width of [1440, 390]) {
  test(`medium parameter sets keep groups together and size fixed at ${width}px`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 900 });
    // Exercise a larger model-supplied schema without changing the production renderer.
    await page.route(/\/api\/v1\/plot-runs\/[^/]+$/, async (route) => {
      const response = await route.fetch();
      const snapshot: PlotRunSnapshot = await response.json();
      if (snapshot.result) {
        snapshot.result.control_groups = [
          ...(snapshot.result.control_groups ?? []),
          { id: "annotations", label: "Annotations" },
          { id: "legend", label: "Legend" },
        ];
        snapshot.result.controls = [
          ...(snapshot.result.controls ?? []).toReversed(),
          ...Array.from({ length: 12 }, (_, index) => ({
            id: `annotation_${index}`,
            label: `Annotation ${index + 1}`,
            type: "number" as const,
            input_mode: "number" as const,
            value: 12,
            minimum: 1,
            maximum: 24,
            step: 1,
            group: index < 6 ? "annotations" : "legend",
            update_strategy: "rerun" as const,
          })),
        ];
      }
      await route.fulfill({ response, json: snapshot });
    });
    await generate(page);
    await expect(
      page.getByRole("tablist", { name: "Parameter sections" }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("group", { name: "Annotations", exact: true }),
    ).toHaveCount(1);
    await expect(
      page.getByRole("group", { name: "Legend", exact: true }),
    ).toHaveCount(1);
    const outputWidth = page.getByRole("spinbutton", {
      name: "Figure width",
      exact: true,
    });
    const before = (await outputWidth.boundingBox())!;
    const fields = page.locator(".parameter-fields-scroll");
    await fields.evaluate((element) => {
      element.scrollTop = element.scrollHeight;
    });
    expect(
      await fields.evaluate((element) => element.scrollTop),
    ).toBeGreaterThan(0);
    expect((await outputWidth.boundingBox())!.y).toBeCloseTo(before.y, 0);
    await expect(outputWidth).toBeInViewport({ ratio: 1 });
    await expect(
      page.getByRole("spinbutton", { name: "Annotation 12", exact: true }),
    ).toBeInViewport({ ratio: 1 });
    await expect(
      page.getByRole("button", { name: "Apply as new version" }),
    ).toBeInViewport({ ratio: 1 });
    await outputWidth.fill("12.5");
    await page.getByRole("button", { name: "Reset", exact: true }).click();
    await expect(outputWidth).toHaveValue("8");
    await fitsWindow(page);
    await page.screenshot({
      path: info.outputPath("grouped-parameters-scrolled.png"),
    });
  });
}

async function downloadFigure(
  page: Page,
  info: TestInfo,
  format: "PNG" | "PDF" | "SVG",
  name = "figure",
) {
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const download = page.waitForEvent("download");
  await page
    .getByRole("menuitem", { name: `Download ${format}`, exact: true })
    .click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(
    new RegExp(`\\.${format.toLowerCase()}$`),
  );
  const path = info.outputPath(`${name}.${format.toLowerCase()}`);
  await file.saveAs(path);
  expect(await file.failure()).toBeNull();
  return readFile(path);
}

test("export menu downloads clean figures as PNG, PDF and SVG", async ({
  page,
}, info) => {
  await generate(page);
  await expect(
    page
      .locator(".plot-toolbar")
      .getByRole("button", { name: "Export", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator(".top-bar")
      .getByRole("button", { name: "Export", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await expect(page.getByRole("menu", { name: "Export format" })).toBeVisible();
  await page.screenshot({ path: info.outputPath("export-menu.png") });
  await page.keyboard.press("Escape");
  const png = await downloadFigure(page, info, "PNG");
  expect(png.subarray(1, 4).toString()).toBe("PNG");
  expect(png.readUInt32BE(16)).toBe(2400);
  expect(png.readUInt32BE(20)).toBe(1650);
  const pdf = await downloadFigure(page, info, "PDF");
  expect(pdf.subarray(0, 5).toString()).toBe("%PDF-");
  const svg = (await downloadFigure(page, info, "SVG")).toString();
  expect(svg).toContain('width="8in"');
  expect(svg).not.toContain("#f1efe8");
  const backgrounds = await page.evaluate((content) => {
    const root = new DOMParser().parseFromString(
      content,
      "image/svg+xml",
    ).documentElement;
    return Array.from(root.children)
      .filter((node) => node.localName === "rect")
      .map((node) => node.getAttribute("fill"));
  }, svg);
  expect(backgrounds).not.toContain("#fffefb");
  await fitsWindow(page);
});
