import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import type { PlotResult } from "../src/api/schemas/plotRun";
import { controlDefinitionSchema } from "../src/api/schemas/plotRun";
import { FigureInspector } from "../src/features/plot-run/FigureInspector";

const base: PlotResult = {
  plot_id: "plot_1",
  version_id: "version_1",
  execution_mode: "demo",
  controls_mode: "hybrid",
  parameter_schema_version: "1.0",
  parameter_updates_available: true,
  data_summary: "Illustrative values. No research dataset was analyzed.",
  caption: "Expression compared between groups.",
  preview: {
    artifact_id: "artifact_1",
    role: "preview",
    media_type: "image/svg+xml",
    href: "/api/v1/artifacts/artifact_1",
    description: "Expression distribution.",
  },
  validation: { status: "demo_only", warnings: [] },
  control_groups: [
    { id: "appearance", label: "Appearance" },
    { id: "distribution", label: "Distribution" },
  ],
  controls: [
    {
      id: "title",
      label: "Title",
      group: "appearance",
      update_strategy: "rerun",
      type: "text",
      value: "Expression",
      min_length: 1,
      max_length: 80,
    },
    {
      id: "label_size",
      label: "Label size",
      group: "appearance",
      update_strategy: "rerun",
      type: "number",
      value: 11,
      minimum: 10,
      maximum: 14,
      step: 0.5,
      unit: "pt",
    },
    {
      id: "palette",
      label: "Palette",
      group: "appearance",
      update_strategy: "rerun",
      type: "choice",
      value: "original",
      options: [
        { value: "original", label: "Forest" },
        { value: "plum", label: "Plum" },
      ],
    },
    {
      id: "show_points",
      label: "Observations",
      group: "distribution",
      update_strategy: "rerun",
      type: "boolean",
      value: true,
    },
  ],
};

test("renders bottom tabs and submits only typed parameter changes", async () => {
  const user = userEvent.setup();
  const apply = vi.fn(async () => true);
  render(
    <FigureInspector
      projectId="project_1"
      result={base}
      disabled={false}
      onApply={apply}
    />,
  );
  expect(screen.getByRole("tab", { name: "Parameters" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  expect(
    screen.queryByRole("tablist", { name: "Parameter sections" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "Observations" })).toBeVisible();
  expect(
    screen.getByRole("button", { name: "Apply as new version" }),
  ).toBeDisabled();
  fireEvent.change(screen.getByRole("slider", { name: /Label size/ }), {
    target: { value: "13" },
  });
  await user.click(screen.getByRole("checkbox", { name: "Observations" }));
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Palette" }),
    "plum",
  );
  await user.click(
    screen.getByRole("button", { name: "Apply as new version" }),
  );
  expect(apply).toHaveBeenCalledWith(
    { label_size: 13, show_points: false, palette: "plum" },
    expect.any(String),
  );
  expect(
    base.controls?.find((control) => control.id === "label_size")?.value,
  ).toBe(11);

  await user.click(screen.getByRole("tab", { name: "Data" }));
  expect(screen.getByText(base.data_summary)).toBeVisible();
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: "Results" }));
  expect(screen.getByText(base.caption!)).toBeVisible();
  expect(screen.getByRole("button", { name: "Export figure" })).toBeVisible();
});

