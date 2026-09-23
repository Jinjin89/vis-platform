import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

// Headless Chromium draws WebGL in software.
test.use({
  actionTimeout: 10000,
  launchOptions: { args: ["--no-sandbox", "--enable-unsafe-swiftshader"] },
});

const RING = 20_000;

async function ok<T>(response: {
  ok(): boolean;
  json(): Promise<T>;
  text(): Promise<string>;
}) {
  expect(response.ok(), await response.text()).toBe(true);
  return response.json();
}

/** Cells on a ring around one cell at the centre, in pixels of a 200 × 200 section. */
function cellTable() {
  const rows = ["cell_id,x_px,y_px,domain"];
  for (let index = 0; index < RING; index += 1) {
    const angle = (index / RING) * 2 * Math.PI;
    const radius = 60 + (index % 7) * 4;
    rows.push(
      `ring_${index},${(100 + Math.cos(angle) * radius).toFixed(3)},${(
        100 +
        Math.sin(angle) * radius
      ).toFixed(3)},${index % 2 ? "Cortex" : "Capsule"}`,
    );
  }
  rows.push("centre_cell,100,100,Medulla");
  return Buffer.from(rows.join("\n") + "\n");
}

/** A pink section image, drawn by the browser. */
async function sectionImage(page: Page) {
  const data = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 200;
    const context = canvas.getContext("2d")!;
    context.fillStyle = "#f6f3f5";
    context.fillRect(0, 0, 200, 200);
    context.fillStyle = "#e4aac8";
    context.beginPath();
    context.arc(100, 100, 90, 0, 2 * Math.PI);
    context.fill();
    return canvas.toDataURL("image/png").split(",")[1]!;
  });
  return Buffer.from(data, "base64");
}

async function studyWithPointMap(request: APIRequestContext, page: Page) {
  const { project_id: project } = await ok<{ project_id: string }>(
    await request.post("/api/v1/projects", { data: { name: "Spatial" } }),
  );
  const { dataset_id: dataset } = await ok<{ dataset_id: string }>(
    await request.post("/api/v1/data-bundles", {
      data: { project_id: project, name: "Section" },
    }),
  );
  for (const [name, data] of [
    ["cells.csv", cellTable()],
    ["section.png", await sectionImage(page)],
  ] as const)
    await ok(
      await request.post(
        `/api/v1/data-bundles/${dataset}/files?project_id=${project}&name=${name}`,
        { data, headers: { "Content-Type": "application/octet-stream" } },
      ),
    );
  await ok(
    await request.post(
      `/api/v1/data-bundles/${dataset}/finalize?project_id=${project}`,
    ),
  );
  let objects: { name: string; object_id: string; revision_id: string }[] = [];
  await expect
    .poll(async () => {
      const found = await ok<{ state: string; objects: typeof objects }>(
        await request.get(
          `/api/v1/data-bundles/${dataset}?project_id=${project}`,
        ),
      );
      objects = found.objects;
      return found.state;
    })
    .toBe("ready");
  const reference = (name: string) => {
    const item = objects.find((object) => object.name === name)!;
    return { object_id: item.object_id, revision_id: item.revision_id };
  };
  const run = await ok<{ links: { status: string } }>(
    await request.post("/api/v1/plot-runs", {
      data: {
        project_id: project,
        request: { text: "Map the section" },
        data_scope: { mode: "selected", bundle_ids: [dataset] },
        research_plan: {
          title: "Section map",
          description: "Cells over the section image.",
          figure_size: { width: 6, height: 5 },
          inputs: [
            { alias: "cells", reference: reference("cells") },
            { alias: "section", reference: reference("section") },
          ],
          point_map: {
            table: "cells",
            x: "x_px",
            y: "y_px",
            color: "domain",
            y_axis: "down",
            image: { input: "section" },
          },
        },
      },
    }),
  );
  await expect
    .poll(
      async () =>
        (await ok<{ status: string }>(await request.get(run.links.status)))
          .status,
      { timeout: 20000 },
    )
    .toBe("completed");
  return project;
}

test("clicking a cell and dragging an area in the GPU view reach the assistant as data", async ({
  page,
  request,
}) => {
  const webgl = await page.evaluate(
    () => document.createElement("canvas").getContext("webgl2") !== null,
  );
  test.skip(
    !webgl,
    "WebGL2 is unavailable; on a server without a display, run under Xvfb.",
  );
  const project = await studyWithPointMap(request, page);
  await page.addInitScript((id) => {
    localStorage.setItem("vis-platform.project-id", id);
  }, project);
  await page.goto("/pinpoint");
  const map = page.getByRole("img", { name: "Section map" });
  await expect(map.locator("canvas")).toBeVisible({ timeout: 15000 });
  await expect(page.locator("figure.pinpoint-map")).toHaveAttribute(
    "data-drawn",
    "true",
    { timeout: 15000 },
  );
  await expect(
    page.getByText(`${(RING + 1).toLocaleString()} points`),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Colour: domain" }),
  ).toContainText("Medulla");

  // The fitted view centres the section, so the lone centre cell is under the middle.
  const box = (await map.boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  const toSend = page.getByRole("list", { name: "Marks to send" });
  await expect(toSend.getByText("Point 1")).toBeVisible();

  await page.getByRole("radio", { name: "Drag an area" }).click();
  await page.mouse.move(box.x + box.width * 0.05, box.y + box.height * 0.05);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5, {
    steps: 6,
  });
  await page.mouse.up();
  await expect(toSend.getByText("Area 2")).toBeVisible();
  const counted = await page.locator(".pinpoint-map-count").textContent();
  const shown = Number(counted!.replace(/[^0-9]/g, ""));
  expect(shown).toBeGreaterThan(1000);
  expect(shown).toBeLessThan(RING / 2);
  await page.screenshot({ path: "test-results/pinpoint-points-marked.png" });

  await page
    .getByRole("textbox", { name: "Your request" })
    .fill("Where are 1 and 2?");
  await page.getByRole("button", { name: "Send" }).click();
  const reply = page.locator(".pinpoint-message[data-role='assistant']");
  await expect(reply).toContainText("Mark 1 is centre_cell.", {
    timeout: 15000,
  });
  // The backend counts the same points over the full table.
  await expect(reply).toContainText(`Mark 2 holds ${shown} points.`);
  await page.screenshot({ path: "test-results/pinpoint-points-reply.png" });
});
