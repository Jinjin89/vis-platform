import { z } from "zod";
import type { components } from "../generated/schema";
type ArtifactReference = components["schemas"]["ArtifactReference"];

export const apiPathSchema = z.string().refine(
  (value) => {
    if (!value.startsWith("/api/v1/") || value.startsWith("//")) {
      return false;
    }
    const normalized = new URL(value, "https://vis-platform.invalid");
    return (
      normalized.origin === "https://vis-platform.invalid" &&
      normalized.pathname.startsWith("/api/v1/")
    );
  },
  { message: "Expected a same-origin /api/v1 path" },
);

export const artifactSchema: z.ZodType<ArtifactReference> = z
  .object({
    artifact_id: z.string(),
    role: z.enum([
      "preview",
      "publication",
      "data",
      "model",
      "script",
      "methods",
    ]),
    media_type: z.string(),
    href: apiPathSchema,
    description: z.string(),
  })
  .strict();
