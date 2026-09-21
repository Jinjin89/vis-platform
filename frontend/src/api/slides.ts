import { z } from "zod";
import { request } from "./client";
import { plotResultSchema } from "./schemas/plotRun";
import {
  reportBlockSchema,
  reportDatasetSchema,
  reportDocumentSchema,
  reportListSchema,
  presentationSettingsSchema,
  slideSettingsSchema,
} from "./schemas/reports";

export const slideDeckSchema = z
  .object({
    schema_version: z.literal("1.0").default("1.0"),
    title: z.string().min(1).max(200),
    datasets: z.array(reportDatasetSchema).max(50).default([]),
    presentation: presentationSettingsSchema.default({
      aspect_ratio: "16:9",
      theme: "paper",
    }),
    slides: z
      .array(
        z
          .object({
            id: z.string().min(1),
            title: z.string().min(1).max(200),
            elements: z.array(reportBlockSchema).max(200).default([]),
            settings: slideSettingsSchema.default({
              layout: "figure-summary",
              notes: "",
              frames: {},
            }),
          })
          .strict(),
      )
      .max(100)
      .default([]),
  })
  .strict();
export type SlideDeck = z.infer<typeof slideDeckSchema>;
const base = (projectId: string) =>
  `/api/v1/projects/${encodeURIComponent(projectId)}/slides`;
export const listSlideDecks = (projectId: string, offset = 0) =>
  request(`${base(projectId)}?offset=${offset}`, reportListSchema);
export const createSlideDeck = (
  projectId: string,
  content: SlideDeck,
  requestId: string,
) =>
  request(base(projectId), reportDocumentSchema, {
    method: "POST",
    body: JSON.stringify({ content, request_id: requestId }),
  });
export const exportSlideDeck = (projectId: string, deckId: string) =>
  request(
    `${base(projectId)}/${encodeURIComponent(deckId)}/content`,
    slideDeckSchema,
  );
export const linkSharedFigure = (
  projectId: string,
  plotId: string,
  versionId: string,
) =>
  request(
    `/api/v1/projects/${encodeURIComponent(projectId)}/shared-figures/${encodeURIComponent(plotId)}`,
    plotResultSchema,
    { method: "POST", body: JSON.stringify({ version_id: versionId }) },
  );
