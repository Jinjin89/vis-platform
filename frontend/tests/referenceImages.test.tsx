import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { startAssistantTurn } from "../src/api/client";
import {
  referenceImageSchema,
  type ReferenceImage,
} from "../src/api/schemas/referenceImages";
import { ConversationPanel } from "../src/features/plot-run/ConversationPanel";
import type { UploadReference } from "../src/features/plot-references/useReferenceImages";

const image: ReferenceImage = {
  image_id: "ref_one",
  project_id: "project_one",
  name: "example.png",
  media_type: "image/png",
  width: 32,
  height: 24,
  byte_size: 120,
  created_at: "2026-09-14T00:00:00Z",
  links: {
    content:
      "/api/v1/projects/project_one/plot-reference-images/ref_one/content",
    thumbnail:
      "/api/v1/projects/project_one/plot-reference-images/ref_one/thumbnail",
  },
};
const originalCreate = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
const originalRevoke = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");

beforeEach(() => {
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => "blob:local-image"),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: vi.fn(),
  });
});
afterEach(() => {
  if (originalCreate)
    Object.defineProperty(URL, "createObjectURL", originalCreate);
  else Reflect.deleteProperty(URL, "createObjectURL");
  if (originalRevoke)
    Object.defineProperty(URL, "revokeObjectURL", originalRevoke);
  else Reflect.deleteProperty(URL, "revokeObjectURL");
  vi.unstubAllGlobals();
});

function panel({
  upload = vi.fn<UploadReference>().mockResolvedValue(image),
  submit = vi.fn().mockResolvedValue(true),
  remove = vi.fn().mockResolvedValue(undefined),
}: {
  upload?: UploadReference;
  submit?: (text: string, images?: ReferenceImage[]) => Promise<boolean>;
  remove?: (image: ReferenceImage) => Promise<void>;
} = {}) {
  render(
    <ConversationPanel
      dataSelector={<button type="button">Data</button>}
      projectId="project_one"
      onUploadReference={upload}
      onDeleteReference={remove}
      committedSnapshot={null}
      activeSnapshot={null}
      messages={[]}
      traceTargets={[]}
      progressMessage="Ready"
      progressValue={0}
      isRunning={false}
      interactionBusy={false}
      interactionError={null}
      onSubmit={submit}
      onAnswerQuestion={async () => undefined}
      onDecideApproval={async () => undefined}
    />,
  );
  return { upload, submit, remove };
}
function picker() {
  return screen.getByLabelText("Choose plot reference images");
}
function input() {
  return screen.getByRole("textbox", { name: "Describe the plot you want" });
}
function file() {
  return new File(["image bytes"], "example.png", { type: "image/png" });
}
function clipboard(files: File[], text = "") {
  return {
    items: files.map((value) => ({ kind: "file", getAsFile: () => value })),
    getData: () => text,
  };
}
function drop(files: File[]) {
  fireEvent.drop(input().closest(".composer-surface")!, {
    dataTransfer: { types: ["Files"], files },
  });
}

test("Data is outside the composer and a picked reference can be sent without text", async () => {
  const user = userEvent.setup();
  const { submit, remove } = panel();
  expect(
    screen.getByRole("button", { name: "Data" }).closest("form"),
  ).toBeNull();
  expect(
    screen.getByRole("button", { name: "Add image" }).closest("form"),
  ).not.toBeNull();
  await user.upload(picker(), file());
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled(),
  );
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Send" }));
  expect(submit).toHaveBeenCalledWith("", [image]);
  expect(
    screen.queryByRole("button", { name: "Remove example.png" }),
  ).not.toBeInTheDocument();
  expect(remove).not.toHaveBeenCalled();
});

test("mixed clipboard text is preserved at the caret while its image is attached", async () => {
  const user = userEvent.setup();
  const { submit } = panel();
  await user.type(input(), "Use  colors");
  (input() as HTMLTextAreaElement).setSelectionRange(4, 4);
  fireEvent.paste(input(), { clipboardData: clipboard([file()], "these") });
  await waitFor(() =>
    expect(screen.getByText("Plot reference")).toBeInTheDocument(),
  );
  expect(input()).toHaveValue("Use these colors");
  await user.click(screen.getByRole("button", { name: "Send" }));
  expect(submit).toHaveBeenCalledWith("Use these colors", [image]);
});

