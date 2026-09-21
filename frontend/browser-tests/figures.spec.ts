import { expect, test, type Page } from "@playwright/test";
import type { FigureDocument } from "../src/api/schemas/figureCompositions";

async function projectId(page: Page): Promise<string> {
  await expect
    .poll(() =>
      page.evaluate(() => sessionStorage.getItem("vis-platform.project-id")),
    )
    .not.toBeNull();
  return (await page.evaluate(() =>
    sessionStorage.getItem("vis-platform.project-id"),
  ))!;
}

async function demoPlot(page: Page, project: string, text: string) {
  const accepted = await page.request.post("/api/v1/plot-runs", {
    data: {
      project_id: project,
      request: { text },
      data_scope: { mode: "demo" },
    },
  });
  expect(accepted.status()).toBe(202);
  const status = (await accepted.json()).links.status as string;
  await expect
    .poll(async () => (await (await page.request.get(status)).json()).status)
    .toBe("completed");
}

async function current(page: Page, project: string): Promise<FigureDocument> {
  const id = new URL(page.url()).searchParams.get("id");
  return (
    await page.request.get(
      `/api/v1/projects/${project}/figure-compositions/${id}`,
    )
  ).json();
}

async function addPlot(page: Page, title: RegExp) {
  await page.getByRole("button", { name: "+ Plot" }).click();
  const dialog = page.getByRole("dialog", { name: "Add a saved plot" });
  await dialog.getByRole("button", { name: title }).first().click();
  await expect(dialog).toBeHidden();
}

