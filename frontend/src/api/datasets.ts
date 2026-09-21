import { request } from "./client";
import {
  analysisResultListSchema,
  datasetListSchema,
  datasetSchema,
  platformDatasetListSchema,
  uploadReceiptSchema,
} from "./schemas/datasets";

export function listDatasets(projectId: string, offset = 0) {
  return request(
    `/api/v1/projects/${encodeURIComponent(projectId)}/datasets?offset=${offset}`,
    datasetListSchema,
  );
}
export function listAnalysisResults(projectId: string, offset = 0) {
  return request(
    `/api/v1/projects/${encodeURIComponent(projectId)}/analysis-results?offset=${offset}`,
    analysisResultListSchema,
  );
}
export function listPlatformDatasets(
  projectId: string,
  cursor?: string | null,
) {
  return request(
    `/api/v1/projects/${encodeURIComponent(projectId)}/data-sources/analysis-platform${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
    platformDatasetListSchema,
  );
}
export function createDataset(
  projectId: string,
  name: string,
  description = "",
  sourceId?: string,
) {
  return request("/api/v1/data-bundles", datasetSchema, {
    method: "POST",
    body: JSON.stringify({
      project_id: projectId,
      name,
      description,
      source_kind: sourceId ? "analysis_platform" : "upload",
      source_id: sourceId,
    }),
  });
}
export function uploadDataFile(
  projectId: string,
  datasetId: string,
  file: File,
) {
  return request(
    `/api/v1/data-bundles/${encodeURIComponent(datasetId)}/files?project_id=${encodeURIComponent(projectId)}&name=${encodeURIComponent(file.name)}`,
    uploadReceiptSchema,
    {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: file,
    },
  );
}
export function finalizeDataset(
  projectId: string,
  datasetId: string,
  refresh = false,
) {
  return request(
    `/api/v1/data-bundles/${encodeURIComponent(datasetId)}/${refresh ? "refresh" : "finalize"}?project_id=${encodeURIComponent(projectId)}`,
    datasetSchema,
    { method: "POST" },
  );
}
export function updateDatasetDescription(
  projectId: string,
  datasetId: string,
  revisionId: string,
  name: string,
  description: string,
) {
  return request(
    `/api/v1/data-bundles/${encodeURIComponent(datasetId)}`,
    datasetSchema,
    {
      method: "PATCH",
      body: JSON.stringify({
        project_id: projectId,
        base_revision_id: revisionId,
        name,
        description,
      }),
    },
  );
}