test("new figure definitions replace controls and saved values, including visibility rules", async () => {
  const user = userEvent.setup();
  const apply = vi.fn(async () => true);
  const { rerender } = render(
    <FigureInspector
      projectId="project_1"
      result={base}
      disabled={false}
      onApply={apply}
    />,
  );
  fireEvent.change(screen.getByRole("slider", { name: /Label size/ }), {
    target: { value: "14" },
  });
  const scatter: PlotResult = {
    ...base,
    version_id: "version_scatter",
    controls: [
      {
        id: "marker_radius",
        label: "Marker radius",
        group: "fit",
        update_strategy: "rerun",
        type: "number",
        value: 3,
        minimum: 1,
        maximum: 7,
        step: 1,
      },
      {
        id: "fit",
        label: "Show fit",
        group: "fit",
        update_strategy: "rerun",
        type: "boolean",
        value: true,
      },
      {
        id: "band",
        label: "Fit band",
        group: "fit",
        update_strategy: "rerun",
        type: "boolean",
        value: true,
        visible_when: { control_id: "fit", equals: true },
      },
    ],
    control_groups: [{ id: "fit", label: "Trend settings" }],
  };
  rerender(
    <FigureInspector
      projectId="project_1"
      result={scatter}
      disabled={false}
      onApply={apply}
    />,
  );
  expect(
    screen.queryByRole("slider", { name: /Label size/ }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("slider", { name: /Marker radius/ })).toHaveValue(
    "3",
  );
  expect(screen.getByRole("checkbox", { name: "Fit band" })).toBeVisible();
  await user.click(screen.getByRole("checkbox", { name: "Show fit" }));
  expect(
    screen.queryByRole("checkbox", { name: "Fit band" }),
  ).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "Apply as new version" }),
  );
  expect(apply).toHaveBeenCalledWith({ fit: false }, expect.any(String));
});

test("failed submissions keep draft values and reuse their request key", async () => {
  const user = userEvent.setup();
  const apply = vi
    .fn()
    .mockRejectedValueOnce(new Error("Connection interrupted"))
    .mockResolvedValue(true);
  render(
    <FigureInspector
      projectId="project_1"
      result={base}
      disabled={false}
      onApply={apply}
    />,
  );
  await user.clear(screen.getByRole("textbox", { name: "Title" }));
  await user.type(
    screen.getByRole("textbox", { name: "Title" }),
    "Updated expression",
  );
  await user.click(
    screen.getByRole("button", { name: "Apply as new version" }),
  );
  expect(screen.getByRole("alert")).toHaveTextContent("Connection interrupted");
  expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue(
    "Updated expression",
  );
  await user.click(
    screen.getByRole("button", { name: "Apply as new version" }),
  );
  expect(apply.mock.calls[0]?.[1]).toBe(apply.mock.calls[1]?.[1]);
});

test("read-only versions and active runs cannot submit changes", () => {
  const { rerender } = render(
    <FigureInspector
      projectId="project_1"
      result={{ ...base, parameter_updates_available: false }}
      disabled={false}
      onApply={async () => true}
    />,
  );
  expect(screen.getByRole("textbox", { name: "Title" })).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Apply as new version" }),
  ).toBeDisabled();
  rerender(
    <FigureInspector
      projectId="project_1"
      result={base}
      disabled
      onApply={async () => true}
    />,
  );
  expect(screen.getByRole("slider", { name: /Label size/ })).toBeDisabled();
});