test("compose, arrange, label, and export a figure", async ({ page }) => {
  await page.goto("/figure");
  const project = await projectId(page);
  await demoPlot(page, project, "Make a violin distribution of expression");
  await demoPlot(page, project, "Make a scatter relationship plot");

  await page.getByRole("button", { name: "+ New figure" }).click();
  const create = page.getByRole("dialog", { name: "New figure" });
  await create.getByLabel("Figure title").fill("Figure 3");
  await create.getByRole("combobox").selectOption("double-column");
  await create.getByRole("button", { name: "Create figure" }).click();
  const sheet = page.getByRole("region", { name: "Figure page" });
  await expect(sheet).toBeVisible();
  await expect(page.getByText("Your page is empty.")).toBeVisible();

  await addPlot(page, /distribution/i);
  await addPlot(page, /relationship/i);
  const first = sheet.getByRole("button", { name: /^Panel A:/ });
  const second = sheet.getByRole("button", { name: /^Panel B:/ });
  await expect(first).toBeVisible();
  await expect(second).toBeVisible();
  let document = await current(page, project);
  expect(document.revision).toBe(3);
  expect(document.content.page.width_mm).toBe(183);
  const [a, b] = document.content.panels;
  expect(document.panels[b!.id]!.frame.x_mm).toBeGreaterThan(
    document.panels[a!.id]!.frame.x_mm,
  );

  // Drag the second panel below the first; the page height follows the content.
  const before = document.page_height_mm;
  const box = (await second.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x - box.width / 2, box.y + box.height * 1.6, {
    steps: 8,
  });
  await page.mouse.up();
  await expect
    .poll(async () => (await current(page, project)).revision)
    .toBe(4);
  document = await current(page, project);
  expect(document.page_height_mm).toBeGreaterThan(before);
  expect(document.panels[b!.id]!.frame.y_mm).toBeGreaterThan(
    document.panels[a!.id]!.frame.y_mm +
      document.panels[a!.id]!.frame.height_mm,
  );

  // Keyboard nudges are saved as one revision.
  const start = document.content.panels[0]!.x_mm;
  await first.focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect
    .poll(async () => (await current(page, project)).revision)
    .toBe(5);
  document = await current(page, project);
  expect(document.content.panels[0]!.x_mm).toBeCloseTo(start + 1);

  // Custom label and legend text.
  await first.dblclick();
  const properties = page.getByLabel("Panel properties");
  await properties.getByRole("textbox", { name: "Custom label" }).fill("a");
  await properties.getByRole("textbox", { name: "Custom label" }).blur();
  await expect(sheet.getByRole("button", { name: /^Panel a:/ })).toBeVisible();
  await page.getByRole("tab", { name: "Legend" }).click();
  const legend = page.getByLabel("Figure legend");
  await legend
    .getByRole("textbox", { name: /Legend for panel a/ })
    .fill("Expression by group.");
  await legend.getByRole("textbox", { name: /Legend for panel a/ }).blur();
  await expect(legend.getByLabel("Legend preview")).toContainText(
    "Figure 3. (a) Expression by group.",
  );

  // Exports come from the server composition.
  await page.getByText("Export", { exact: true }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("menuitem", { name: "PDF · vector" }).click();
  expect((await download).suggestedFilename()).toMatch(/^Figure-3-r\d+\.pdf$/);

  // The figure is saved and reopens from the library.
  await page.getByRole("button", { name: /Figures/ }).click();
  await page.getByRole("button", { name: /Figure 3/ }).click();
  await expect(sheet.getByRole("button", { name: /^Panel a:/ })).toBeVisible();
});

const IMAGE_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAASwAAADICAIAAADdvUsCAAABsElEQVR42u3TQREAMAjAsDE1SEQispDBg0RC7xpZ/YA9XwIwIZgQMCGYEDAhmBAwIZgQMCGYEDAhmBAwIZgQMCGYEDAhmBAwIZgQMCGYEDAhmBAwIZgQMCGYEDAhmBAwIZgQMCGYEDAhmBAwIZgQMCGYEDAhmBAwIZgQMCGYEDAhmBAwIZgQMCGYEDAhmBAwIZgQMCGYEDAhmBAwIZgQMCGYEEwImBBMCJgQTAiYEEwImBBMCJgQTAiYEEwImBBMCJgQTAiYEEwImBBMCJgQTAiYEEwImBBMCJgQTAiYEEwImBBMCJgQTAiYEEwImBBMCJgQTAiYEEwImBBMCJgQTAiYEEwImBBMCJgQTAiYEEwImBBMCJgQTAiYEEwImBBMCJgQTAgmBEwIJgRMCCYETAgmBEwIJgRMCCYETAgmBEwIJgRMCCYETAgmBEwIJgRMCCYETAgmBEwIJgRMCCYETAgmBEwIJgRMCCYETAgmBEwIJgRMCCYETAgmBEwIJgRMCCYETAgmBEwIJgRMCCYETAgmBEwIJgRMCCYETAgmBEwIJgRMCCYEEwImBBMCJoSbBuJSAvi+UQSDAAAAAElFTkSuQmCC",
  "base64",
);

async function addImage(page: Page, name: string) {
  await page.getByRole("button", { name: "+ Image" }).click();
  const dialog = page.getByRole("dialog", { name: "Add an image" });
  await dialog
    .getByLabel("Image file")
    .setInputFiles({ name, mimeType: "image/png", buffer: IMAGE_PNG });
  await dialog.getByRole("button", { name: "Add image" }).click();
  await expect(dialog).toBeHidden();
}

test("several images upload on a plain-http address", async ({ page }) => {
  // Browsers omit crypto.randomUUID outside secure contexts, such as a LAN IP over http.
  await page.addInitScript(() => {
    Object.defineProperty(Crypto.prototype, "randomUUID", { value: undefined });
  });
  await page.goto("/figure");
  const project = await projectId(page);
  await page.getByRole("button", { name: "+ New figure" }).click();
  await page
    .getByRole("dialog", { name: "New figure" })
    .getByRole("button", { name: "Create figure" })
    .click();
  await addImage(page, "micrograph.png");
  await addImage(page, "diagram.png");
  await addImage(page, "stain.png");
  const sheet = page.getByRole("region", { name: "Figure page" });
  await expect(sheet.getByRole("button", { name: /^Panel C:/ })).toBeVisible();
  expect(
    (await current(page, project)).content.panels.map((panel) => panel.id),
  ).toEqual(["panel-1", "panel-2", "panel-3"]);
});