test("ordinary text paste is unchanged and data drops never start image uploads", async () => {
  const user = userEvent.setup();
  const { upload } = panel();
  await user.click(input());
  await user.paste("Compare treatment groups");
  expect(input()).toHaveValue("Compare treatment groups");
  drop([new File(["value\n1"], "trial.csv", { type: "text/csv" })]);
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Use Data for data files",
  );
  expect(upload).not.toHaveBeenCalled();
  expect(input()).toHaveValue("Compare treatment groups");
});

test("dropping an image attaches it through the same upload flow", async () => {
  const { upload } = panel();
  const value = file();
  drop([value]);
  await waitFor(() =>
    expect(screen.getByText("Plot reference")).toBeInTheDocument(),
  );
  expect(upload).toHaveBeenCalledWith(
    value,
    expect.any(AbortSignal),
    expect.any(String),
  );
});

test("failed uploads block Send, retry the same upload key, and preserve the draft", async () => {
  const user = userEvent.setup();
  const upload = vi
    .fn<UploadReference>()
    .mockRejectedValueOnce(new Error("Upload interrupted"))
    .mockResolvedValueOnce(image);
  panel({ upload });
  await user.type(input(), "Keep this layout");
  await user.upload(picker(), file());
  expect(await screen.findByText("Upload interrupted")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled(),
  );
  expect(upload.mock.calls[0]![2]).toBe(upload.mock.calls[1]![2]);
  expect(input()).toHaveValue("Keep this layout");
});

test("an unaccepted message keeps both its image and text for another attempt", async () => {
  const user = userEvent.setup();
  const submit = vi
    .fn()
    .mockResolvedValueOnce(false)
    .mockResolvedValueOnce(true);
  panel({ submit });
  await user.type(input(), "Use this example");
  await user.upload(picker(), file());
  await user.click(screen.getByRole("button", { name: "Send" }));
  expect(input()).toHaveValue("Use this example");
  expect(
    screen.getByRole("button", { name: "Remove example.png" }),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Send" }));
  expect(input()).toHaveValue("");
  expect(submit).toHaveBeenCalledTimes(2);
});

test("removing an in-flight image aborts it and cleans up a late upload response", async () => {
  const user = userEvent.setup();
  let resolve!: (image: ReferenceImage) => void;
  const upload = vi.fn<UploadReference>(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const { remove } = panel({ upload });
  await user.upload(picker(), file());
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Remove example.png" }));
  expect(upload.mock.calls[0]![1].aborted).toBe(true);
  await act(async () => resolve(image));
  expect(remove).toHaveBeenCalledWith(image);
  expect(screen.queryByText("Plot reference")).not.toBeInTheDocument();
});

test("reference links are constrained to the application's versioned API", () => {
  expect(() =>
    referenceImageSchema.parse({
      ...image,
      links: { ...image.links, content: "https://other.example/image.png" },
    }),
  ).toThrow();
});

test("assistant submission carries image IDs independently from selected data", async () => {
  const fetcher = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        schema_version: "1.0",
        turn_id: "turn_one",
        status: "running",
        links: { trace: "/api/v1/assistant-turns/turn_one/trace" },
      }),
      { status: 202, headers: { "Content-Type": "application/json" } },
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  await startAssistantTurn(
    "project_one",
    "Like this",
    undefined,
    ["dataset_one"],
    [],
    ["ref_one"],
  );
  const body = JSON.parse(fetcher.mock.calls[0]![1].body);
  expect(body.request.reference_image_ids).toEqual(["ref_one"]);
  expect(body.data_scope).toEqual({
    mode: "selected",
    bundle_ids: ["dataset_one"],
  });
  expect(JSON.stringify(body)).not.toContain("base64");
});
