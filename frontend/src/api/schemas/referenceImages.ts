import { z } from "zod";
import type { components } from "../generated/schema";
import { apiPathSchema } from "./artifacts";

export type ReferenceImage = components["schemas"]["ReferenceImage"];

export const referenceImageSchema: z.ZodType<ReferenceImage> = z
  .object({
    image_id: z.string(),
    project_id: z.string(),
    name: z.string(),
    media_type: z.literal("image/png").default("image/png"),
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    byte_size: z.number().int().positive(),
    created_at: z.string(),
    links: z
      .object({ content: apiPathSchema, thumbnail: apiPathSchema })
      .strict(),
  })
  .strict();