test("history restores an earlier arrangement", async ({ page }) => {
  await page.goto("/figure");
  const project = await projectId(page);
  await demoPlot(page, project, "Make a violin distribution of expression");
  await page.getByRole("button", { name: "+ New figure" }).click();
  await page
    .getByRole("dialog", { name: "New figure" })
    .getByRole("button", { name: "Create figure" })
    .click();
  await addPlot(page, /distribution/i);
  const sheet = page.getByRole("region", { name: "Figure page" });
  await sheet.getByRole("button", { name: /^Panel A:/ }).dblclick();
  await page.getByRole("button", { name: "Remove panel" }).click();
  await expect(page.getByText("Your page is empty.")).toBeVisible();
  await page.getByRole("button", { name: "History" }).click();
  await page.getByRole("button", { name: "Restore revision 2" }).click();
  await expect(sheet.getByRole("button", { name: /^Panel A:/ })).toBeVisible();
  expect((await current(page, project)).revision).toBe(4);
});

test("tidy rows and render plots at their printed size", async ({ page }) => {
  await page.goto("/figure");
  const project = await projectId(page);
  await demoPlot(page, project, "Make a violin distribution of expression");
  await demoPlot(page, project, "Make a scatter relationship plot");
  await page.getByRole("button", { name: "+ New figure" }).click();
  await page
    .getByRole("dialog", { name: "New figure" })
    .getByRole("button", { name: "Create figure" })
    .click();
  await addPlot(page, /distribution/i);
  await addPlot(page, /relationship/i);
  const sheet = page.getByRole("region", { name: "Figure page" });
  // Scale the second panel down so the rows are uneven before tidying.
  await sheet.getByRole("button", { name: /^Panel B:/ }).dblclick();
  const scale = page.getByLabel("Panel properties").getByLabel("Scale");
  await scale.fill("25");
  await scale.press("Enter");
  await expect
    .poll(async () => (await current(page, project)).revision)
    .toBe(4);
  await page.locator("summary", { hasText: "Arrange" }).click();
  await page
    .getByRole("menuitem", { name: "Tidy rows and render plots at size" })
    .click();
  await expect
    .poll(
      async () =>
        (await current(page, project)).jobs.map((job) => job.status).join(),
      { timeout: 20000 },
    )
    .toBe("completed,completed");
  const document = await current(page, project);
  const [a, b] = document.content.panels;
  expect(a!.scale).toBe(1);
  expect(b!.scale).toBe(1);
  const frameA = document.panels[a!.id]!.frame;
  const frameB = document.panels[b!.id]!.frame;
  expect(frameA.height_mm).toBeCloseTo(frameB.height_mm, 0);
  expect(frameA.x_mm + frameA.width_mm + 4).toBeCloseTo(frameB.x_mm, 0);
  await expect(sheet.getByText("Rendering at panel size…")).toHaveCount(0);
});

