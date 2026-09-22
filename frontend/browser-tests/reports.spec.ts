import { expect, test, type Page } from "@playwright/test";
import type { ReportDocument } from "../src/api/schemas/reports";

test.use({ actionTimeout: 10000 });
async function currentReport(page: Page): Promise<ReportDocument> {
  const reportId = new URL(page.url()).searchParams.get("id")!;
  const project = await page.evaluate(() =>
    localStorage.getItem("vis-platform.project-id"),
  );
  return (
    await page.request.get(`/api/v1/projects/${project}/reports/${reportId}`)
  ).json();
}
async function createReport(page: Page, data = true, article = false) {
  await page.goto("/report");
  await page.getByRole("button", { name: "+ New report", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "New report", exact: true });
  await dialog
    .getByLabel("Report title", { exact: true })
    .fill("Treatment study report");
  if (article)
    await dialog.getByLabel("Report structure").selectOption("article");
  if (data) {
    await dialog.getByRole("button", { name: "Choose data" }).click();
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
  await dialog
    .getByRole("button", { name: "Create report", exact: true })
    .click();
  await expect(
    page.getByRole("article", { name: "Report document" }),
  ).toBeVisible();
}
async function send(page: Page, text: string) {
  const assistant = page.getByRole("complementary", {
    name: "Report assistant",
  });
  if (!(await assistant.isVisible()))
    await page.getByRole("button", { name: "Toggle report assistant" }).click();
  await assistant.getByLabel("Message the report assistant").fill(text);
  await assistant.getByRole("button", { name: "Send", exact: true }).click();
}
async function finished(page: Page) {
  await expect
    .poll(async () => (await currentReport(page)).messages.at(-1)?.status, {
      timeout: 30000,
    })
    .toBe("completed");
  await expect(page.locator(".report-message-working")).toHaveCount(0);
}
async function showPaper(page: Page) {
  if ((page.viewportSize()?.width ?? 1440) < 960) {
    const close = page.getByRole("button", { name: "Hide report assistant" });
    if (await close.isVisible()) await close.click();
  }
}

test("reports stay listed beside the open report and on a later visit", async ({
  page,
  context,
}) => {
  await createReport(page, false);
  const list = page.getByRole("navigation", { name: "Reports", exact: true });
  await expect(
    list.getByRole("button", { name: /Treatment study report/ }),
  ).toHaveAttribute("aria-current", "page");
  await list.getByRole("button", { name: "New report" }).click();
  const dialog = page.getByRole("dialog", { name: "New report", exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();

  const later = await context.newPage();
  await later.goto("/report");
  await later
    .getByRole("navigation", { name: "Reports", exact: true })
    .getByRole("button", { name: /Treatment study report/ })
    .click();
  await expect(
    later.getByRole("article", { name: "Report document" }),
  ).toBeVisible();
  await later.close();
});

test("one composer routes plots and paragraphs, chooses placement, and preserves shared figure metadata", async ({
  page,
}, info) => {
  test.setTimeout(60000);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await createReport(page);
  await expect(page.getByLabel("Assistant section")).toHaveCount(0);
  await expect(
    page.getByRole("group", { name: "Assistant action" }),
  ).toHaveCount(0);
  await expect(page.locator(".report-selection-hint")).toHaveCount(0);
  await send(page, "Create a figure comparing treatment groups in Results");
  await page.reload();
  await finished(page);
  await expect(page.locator(".report-figure-image")).toHaveCount(1);
  await send(page, "Write a paragraph explaining the figure in Results");
  await finished(page);
  const initial = await currentReport(page);
  const section = initial.content.sections[0]!;
  expect(section.blocks.map((block) => block.type)).toEqual(["figure", "text"]);
  const original = section.blocks[0]!;
  if (original.type !== "figure") throw new Error("Missing figure");
  const source = initial.figures[original.version_id!]!;
  expect(original.caption).toBe("");
  await expect(page.locator("figcaption")).toContainText(source.caption!);
  await expect(
    page.getByRole("textbox", { name: "Figure caption" }),
  ).toHaveCount(0);
  await send(page, "Refine Figure 1 with blue bars");
  await finished(page);
  const refined = await currentReport(page);
  const next = refined.content.sections[0]!.blocks[0]!;
  if (next.type !== "figure") throw new Error("Missing refined figure");
  expect(next.id).toBe(original.id);
  expect(next.version_id).not.toBe(original.version_id);
  await expect(page.locator(".report-figure-image")).toHaveCount(1);
  await page.locator(".report-figure-image").click({ button: "right" });
  await page
    .getByRole("menuitem", { name: "Refine this figure", exact: true })
    .click();
  await expect(
    page.getByRole("combobox", { name: "Color", exact: true }),
  ).toHaveValue("steelblue");
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.screenshot({ path: info.outputPath("automatic-report.png") });
  expect(errors).toEqual([]);
});

test("natural language creates a subsection and moves the section together with its contents", async ({
  page,
}, info) => {
  test.setTimeout(60000);
  await createReport(page, true, true);
  await send(
    page,
    "Add a subsection under Results, create a figure comparing the groups, and summarize it.",
  );
  await finished(page);
  const created = await currentReport(page);
  const child = created.content.sections.find(
    (section) => section.level === 2,
  )!;
  const parent = created.content.sections.find(
    (section) => section.id === child.parent_id,
  )!;
  expect(parent.title).toBe("Results");
  expect(child.blocks.map((block) => block.type)).toEqual(["figure", "text"]);
  await expect(
    page.getByRole("heading", { name: "Treatment comparison", level: 3 }),
  ).toBeVisible();
  await expect(
    page.locator('.report-outline button[data-level="2"]'),
  ).toContainText("Treatment comparison");
  await send(page, "Move Discussion before Results.");
  await finished(page);
  const moved = await currentReport(page);
  expect(moved.content.sections.map((section) => section.title)).toEqual([
    "Abstract",
    "Introduction",
    "Discussion",
    "Results",
    "Treatment comparison",
  ]);
  expect(moved.content.sections.at(-1)!.blocks).toEqual(child.blocks);
  await page.locator(".report-paper-scroll").evaluate((element) => {
    element.scrollTo({ top: element.scrollHeight, behavior: "instant" });
  });
  await page.screenshot({ path: info.outputPath("nested-report.png") });
});

test("abstract placement is automatic and questions do not publish paragraphs", async ({
  page,
}) => {
  await createReport(page, false);
  const before = await currentReport(page);
  await send(page, "What evidence do we need before writing results?");
  await finished(page);
  expect((await currentReport(page)).revision).toBe(before.revision);
  await send(page, "Write an abstract summarizing the available findings.");
  await finished(page);
  const after = await currentReport(page);
  expect(after.content.sections[0]!.title).toBe("Abstract");
  expect(after.content.sections[0]!.blocks[0]!.type).toBe("text");
  await page.reload();
  await expect(page.locator(".message-user")).toHaveCount(2);
});

test("ambiguous requests ask once and resume after refresh", async ({
  page,
}) => {
  await createReport(page, false, true);
  await send(page, "Summarize the ambiguous comparison.");
  await expect(
    page.getByRole("form", { name: "Question from the planner" }),
  ).toBeVisible();
  const pending = (await currentReport(page)).messages[0]!;
  await page.reload();
  await page.getByRole("radio", { name: "Results", exact: true }).check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await finished(page);
  const completed = await currentReport(page);
  expect(completed.messages).toHaveLength(1);
  expect(completed.messages[0]!.message_id).toBe(pending.message_id);
  expect(
    completed.content.sections.find((section) => section.title === "Results")!
      .blocks,
  ).toHaveLength(1);
});

test("legacy imports migrate and the report remains readable on phones", async ({
  page,
}, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/report");
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.getByLabel("Pre-report file").setInputFiles({
    name: "legacy.json",
    mimeType: "application/json",
    buffer: Buffer.from(
      JSON.stringify({
        schema_version: "1.0",
        title: "Legacy research report",
        topics: [
          {
            id: "results",
            title: "Results",
            blocks: [
              {
                id: "paragraph",
                type: "text",
                body: "The report summarizes the recorded observations.",
              },
            ],
          },
        ],
      }),
    ),
  });
  await page
    .getByRole("button", { name: "Import report", exact: true })
    .click();
  await expect(page.locator(".report-text-block")).toContainText(
    "recorded observations",
  );
  const migrated = await currentReport(page);
  expect(migrated.content.schema_version).toBe("2.0");
  expect(migrated.content.sections[0]!.id).toBe("results");
  await send(page, "Write an abstract for this report.");
  await finished(page);
  await showPaper(page);
  await expect(
    page.getByRole("heading", { name: "Abstract", level: 2 }),
  ).toBeVisible();
  const metrics = await page.locator(".report-shell").evaluate((element) => ({
    width: element.clientWidth,
    scrollWidth: element.scrollWidth,
    height: element.clientHeight,
    scrollHeight: element.scrollHeight,
  }));
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.width + 1);
  expect(metrics.scrollHeight).toBeLessThanOrEqual(metrics.height + 1);
  await page.screenshot({ path: info.outputPath("report-phone.png") });
});
