from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from uuid import uuid4

from vis_platform_backend.agents.data_agent import DataAgent
from vis_platform_backend.config import Settings
from vis_platform_backend.contracts.datasets import (
    AnalysisResultList,
    CreateDatasetRequest,
    Dataset,
    DatasetList,
    DatasetMetadataPatch,
    ObjectDescription,
    ObjectReference,
    UploadReceipt,
)
from vis_platform_backend.data.profiling import content_hash
from vis_platform_backend.data.providers import (
    AnalysisPlatformProvider,
    SourceObject,
)
from vis_platform_backend.data.repository import DatasetRepository
from vis_platform_backend.execution.runner import RWorker
from vis_platform_backend.infrastructure.database import Repository, utc_now

from .demo_transcriptomics import DEMO_SOURCE_IDS, DemoTranscriptomicsProvider
from .errors import DataError as DataError
from .ingestion import DatasetIngestor
from .platform_catalog import PlatformCatalog
from .relationships import validate_relationships


class DatasetService:
    def __init__(
        self,
        repository: Repository,
        store: DatasetRepository,
        settings: Settings,
        agent: DataAgent,
        worker: RWorker,
    ) -> None:
        self.repository, self.store, self.settings, self.agent, self.worker = (
            repository,
            store,
            settings,
            agent,
            worker,
        )
        self.root = (settings.artifact_root.parent / "datasets").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.platform = PlatformCatalog(
            AnalysisPlatformProvider(
                settings.analysis_platform_url,
                settings.analysis_platform_token,
                settings.upload_limit_bytes,
            ),
            DemoTranscriptomicsProvider(self.root / "builtin-platform"),
        )
        self.ingestion = DatasetIngestor(store, agent, worker, self.platform, self.root)
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.resolution_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self.store.recover()

    def check_project(self, project_id: str) -> None:
        if not self.repository.project_exists(project_id):
            raise DataError("The project was not found.", "NOT_FOUND", 404)

    def get(self, project_id: str, dataset_id: str, revision_id: str | None = None) -> Dataset:
        dataset = self.store.get_dataset(project_id, dataset_id, revision_id)
        if dataset is None:
            raise DataError(
                "The dataset or revision was not found in this project.", "NOT_FOUND", 404
            )
        return dataset

    def list_datasets(self, project_id: str, offset: int = 0, limit: int = 30) -> DatasetList:
        self.check_project(project_id)
        datasets, total = self.store.list_datasets(project_id, offset, limit)
        return DatasetList(
            datasets=datasets, total=total, offset=offset, complete=offset + len(datasets) >= total
        )

    def results(self, project_id: str, offset: int = 0, limit: int = 30) -> AnalysisResultList:
        self.check_project(project_id)
        results, total = self.store.list_results(project_id, offset, limit)
        return AnalysisResultList(
            results=results, total=total, offset=offset, complete=offset + len(results) >= total
        )

    def create(self, request: CreateDatasetRequest) -> Dataset:
        self.check_project(request.project_id)
        source_id = request.source_id or f"upload_{uuid4().hex}"
        existing = self.store.find_source(request.project_id, request.source_kind, source_id)
        if existing is not None:
            return existing
        if (
            request.source_kind == "analysis_platform"
            and self.settings.analysis_platform_url is None
            and source_id not in DEMO_SOURCE_IDS
        ):
            raise DataError("The analysis platform is not connected.")
        now = utc_now()
        dataset = Dataset(
            dataset_id=f"dataset_{uuid4().hex}",
            project_id=request.project_id,
            name=request.name,
            description=request.description,
            source_id=source_id,
            source_kind=request.source_kind,
            contains_demo_data=request.source_kind == "analysis_platform"
            and source_id in DEMO_SOURCE_IDS,
            created_at=now,
            updated_at=now,
        )
        self.store.save_dataset(dataset)
        return dataset

    def upload_path(self, project_id: str, dataset_id: str, name: str) -> tuple[str, Path]:
        dataset = self.get(project_id, dataset_id)
        if dataset.source_kind != "upload" or dataset.state != "uploading":
            raise DataError("Files can only be added to an unfinished upload.")
        if (
            Path(name).name != name
            or not name
            or len(name) > 200
            or any(ord(char) < 32 for char in name)
        ):
            raise DataError("Use a plain file name.", "INVALID_FILE_NAME", 422)
        if len(self.store.files(dataset_id)) >= 30:
            raise DataError("An upload can contain up to 30 files.")
        file_id = f"file_{uuid4().hex}"
        directory = self.root / dataset_id / "originals"
        directory.mkdir(parents=True, exist_ok=True)
        return file_id, directory / file_id

    def finish_upload(
        self, dataset_id: str, file_id: str, name: str, path: Path, size: int
    ) -> UploadReceipt:
        try:
            self.store.add_file(dataset_id, file_id, name, path, size)
        except sqlite3.IntegrityError as error:
            path.unlink(missing_ok=True)
            raise DataError(
                "This upload already contains a file with that name.", "DUPLICATE_FILE"
            ) from error
        return UploadReceipt(file_id=file_id, name=name, size=size)

    def finalize(self, project_id: str, dataset_id: str, *, refresh: bool = False) -> Dataset:
        dataset = self.get(project_id, dataset_id)
        if dataset.state == "processing" or (dataset.state == "ready" and not refresh):
            return dataset
        if dataset.source_kind == "upload" and not self.store.files(dataset_id):
            raise DataError("Upload at least one file before inspection.", "FILES_REQUIRED", 422)
        dataset.state = "processing"
        dataset.updated_at = utc_now()
        self.store.save_dataset(dataset)
        task = asyncio.create_task(self.ingestion.ingest(dataset))
        self.tasks[dataset_id] = task
        task.add_done_callback(lambda _task: self.tasks.pop(dataset_id, None))
        return dataset

    async def materialize(
        self, project_id: str, reference: ObjectReference
    ) -> tuple[ObjectDescription, Path, str]:
        lock = self.resolution_locks.setdefault(
            (reference.revision_id, reference.object_id), asyncio.Lock()
        )
        async with lock:
            item = self.inspect(project_id, reference)
            bindings = self.store.bindings(project_id, reference.revision_id)
            binding = bindings.get(reference.object_id) if bindings else None
            if binding is None:
                raise DataError("The selected input was not found.", "NOT_FOUND", 404)
            if not binding.get("path"):
                if "materialize" not in item.capabilities or "source_object" not in binding:
                    raise DataError("The selected object cannot be materialized.")
                source = SourceObject.model_validate(binding["source_object"])
                if source.sha256 is None:
                    latest = await self.platform.describe(binding["source_id"])
                    if latest.revision != binding["source_revision"]:
                        raise DataError(
                            "This uncached source revision is no longer current. Refresh the "
                            "dataset before recomputing."
                        )
                directory = (
                    self.root / item.owner_id / reference.revision_id / f"resolved_{uuid4().hex}"
                )
                directory.mkdir(parents=True)
                raw = directory / "source"
                await self.platform.materialize(source, raw)
                if source.sha256 and content_hash(raw).lower() != source.sha256.lower():
                    raise DataError(
                        "The requested source revision changed. Re-import the updated dataset."
                    )
                if source.sha256 is None:
                    latest = await self.platform.describe(binding["source_id"])
                    if latest.revision != binding["source_revision"]:
                        raise DataError(
                            "The source changed during retrieval. Refresh the dataset before "
                            "recomputing."
                        )
                owner = self.get(project_id, item.owner_id, reference.revision_id)
                parsed = await self.ingestion._parse(
                    raw,
                    f"source.{source.description.format}",
                    owner,
                    reference.revision_id,
                    directory / "parsed",
                    source.object_path,
                )
                if len(parsed) != 1:
                    raise DataError("The selected source must resolve exactly one logical object.")
                measured = parsed[0]
                if measured.description.readiness != "ready":
                    raise DataError("The selected source object could not be parsed.")
                if item.dimensions and item.dimensions != measured.description.dimensions:
                    raise DataError(
                        "The object dimensions do not match the recorded source description."
                    )
                if item.columns and {column.name for column in item.columns} != {
                    column.name for column in measured.description.columns
                }:
                    raise DataError(
                        "The object columns do not match the recorded source description."
                    )
                self.store.cache_object(
                    project_id,
                    reference.revision_id,
                    item.object_id,
                    {
                        "path": str(measured.path),
                        "format": measured.description.format,
                        "hash": measured.description.content_hash,
                        "profile": measured.description.model_dump(mode="json"),
                    },
                )
            return self.resolve(project_id, reference)

    def resolve(
        self, project_id: str, reference: ObjectReference
    ) -> tuple[ObjectDescription, Path, str]:
        owner = self.store.object_owner(project_id, reference.revision_id)
        descriptor = (
            next(
                (
                    item
                    for item in owner.objects
                    if item.object_id == reference.object_id
                    and item.revision_id == reference.revision_id
                ),
                None,
            )
            if owner
            else None
        )
        bindings = self.store.bindings(project_id, reference.revision_id)
        item = bindings.get(reference.object_id) if bindings else None
        if descriptor is None or item is None:
            raise DataError(
                "The selected object revision was not found in this project.", "NOT_FOUND", 404
            )
        if descriptor.readiness != "ready" or "materialize" not in descriptor.capabilities:
            raise DataError("The selected object is not ready for execution.")
        if not item.get("path"):
            raise DataError("The selected input needs to be resolved before execution.")
        path = Path(item["path"])
        roots = (self.root, self.settings.artifact_root.resolve())
        if (
            path.is_symlink()
            or not any(path.resolve().is_relative_to(root) for root in roots)
            or not path.is_file()
        ):
            raise DataError(
                "The saved input is no longer available. Historical recomputation cannot continue."
            )
        if content_hash(path) != item["hash"]:
            raise DataError(
                "The saved input changed. Re-import it as a new revision before recomputing."
            )
        return self.inspect(project_id, reference), path, item["format"]

    def dataset_ids_for_objects(
        self, project_id: str, references: list[ObjectReference]
    ) -> set[str]:
        dataset_ids: set[str] = set()
        visited: set[str] = set()
        pending = list(references)
        while pending:
            reference = pending.pop()
            item = self.inspect(project_id, reference)
            if item.owner_kind == "dataset":
                dataset_ids.add(item.owner_id)
            elif item.owner_id not in visited:
                visited.add(item.owner_id)
                result = self.store.get_result(project_id, item.owner_id)
                if result:
                    pending.extend(result.inputs)
        return dataset_ids

    def inspect(self, project_id: str, reference: ObjectReference) -> ObjectDescription:
        owner = self.store.object_owner(project_id, reference.revision_id)
        item = (
            next((item for item in owner.objects if item.object_id == reference.object_id), None)
            if owner
            else None
        )
        if item is None:
            raise DataError("The object was not found in this project.", "NOT_FOUND", 404)
        bindings = self.store.bindings(project_id, reference.revision_id)
        cached = bindings.get(reference.object_id, {}) if bindings else {}
        if cached.get("profile"):
            measured = ObjectDescription.model_validate(cached["profile"])
            semantics = {column.name: column for column in item.columns}
            for column in measured.columns:
                if column.name in semantics:
                    declared = semantics[column.name]
                    column.description, column.unit, column.meaning_origin = (
                        declared.description,
                        declared.unit,
                        declared.meaning_origin or "source",
                    )
            item = item.model_copy(
                update={
                    "dimensions": measured.dimensions,
                    "columns": measured.columns,
                    "kind": measured.kind,
                    "content_hash": cached["hash"],
                    "scalar": measured.scalar,
                }
            )
        return item

    def patch(self, dataset_id: str, patch: DatasetMetadataPatch) -> Dataset:
        dataset = self.get(patch.project_id, dataset_id)
        if dataset.state != "ready" or dataset.revision_id != patch.base_revision_id:
            raise DataError("The dataset changed. Reload before editing its description.")
        original = dataset.model_dump_json()
        bindings = self.store.bindings(dataset.project_id, patch.base_revision_id)
        assert bindings is not None
        if patch.name is not None:
            dataset.name = patch.name
        if patch.description is not None:
            dataset.description = patch.description
        if patch.relationships is not None:
            dataset.relationships = [
                item.model_copy(update={"origin": "user", "validation": "declared"})
                for item in patch.relationships
            ]
        objects = {item.object_id: item for item in dataset.objects}
        for meaning in patch.objects:
            target = objects.get(meaning.object_id)
            if target is None:
                raise DataError(
                    "The metadata patch references an unknown object.", "INVALID_METADATA", 422
                )
            for field in ("name", "description", "observation_unit"):
                if field in meaning.model_fields_set:
                    value = getattr(meaning, field)
                    if field == "description" and value is None:
                        value = ""
                    if field == "name" and value is None:
                        raise DataError("Object names cannot be empty.", "INVALID_METADATA", 422)
                    setattr(target, field, value)
                    target.description_origin = "user"
            columns = {item.name: item for item in target.columns}
            for column_patch in meaning.columns:
                column = columns.get(column_patch.name)
                if column is None:
                    raise DataError(
                        "The metadata patch references an unknown column.", "INVALID_METADATA", 422
                    )
                for field in ("description", "unit"):
                    if field in column_patch.model_fields_set:
                        setattr(column, field, getattr(column_patch, field))
                        column.meaning_origin = "user"
        validate_relationships(dataset, bindings)
        if dataset.model_dump_json() == original:
            return dataset
        dataset.revision_id = f"revision_{uuid4().hex}"
        dataset.updated_at = utc_now()
        for item in dataset.objects:
            item.revision_id = dataset.revision_id
        self.store.save_revision(dataset, bindings)
        return dataset

    async def shutdown(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
