import { expect, test, type APIRequestContext } from "@playwright/test";

test.use({ actionTimeout: 10000 });

async function ok<T>(response: {
  ok(): boolean;
  json(): Promise<T>;
  text(): Promise<string>;
}) {
  expect(response.ok(), await response.text()).toBe(true);
  return response.json();
}

/** A study with a real R bar chart of group means: A = 2, B = 6. */
async function studyWithPlot(request: APIRequestContext) {
  const { project_id: project } = await ok<{ project_id: string }>(
    await request.post("/api/v1/projects", { data: { name: "Pinpoint" } }),
  );
  const { dataset_id: dataset } = await ok<{ dataset_id: string }>(
    await request.post("/api/v1/data-bundles", {
      data: { project_id: project, name: "Treatment study" },
    }),
  );
  for (const [name, contents] of [
    ["observations.csv", "sample_id,value\ns1,1\ns2,3\ns3,5\ns4,7\n"],
    ["samples.csv", "sample_id,group\ns1,A\ns2,A\ns3,B\ns4,B\n"],
  ])
    await ok(
      await request.post(
        `/api/v1/data-bundles/${dataset}/files?project_id=${project}&name=${name}`,
        {
          data: Buffer.from(contents!),
          headers: { "Content-Type": "application/octet-stream" },
        },
      ),
    );
  await ok(
    await request.post(
      `/api/v1/data-bundles/${dataset}/finalize?project_id=${project}`,
    ),
  );
  await expect
    .poll(
      async () =>
        (
          await ok<{ state: string }>(
            await request.get(
              `/api/v1/data-bundles/${dataset}?project_id=${project}`,
            ),
          )
        ).state,
    )
    .toBe("ready");
  const turn = await ok<{ plot_run: { links: { status: string } } }>(
    await request.post("/api/v1/assistant-turns", {
      data: {
        project_id: project,
        request: { text: "Compare treatment group means" },
        data_scope: { mode: "selected", bundle_ids: [dataset] },
      },
    }),
  );
  await expect
    .poll(
      async () =>
        (
          await ok<{ status: string }>(
            await request.get(turn.plot_run.links.status),
          )
        ).status,
      { timeout: 20000 },
    )
    .toBe("completed");
  return project;
}

test("marks on a real plot reach the assistant in data units", async ({
  page,
  request,
}) => {
  const project = await studyWithPlot(request);
  await page.addInitScript((id) => {
    localStorage.setItem("vis-platform.project-id", id);
  }, project);
  await page.goto("/pinpoint");
  const image = page.getByRole("img", { name: /Mean observed value/ });
  await expect(image).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Plots" }).getByRole("button", {
      name: /Treatment comparison/,
    }),
  ).toHaveAttribute("aria-current", "page");

  // Point at the top of bar B (mean 6), then drag across bar A.
  const box = (await image.boundingBox())!;
  const surface = page.locator(".pinpoint-surface");
  await surface.click({
    position: { x: box.width * 0.72, y: box.height * 0.2 },
  });
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.5);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.45, box.y + box.height * 0.8, {
    steps: 5,
  });
  await page.mouse.up();
  const toSend = page.getByRole("list", { name: "Marks to send" });
  await expect(toSend.getByText("Point 1")).toBeVisible();
  await expect(toSend.getByText("Area 2")).toBeVisible();
  await page.screenshot({ path: "test-results/pinpoint-marked.png" });

  await page
    .getByRole("textbox", { name: "Your request" })
    .fill("Where are 1 and 2?");
  await page.getByRole("button", { name: "Send" }).click();
  const reply = page.locator(".pinpoint-message[data-role='assistant']");
  await expect(reply).toContainText(/Mark 1 is at y = [\d.]+\./, {
    timeout: 15000,
  });
  const value = Number(
    /Mark 1 is at y = (\d+(?:\.\d+)?)/.exec((await reply.textContent())!)![1],
  );
  // 20% down a bar chart whose axis reaches about 6: well above bar A.
  expect(value).toBeGreaterThan(4);
  expect(value).toBeLessThan(7);
  await expect(reply).toContainText(/Mark 2 spans y = [\d.]+ to [\d.]+\./);
  await page.screenshot({ path: "test-results/pinpoint-reply.png" });

  // A refinement makes a new version, which clears the marks placed on the old one.
  await page
    .getByRole("textbox", { name: "Your request" })
    .fill("Refine the selected plot: make 1 blue");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(toSend).toBeHidden({ timeout: 20000 });
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
});
