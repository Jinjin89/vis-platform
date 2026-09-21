import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";

async function referenceBytes() {
  return readFile(new URL("./fixtures/reference.png", import.meta.url));
}

async function addData(page: Page) {
  await page.getByRole("button", { name: "Choose data", exact: true }).click();
  const library = page.getByRole("dialog", { name: "Data & analysis" });
  await library.getByRole("tab", { name: "Upload", exact: true }).click();
  await library.getByLabel("Dataset name").fill("Reference study");
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
  await library.getByRole("button", { name: "Done", exact: true }).click();
}

for (const width of [1440, 390]) {
  test(`separate Data and Add image generate a real figure at ${width}px`, async ({
    page,
  }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Add image" })).toBeVisible();
    expect(
      await page
        .getByRole("button", { name: "Choose data", exact: true })
        .evaluate((button) => button.closest("form") === null),
    ).toBe(true);
    await addData(page);
    await page.getByLabel("Choose plot reference images").setInputFiles({
      name: "reference.png",
      mimeType: "image/png",
      buffer: await referenceBytes(),
    });
    await expect(
      page.getByText("Plot reference", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "View reference.png" }).click();
    const preview = page.getByRole("dialog", {
      name: "Image preview: reference.png",
    });
    await expect(preview).toBeVisible();
    await expect(preview.getByRole("img")).toBeVisible();
    await preview.getByRole("button", { name: "Close image preview" }).click();
    await page
      .getByRole("textbox", { name: "Describe the plot you want" })
      .fill("Make a plot like this using my data.");
    const submission = page.waitForRequest(
      (req) =>
        req.url().endsWith("/api/v1/assistant-turns") &&
        req.method() === "POST",
    );
    await page.getByRole("button", { name: "Send", exact: true }).click();
    const body = (await submission).postDataJSON();
    expect(body.request.reference_image_ids).toHaveLength(1);
    expect(body.data_scope.mode).toBe("selected");
    expect(body.data_scope.bundle_ids).toHaveLength(1);
    await expect(page.locator(".plot-preview")).toBeVisible();
    if (width === 390)
      await page
        .getByRole("button", { name: "Conversation", exact: true })
        .click();
    await expect(
      page.locator(".message-user").getByRole("img", { name: "reference.png" }),
    ).toBeVisible();
    await expect(page.locator(".conversation-data")).toContainText(
      "Reference study",
    );
    await expect(
      page.getByRole("button", { name: "Add image" }),
    ).toBeInViewport();
    await expect(
      page.getByRole("button", { name: "Send", exact: true }),
    ).toBeInViewport();
    await page.screenshot({
      path: info.outputPath("two-button-workspace.png"),
    });
  });
}

test("pasted and dropped references survive an unanswered question and refresh", async ({
  page,
}) => {
  await page.goto("/");
  const encoded = (await referenceBytes()).toString("base64");
  const composer = page.getByRole("textbox", {
    name: "Describe the plot you want",
  });
  await composer.evaluate((element, bytes) => {
    const file = new File(
      [Uint8Array.from(atob(bytes), (c) => c.charCodeAt(0))],
      "pasted.png",
      { type: "image/png" },
    );
    const transfer = new DataTransfer();
    transfer.items.add(file);
    element.dispatchEvent(
      new ClipboardEvent("paste", {
        clipboardData: transfer,
        bubbles: true,
        cancelable: true,
      }),
    );
  }, encoded);
  await expect(page.getByText("Plot reference", { exact: true })).toHaveCount(
    1,
  );
  await page.locator(".composer-surface").evaluate((element, bytes) => {
    const file = new File(
      [Uint8Array.from(atob(bytes), (c) => c.charCodeAt(0))],
      "dropped.png",
      { type: "image/png" },
    );
    const transfer = new DataTransfer();
    transfer.items.add(file);
    element.dispatchEvent(
      new DragEvent("drop", {
        dataTransfer: transfer,
        bubbles: true,
        cancelable: true,
      }),
    );
  }, encoded);
  await expect(page.getByText("Plot reference", { exact: true })).toHaveCount(
    2,
  );
  await composer.fill("Ask me what to emphasize in this plot.");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(
    page.getByText("What should this comparison emphasize?"),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("What should this comparison emphasize?"),
  ).toBeVisible();
  await expect(
    page.locator(".message-user").getByRole("img", { name: "pasted.png" }),
  ).toBeVisible();
  await expect(
    page.locator(".message-user").getByRole("img", { name: "dropped.png" }),
  ).toBeVisible();
});
