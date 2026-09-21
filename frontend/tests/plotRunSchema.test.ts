import { expect, test } from "vitest";

import { plotRunAcceptedSchema } from "../src/api/schemas/plotRun";

const accepted = {
  schema_version: "1.0",
  run_id: "run_1",
  status: "queued",
  stage: "received",
  links: {
    status: "/api/v1/plot-runs/run_1",
    events: "/api/v1/plot-runs/run_1/events",
    cancel: "/api/v1/plot-runs/run_1/cancel",
  },
};

test("accepts the backend plot-run envelope", () => {
  expect(plotRunAcceptedSchema.parse(accepted)).toEqual(accepted);
});

test("rejects unknown backend states", () => {
  expect(() =>
    plotRunAcceptedSchema.parse({ ...accepted, status: "ready" }),
  ).toThrow();
});

test("rejects backend links outside the versioned same-origin API", () => {
  expect(() =>
    plotRunAcceptedSchema.parse({
      ...accepted,
      links: { ...accepted.links, events: "https://example.com/events" },
    }),
  ).toThrow();
  expect(() =>
    plotRunAcceptedSchema.parse({
      ...accepted,
      links: { ...accepted.links, status: "/api/v1/../private" },
    }),
  ).toThrow();
});
