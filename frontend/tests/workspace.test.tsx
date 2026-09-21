import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { expect, test } from "vitest";

import { WorkspacePage } from "../src/pages/WorkspacePage";

function renderWorkspace() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WorkspacePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("renders the agreed split workspace and empty state", () => {
  renderWorkspace();

  expect(
    screen.getByRole("region", { name: "Plot canvas" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("complementary", { name: "Plot conversation" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: /shape the figure/i }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("textbox", { name: "Describe the plot you want" }),
  ).toBeInTheDocument();
});
