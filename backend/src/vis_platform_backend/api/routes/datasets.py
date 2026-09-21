from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request, status

from vis_platform_backend.contracts.datasets import (
    AnalysisResult,
    AnalysisResultList,
    CreateDatasetRequest,
    Dataset,
    DatasetList,
    DatasetMetadataPatch,
    ObjectDescription,
    ObjectReference,
    PlatformDatasetList,
    UploadReceipt,
)
from vis_platform_backend.data.service import DataError, DatasetService

router = APIRouter(tags=["datasets"])


def get_data_service(request: Request) -> DatasetService:
    return cast(DatasetService, request.app.state.dataset_service)


DataDependency = Annotated[DatasetService, Depends(get_data_service)]


@router.get("/projects/{project_id}/datasets", response_model=DatasetList)
def list_datasets(
    project_id: str,
    service: DataDependency,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
) -> DatasetList:
    return service.list_datasets(project_id, offset, limit)


@router.get("/projects/{project_id}/analysis-results", response_model=AnalysisResultList)
def list_results(
    project_id: str,
    service: DataDependency,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
) -> AnalysisResultList:
    return service.results(project_id, offset, limit)


@router.get("/analysis-results/{result_id}", response_model=AnalysisResult)
def get_result(result_id: str, project_id: str, service: DataDependency) -> AnalysisResult:
    result = service.store.get_result(project_id, result_id)
    if result is None:
        raise DataError("The analysis result was not found in this project.", "NOT_FOUND", 404)
    return result


@router.get(
    "/projects/{project_id}/data-sources/analysis-platform", response_model=PlatformDatasetList
)
async def platform_datasets(
    project_id: str, service: DataDependency, cursor: str | None = None
) -> PlatformDatasetList:
    service.check_project(project_id)
    return await service.platform.discover(cursor)


@router.post("/data-bundles", response_model=Dataset, status_code=status.HTTP_201_CREATED)
def create_dataset(payload: CreateDatasetRequest, service: DataDependency) -> Dataset:
    return service.create(payload)


@router.get("/data-bundles/{dataset_id}", response_model=Dataset)
def get_dataset(
    dataset_id: str, project_id: str, service: DataDependency, revision_id: str | None = None
) -> Dataset:
    return service.get(project_id, dataset_id, revision_id)


@router.post(
    "/data-bundles/{dataset_id}/files",
    response_model=UploadReceipt,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload_file(
    dataset_id: str, project_id: str, name: str, request: Request, service: DataDependency
) -> UploadReceipt:
    file_id, path = service.upload_path(project_id, dataset_id, name)
    total = 0
    try:
        with path.open("xb") as destination:
            async for chunk in request.stream():
                total += len(chunk)
                if total > service.settings.upload_limit_bytes:
                    raise DataError(
                        "The file exceeds the current 32 MB upload limit.", "UPLOAD_TOO_LARGE", 413
                    )
                destination.write(chunk)
        if not total:
            raise DataError("The uploaded file is empty.", "EMPTY_UPLOAD", 422)
        return service.finish_upload(dataset_id, file_id, name, path, total)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


@router.post(
    "/data-bundles/{dataset_id}/finalize",
    response_model=Dataset,
    status_code=status.HTTP_202_ACCEPTED,
)
async def finalize_dataset(dataset_id: str, project_id: str, service: DataDependency) -> Dataset:
    return service.finalize(project_id, dataset_id)


@router.post(
    "/data-bundles/{dataset_id}/refresh",
    response_model=Dataset,
    status_code=status.HTTP_202_ACCEPTED,
)
async def refresh_dataset(dataset_id: str, project_id: str, service: DataDependency) -> Dataset:
    return service.finalize(project_id, dataset_id, refresh=True)


@router.patch("/data-bundles/{dataset_id}", response_model=Dataset)
def update_description(
    dataset_id: str, payload: DatasetMetadataPatch, service: DataDependency
) -> Dataset:
    return service.patch(dataset_id, payload)


@router.get("/objects/{object_id}", response_model=ObjectDescription)
async def inspect_object(
    object_id: str,
    revision_id: str,
    project_id: str,
    service: DataDependency,
    profile: bool = False,
) -> ObjectDescription:
    reference = ObjectReference(object_id=object_id, revision_id=revision_id)
    if profile:
        measured, _, _ = await service.materialize(project_id, reference)
        return measured
    return service.inspect(project_id, reference)
