import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import type { ReportDocument } from "../src/api/schemas/reports";

async function current(page: Page): Promise<ReportDocument> {
  const id = new URL(page.url()).searchParams.get("id");
  const project = await page.evaluate(() =>
    localStorage.getItem("vis-platform.project-id"),
  );
  return (
    await page.request.get(`/api/v1/projects/${project}/reports/${id}`)
  ).json();
}
async function create(page: Page) {
  await page.goto("/slides");
  await page
    .getByRole("button", { name: "+ New presentation", exact: true })
    .click();
  const dialog = page.getByRole("dialog", {
    name: "New presentation",
    exact: true,
  });
  await dialog
    .getByLabel("Presentation title")
    .fill("Treatment response study");
  await dialog
    .getByRole("button", { name: "Create presentation", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Slide editor" }),
  ).toBeVisible();
}
async function send(page: Page, message: string) {
  const assistant = page.getByRole("complementary", {
    name: "Slides assistant",
  });
  if (!(await assistant.isVisible()))
    await page.getByRole("button", { name: "Toggle slides assistant" }).click();
  await assistant.getByLabel("Message the slides assistant").fill(message);
  await assistant.getByRole("button", { name: "Send", exact: true }).click();
  await expect
    .poll(async () => (await current(page)).messages.at(-1)?.status, {
      timeout: 40000,
    })
    .toBe("completed");
}
async function data(page: Page) {
  await page.getByRole("button", { name: "Choose data" }).click();
  await page.getByRole("tab", { name: "Upload", exact: true }).click();
  await page
    .getByLabel("Dataset name", { exact: true })
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
  await expect(page.locator(".dataset-state").first()).toHaveText("Ready");
  await page.getByRole("button", { name: "Done", exact: true }).click();
}

test("Slides creates a real figure and summary, edits layout, and presents", async ({
  page,
}, info) => {
  test.setTimeout(75000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await create(page);
  await data(page);
  await page
    .getByRole("button", { name: "Slide 2: Key findings", exact: true })
    .click();
  await send(
    page,
    "Create a figure comparing treatment groups and summarize the findings.",
  );
  await expect(
    page.locator(".slides-stage .slide-element-figure img"),
  ).toBeVisible();
  await expect(page.locator(".slides-stage .slide-prose")).toContainText(
    "Group B",
  );
  await page.locator(".slides-stage .slide-element-figure").click();
  await expect(
    page.getByText("Linked figure · updates across documents", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Refine / parameters", exact: true })
    .click();
  const editor = page.getByRole("dialog", {
    name: "Refine figure",
    exact: true,
  });
  await expect(
    editor.getByRole("region", { name: "Figure details" }),
  ).toBeVisible();
  await editor.getByRole("button", { name: "Close dialog" }).click();
  await page
    .getByLabel("Slide layout", { exact: true })
    .selectOption("two-column");
  await expect
    .poll(async () => (await current(page)).content.sections[1]?.slide?.layout)
    .toBe("two-column");
  await page
    .getByLabel("Speaker notes", { exact: true })
    .fill("Discuss the observed difference and uncertainty.");
  await page.getByLabel("Slide title", { exact: true }).click();
  await expect
    .poll(async () => (await current(page)).content.sections[1]?.slide?.notes)
    .toContain("uncertainty");
  await page
    .getByLabel("Presentation theme", { exact: true })
    .selectOption("midnight");
  await expect(page.locator(".slides-stage .slide-canvas")).toHaveAttribute(
    "data-theme",
    "midnight",
  );
  await page.screenshot({ path: info.outputPath("slides-editor.png") });
  await page.getByRole("button", { name: "▷ Present", exact: true }).click();
  const presentation = page.getByRole("dialog", {
    name: "Presentation",
    exact: true,
  });
  await expect(presentation).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(presentation.locator(".slide-heading")).toHaveText("Takeaways");
  await page.keyboard.press("Escape");
  await expect(presentation).toHaveCount(0);
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Slide 2: Key findings" }),
  ).toBeVisible();
  expect((await current(page)).content.presentation?.theme).toBe("midnight");
  expect(errors).toEqual([]);
});

test("Slides supports manual text, positioning, reordering and frozen JSON export", async ({
  page,
}, info) => {
  await create(page);
  await page.getByRole("button", { name: "Slide 2: Key findings" }).click();
  await page.getByRole("button", { name: "T Text", exact: true }).click();
  const editor = page.getByRole("dialog", { name: "Add text", exact: true });
  await editor
    .getByRole("textbox")
    .first()
    .fill("A concise finding from the study.");
  await editor
    .getByRole("button", { name: /Save|Add text/ })
    .last()
    .click();
  await expect(page.locator(".slides-stage .slide-prose")).toContainText(
    "concise finding",
  );
  const element = page.locator(".slides-stage .slide-element-text");
  await element.click();
  await element.focus();
  await page.keyboard.press("Alt+ArrowRight");
  await expect
    .poll(
      async () =>
        Object.keys(
          (await current(page)).content.sections[1]?.slide?.frames ?? {},
        ).length,
    )
    .toBe(1);
  await page.getByRole("button", { name: "Move slide earlier" }).click();
  await expect
    .poll(async () => (await current(page)).content.sections[0]?.title)
    .toBe("Key findings");
  await page.locator(".slides-export summary").click();
  const download = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Slide deck JSON", exact: true })
    .click();
  const saved = await download;
  expect(saved.suggestedFilename()).toContain(".json");
  const bytes = await readFile((await saved.path())!);
  const content = JSON.parse(bytes.toString("utf8"));
  expect(content.schema_version).toBe("1.0");
  expect(content.slides[0].title).toBe("Key findings");
  await page.pdf({
    path: info.outputPath("slides.pdf"),
    preferCSSPageSize: true,
    printBackground: true,
  });
  await page.goto("/slides");
  await page.getByLabel("Import slide deck", { exact: true }).setInputFiles({
    name: "presentation.json",
    mimeType: "application/json",
    buffer: bytes,
  });
  await expect(page.locator(".slides-stage .slide-prose")).toContainText(
    "concise finding",
  );
});

test("Slides remains usable on a phone", async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await create(page);
  await expect(
    page.getByRole("region", { name: "Slide editor" }),
  ).toBeInViewport();
  await page.getByRole("button", { name: "Toggle slides assistant" }).click();
  await expect(
    page.getByLabel("Message the slides assistant"),
  ).toBeInViewport();
  await page.getByRole("button", { name: "Hide slides assistant" }).click();
  await expect(
    page.getByRole("region", { name: "Slide editor" }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath("slides-phone.png") });
});

test("a slide refinement updates a linked report figure while its pinned copy stays unchanged", async ({
  page,
  context,
}) => {
  test.setTimeout(60000);
  await create(page);
  await data(page);
  await page.getByRole("button", { name: "Slide 2: Key findings" }).click();
  await send(page, "Create a figure comparing treatment groups.");
  const initial = await current(page);
  const figure = initial.content.sections[1]!.blocks[0]!;
  if (figure.type !== "figure") throw new Error("Missing figure");
  const response = await page.request.post(
    `/api/v1/projects/${initial.project_id}/reports`,
    {
      data: {
        request_id: "linked-report",
        content: {
          title: "Linked report",
          sections: [
            {
              id: "results",
              title: "Results",
              blocks: [
                { ...figure, id: "linked" },
                { ...figure, id: "pinned", follow_plot_id: null },
              ],
            },
          ],
        },
      },
    },
  );
  expect(response.status()).toBe(201);
  const report = await response.json();
  const reportPage = await context.newPage();
  await reportPage.addInitScript(
    (project) => localStorage.setItem("vis-platform.project-id", project),
    initial.project_id,
  );
  await reportPage.goto(`/report?id=${report.report_id}`);
  const images = reportPage.locator(".report-figure-image");
  await expect(images).toHaveCount(2);
  const original = await images.first().getAttribute("src");
  await send(page, "Refine Figure 1 with blue bars.");
  await expect(images.first()).not.toHaveAttribute("src", original!, {
    timeout: 10000,
  });
  await expect(images.nth(1)).toHaveAttribute("src", original!);
  await reportPage.close();
});
