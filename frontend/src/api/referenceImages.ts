import { apiUrl, checkResponse, request } from "./client";
import {
  referenceImageSchema,
  type ReferenceImage,
} from "./schemas/referenceImages";

export function uploadReferenceImage(
  projectId: string,
  file: File,
  signal: AbortSignal,
  requestId: string,
): Promise<ReferenceImage> {
  return request(
    `/api/v1/projects/${encodeURIComponent(projectId)}/plot-reference-images?name=${encodeURIComponent(file.name || "pasted-image.png")}`,
    referenceImageSchema,
    {
      method: "POST",
      signal,
      headers: {
        "Content-Type": "application/octet-stream",
        "Idempotency-Key": requestId,
      },
      body: file,
    },
  );
}

export async function deleteReferenceImage(
  image: ReferenceImage,
): Promise<void> {
  const response = await fetch(
    apiUrl(
      `/api/v1/projects/${encodeURIComponent(image.project_id)}/plot-reference-images/${encodeURIComponent(image.image_id)}`,
    ),
    { method: "DELETE" },
  );
  if (response.status !== 404 && response.status !== 409)
    await checkResponse(response);
}