test("main tabs support keyboard navigation with a unified small parameter form", async () => {
  const user = userEvent.setup();
  render(
    <FigureInspector
      projectId="project_1"
      result={base}
      disabled={false}
      onApply={async () => true}
    />,
  );
  const tabs = screen.getByRole("tablist", { name: "Figure details" });
  within(tabs).getByRole("tab", { name: "Parameters" }).focus();
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: "Data" })).toHaveFocus();
  expect(screen.getByRole("tab", { name: "Data" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await user.keyboard("{Home}");
  expect(screen.getByRole("group", { name: "Appearance" })).toBeVisible();
  expect(screen.getByRole("group", { name: "Distribution" })).toBeVisible();
});

test("runtime control schema rejects unknown types and invalid options or ranges", () => {
  expect(
    controlDefinitionSchema.safeParse({
      type: "script",
      id: "x",
      label: "x",
      value: "alert(1)",
    }).success,
  ).toBe(false);
  expect(
    controlDefinitionSchema.safeParse({
      type: "number",
      id: "x",
      label: "x",
      value: 7,
      minimum: 0,
      maximum: 3,
      step: 1,
    }).success,
  ).toBe(false);
  expect(
    controlDefinitionSchema.safeParse({
      type: "choice",
      id: "x",
      label: "x",
      value: "missing",
      options: [{ value: "yes", label: "Yes" }],
    }).success,
  ).toBe(false);
});

function withControlCount(count: number): PlotResult {
  return {
    ...base,
    controls: [
      ...base.controls!,
      ...Array.from({ length: count - base.controls!.length }, (_, index) => ({
        id: `extra_${index}`,
        label: `Option ${index + 1}`,
        type: "boolean" as const,
        value: true,
        group: "distribution",
        update_strategy: "rerun" as const,
      })),
    ],
  };
}

test.each([8, 24, 25])(
  "uses sections only when %i controls need them",
  (count) => {
    render(
      <FigureInspector
        projectId="project_1"
        result={withFigureSize(withControlCount(count))}
        disabled={false}
        onApply={async () => true}
      />,
    );
    const tabs = screen.queryByRole("tablist", { name: "Parameter sections" });
    if (count <= 24) {
      expect(tabs).not.toBeInTheDocument();
      expect(
        screen.getByRole("checkbox", { name: "Observations" }),
      ).toBeVisible();
    } else {
      expect(tabs).toBeVisible();
      expect(
        screen.queryByRole("checkbox", { name: "Observations" }),
      ).not.toBeInTheDocument();
    }
  },
);

test("large forms retain drafts across sections and support keyboard navigation", async () => {
  const user = userEvent.setup();
  const apply = vi.fn(async () => true);
  render(
    <FigureInspector
      projectId="project_1"
      result={withFigureSize(withControlCount(25))}
      disabled={false}
      onApply={apply}
    />,
  );
  fireEvent.change(screen.getByRole("spinbutton", { name: "Figure width" }), {
    target: { value: "12" },
  });
  fireEvent.change(screen.getByRole("slider", { name: /Label size/ }), {
    target: { value: "13" },
  });
  screen.getByRole("tab", { name: "Appearance" }).focus();
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: "Distribution" })).toHaveFocus();
  expect(screen.getByRole("tabpanel", { name: "Distribution" })).toBeVisible();
  expect(screen.getByRole("spinbutton", { name: "Figure width" })).toHaveValue(
    12,
  );
  expect(
    screen.queryByRole("tab", { name: "Figure size" }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("checkbox", { name: "Observations" }));
  await user.click(screen.getByRole("tab", { name: "Appearance" }));
  expect(screen.getByRole("slider", { name: /Label size/ })).toHaveValue("13");
  await user.click(
    screen.getByRole("button", { name: "Apply as new version" }),
  );
  expect(apply).toHaveBeenCalledWith(
    { figure_width: 12, label_size: 13, show_points: false },
    expect.any(String),
  );
});

test("a single populated group does not add a redundant sub-tab", () => {
  const result = withControlCount(25);
  result.controls = result.controls!.map((control) => ({
    ...control,
    group: "appearance",
  }));
  render(
    <FigureInspector
      projectId="project_1"
      result={result}
      disabled={false}
      onApply={async () => true}
    />,
  );
  expect(
    screen.queryByRole("tablist", { name: "Parameter sections" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "Option 5" })).toBeVisible();
});

test("numeric size controls accept precise typed values and keep empty drafts invalid", async () => {
  const user = userEvent.setup();
  const apply = vi.fn(async () => true);
  render(
    <FigureInspector
      projectId="project_1"
      result={{
        ...base,
        controls: [
          {
            id: "figure_width",
            label: "Figure width",
            group: "figure_size",
            update_strategy: "rerun",
            type: "number",
            input_mode: "number",
            value: 9,
            minimum: 2,
            maximum: 30,
            step: 0.01,
            unit: "in",
          },
        ],
        control_groups: [{ id: "figure_size", label: "Figure size" }],
      }}
      disabled={false}
      onApply={apply}
    />,
  );
  const width = screen.getByRole("spinbutton", { name: "Figure width" });
  await user.clear(width);
  expect(
    screen.getByRole("button", { name: "Apply as new version" }),
  ).toBeDisabled();
  await user.type(width, "12.25");
  await user.click(
    screen.getByRole("button", { name: "Apply as new version" }),
  );
  expect(apply).toHaveBeenCalledWith(
    { figure_width: 12.25 },
    expect.any(String),
  );
});