test("the assistant asks, arranges, and writes the legend", async ({
  page,
}) => {
  await page.goto("/figure");
  const project = await projectId(page);
  await demoPlot(page, project, "Make a violin distribution of expression");
  await demoPlot(page, project, "Make a scatter relationship plot");
  await demoPlot(page, project, "Make a boxplot comparing treatment groups");
  await page.getByRole("button", { name: "+ New figure" }).click();
  await page
    .getByRole("dialog", { name: "New figure" })
    .getByRole("button", { name: "Create figure" })
    .click();
  for (const name of [/distribution/i, /relationship/i, /distribution/i])
    await addPlot(page, name);
  const assistant = page.getByLabel("Figure assistant");
  const composer = assistant.getByRole("textbox", {
    name: "Message the figure assistant",
  });
  await composer.fill("Which panel should lead? Then arrange the figure.");
  await assistant.getByRole("button", { name: "Send", exact: true }).click();
  await expect(
    assistant.getByText("Which panel should lead the figure?"),
  ).toBeVisible();
  await assistant.getByRole("radio", { name: /relationship/i }).check();
  await assistant.getByRole("button", { name: "Continue" }).click();
  await expect
    .poll(async () => (await current(page, project)).messages.at(-1)?.status, {
      timeout: 20000,
    })
    .toBe("completed");
  await expect(assistant.getByText("Arranged the panels.")).toBeVisible();
  let document = await current(page, project);
  const lead = document.content.panels.find(
    (panel) =>
      panel.content.type === "plot" &&
      document.figures[panel.content.version_id]?.title?.match(/relationship/i),
  )!;
  // The chosen panel leads the figure at full printable width.
  expect(document.panels[lead.id]!.label).toBe("A");
  expect(document.panels[lead.id]!.frame.width_mm).toBeCloseTo(200, 0);
  expect(document.jobs.every((job) => job.status === "completed")).toBe(true);

  await composer.fill("Write the legend");
  await assistant.getByRole("button", { name: "Send", exact: true }).click();
  await expect(assistant.getByText("Wrote the legend.")).toBeVisible();
  document = await current(page, project);
  expect(Object.keys(document.content.legend.entries)).toHaveLength(3);
  await page.getByRole("tab", { name: "Legend" }).click();
  await expect(page.getByLabel("Legend preview")).toContainText(
    "Overview of the study results.",
  );
});

test("a figure is built from a description, one slot at a time", async ({
  page,
}) => {
  test.setTimeout(90_000);
  await page.goto("/figure");
  const project = await projectId(page);
  await page.getByRole("button", { name: "+ New figure" }).click();
  const create = page.getByRole("dialog", { name: "New figure" });
  await create
    .getByLabel(/What should this figure show/)
    .fill("Build a figure of the treatment response");
  await create.getByRole("button", { name: "Create and build" }).click();
  const sheet = page.getByRole("region", { name: "Figure page" });
  await expect(sheet.getByRole("button", { name: /^Panel C:/ })).toBeVisible();
  const types = async () =>
    (await current(page, project)).content.panels.map(
      (panel) => panel.content.type,
    );
  await expect
    .poll(types, { timeout: 60_000 })
    .toEqual(["plot", "plot", "plot"]);
  await expect(
    page.getByRole("list", { name: "Completed changes" }),
  ).toContainText("Created panel “summary”.");
  let document = await current(page, project);
  // The first panel spans the page; the other two share a row below it.
  const [lead, left, right] = ["distribution", "comparison", "summary"].map(
    (id) => document.panels[id]!.frame,
  );
  expect(lead!.width_mm).toBeGreaterThan(left!.width_mm + right!.width_mm);
  expect(left!.y_mm).toBeCloseTo(right!.y_mm, 1);

  // A slot drawn by hand is described and filled on request.
  await page.getByRole("button", { name: "+ Slot" }).click();
  await expect(sheet.getByRole("button", { name: /Empty slot/ })).toBeVisible();
  await page
    .getByLabel("What should this plot show?")
    .fill("Use demonstration data to create a violin distribution");
  await page.getByRole("button", { name: "Create plot" }).click();
  await expect
    .poll(types, { timeout: 60_000 })
    .toEqual(["plot", "plot", "plot", "plot"]);
  // The plot may still be rendering at the slot's size; the message then finishes.
  await expect
    .poll(async () => (await current(page, project)).messages.at(-1)!.panels, {
      timeout: 30_000,
    })
    .toEqual([{ panel_id: "panel-1", status: "completed", error: null }]);
  await page.screenshot({ path: test.info().outputPath("built-figure.png") });
});