function withFigureSize(result: PlotResult): PlotResult {
  return {
    ...result,
    control_groups: [
      ...result.control_groups!,
      { id: "figure_size", label: "Figure size" },
    ],
    controls: [
      ...result.controls!,
      ...["height", "width"].map((dimension) => ({
        id: `figure_${dimension}`,
        label: `Figure ${dimension}`,
        group: "figure_size",
        update_strategy: "rerun" as const,
        type: "number" as const,
        input_mode: "number" as const,
        value: dimension === "width" ? 9 : 6,
        minimum: 2,
        maximum: 30,
        step: 0.01,
        unit: "in",
      })),
    ],
  };
}

test("figure size has a stable first position and other groups keep their labels", async () => {
  const user = userEvent.setup();
  render(
    <FigureInspector
      projectId="project_1"
      result={withFigureSize(base)}
      disabled={false}
      onApply={async () => true}
    />,
  );
  const groups = screen.getAllByRole("group");
  expect(
    groups.map((group) => group.querySelector("legend")?.textContent?.trim()),
  ).toEqual(["Figure size", "Appearance", "Distribution"]);
  expect(
    within(groups[0]!)
      .getAllByRole("spinbutton")
      .map((input) => input.id),
  ).toEqual([
    expect.stringContaining("control-figure_width"),
    expect.stringContaining("control-figure_height"),
  ]);
  expect(
    within(groups[1]!).getByRole("textbox", { name: "Title" }),
  ).toBeVisible();
  expect(
    within(groups[2]!).getByRole("checkbox", { name: "Observations" }),
  ).toBeVisible();
  fireEvent.change(screen.getByRole("spinbutton", { name: "Figure width" }), {
    target: { value: "15" },
  });
  await user.click(screen.getByRole("checkbox", { name: "Observations" }));
  await user.click(screen.getByRole("button", { name: "Reset" }));
  expect(screen.getByRole("spinbutton", { name: "Figure width" })).toHaveValue(
    9,
  );
  expect(screen.getByRole("checkbox", { name: "Observations" })).toBeChecked();
  expect(
    screen.getByRole("button", { name: "Apply as new version" }),
  ).toBeDisabled();
});

test("dynamic group descriptions and conditional fields remain associated with their controls", async () => {
  const user = userEvent.setup();
  const result: PlotResult = {
    ...base,
    controls: [
      {
        ...base.controls![3]!,
        group: "custom",
        description: "Show the measured values.",
      },
      {
        ...base.controls![0]!,
        group: "custom",
        visible_when: { control_id: "show_points", equals: true },
      },
    ],
    control_groups: [
      {
        id: "custom",
        label: "Measurements",
        description: "Customize the observations in this figure.",
      },
    ],
  };
  render(
    <FigureInspector
      projectId="project_1"
      result={result}
      disabled={false}
      onApply={async () => true}
    />,
  );
  const group = screen.getByRole("group", { name: "Measurements" });
  expect(
    within(group).getByText("Customize the observations in this figure."),
  ).toBeVisible();
  const observations = within(group).getByRole("checkbox", {
    name: "Observations",
  });
  expect(observations).toHaveAccessibleDescription("Show the measured values.");
  await user.click(observations);
  expect(
    screen.queryByRole("textbox", { name: "Title" }),
  ).not.toBeInTheDocument();
  expect(group).toBeVisible();
  expect(
    screen.queryByRole("tablist", { name: "Parameter sections" }),
  ).not.toBeInTheDocument();
});
