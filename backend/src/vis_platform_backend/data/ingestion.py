from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from vis_platform_backend.agents.data_agent import DataAgent
from vis_platform_backend.agents.structured import StructuredAgentError
from vis_platform_backend.contracts.datasets import (
    Dataset,
    ObjectDescription,
)
from vis_platform_backend.data.profiling import ParsedObject, content_hash, parse_file
from vis_platform_backend.data.providers import (
    SourceProvider,
    UploadedFilesProvider,
)
from vis_platform_backend.data.repository import DatasetRepository
from vis_platform_backend.execution.runner import RExecutionError, RWorker, output_file
from vis_platform_backend.infrastructure.database import utc_now

from .errors import DataError
from .relationships import validate_relationships


class DatasetIngestor:
    def __init__(
        self,
        store: DatasetRepository,
        agent: DataAgent,
        worker: RWorker,
        platform: SourceProvider,
        root: Path,
    ) -> None:
        self.store, self.agent, self.worker, self.platform, self.root = (
            store,
            agent,
            worker,
            platform,
            root,
        )

    async def _parse(
        self,
        path: Path,
        name: str,
        dataset: Dataset,
        revision: str,
        directory: Path,
        object_path: list[str | int] | None = None,
    ) -> list[ParsedObject]:
        directory.mkdir(parents=True, exist_ok=True)
        if Path(name).suffix.lower() != ".rds" or not self.worker.available:
            return await asyncio.to_thread(
                parse_file, path, name, dataset.dataset_id, revision, directory, object_path
            )
        output = await self.worker.execute(
            {
                "mode": "profile",
                "object_path": object_path or [],
                "expand_collection": object_path is None,
            },
            {"file": (path, "rds")},
        )
        objects = []
        for index, item in enumerate(output.response.get("objects", [])):
            target = directory / f"object-{index}.rds"
            shutil.copyfile(output_file(output, item["filename"]), target)
            descriptor = ObjectDescription.model_validate(
                {
                    "object_id": "",
                    "owner_id": dataset.dataset_id,
                    "revision_id": revision,
                    "name": item["selector"],
                    "kind": item["kind"],
                    "format": "rds",
                    "dimensions": item["dimensions"] or [],
                    "scalar": item.get("scalar"),
                    "columns": item["columns"],
                    "capabilities": ["inspect", "materialize"],
                    "content_hash": content_hash(target),
                    "description": "An object inspected from the uploaded R collection.",
                    "extensions": {"r_class": item.get("native_class", [])},
                }
            )
            objects.append(
                ParsedObject(selector=item["selector"], path=target, description=descriptor)
            )
        shutil.rmtree(output.directory.parent, ignore_errors=True)
        return objects

    async def ingest(self, dataset: Dataset) -> None:
        previous = (
            self.store.get_dataset(dataset.project_id, dataset.dataset_id, dataset.revision_id)
            if dataset.revision_id
            else None
        )
        revision = f"revision_{uuid4().hex}"
        directory = self.root / dataset.dataset_id / revision
        directory.mkdir(parents=True)
        bindings: dict[str, Any] = {}
        try:
            dataset.objects, dataset.relationships, dataset.notices = [], [], []
            provider: SourceProvider = (
                self.platform
                if dataset.source_kind == "analysis_platform"
                else UploadedFilesProvider(
                    dataset.source_id,
                    dataset.name,
                    dataset.description,
                    self.store.files(dataset.dataset_id),
                )
            )
            manifest = await provider.describe(dataset.source_id)
            previous = (
                self.store.get_dataset(dataset.project_id, dataset.dataset_id, dataset.revision_id)
                if dataset.revision_id
                else None
            )
            if (
                dataset.source_kind == "analysis_platform"
                and previous
                and previous.source_revision == manifest.revision
            ):
                self.store.save_dataset(previous)
                return
            dataset.name, dataset.description = manifest.name, manifest.description
            dataset.source_revision = manifest.revision
            dataset.contains_demo_data = manifest.contains_demo_data
            mapped_ids = {
                item.source_object_id: self._object_id(dataset.dataset_id, item.source_object_id)
                for item in manifest.objects
            }
            if len(mapped_ids) != len(manifest.objects):
                raise DataError("The source contains duplicate object identifiers.")
            if dataset.source_kind == "analysis_platform":
                for source_object in manifest.objects:
                    descriptor: ObjectDescription = source_object.description.model_copy(deep=True)
                    descriptor.object_id = mapped_ids[source_object.source_object_id]
                    descriptor.owner_id, descriptor.revision_id = dataset.dataset_id, revision
                    descriptor.owner_kind, descriptor.description_origin = "dataset", "source"
                    supported = descriptor.format in {"csv", "tsv", "json", "jsonl", "ndjson"} or (
                        descriptor.format == "rds" and self.worker.available
                    )
                    descriptor.readiness = "ready" if supported else "unsupported"
                    descriptor.capabilities = (
                        ["inspect", "materialize"] if supported else ["inspect"]
                    )
                    dataset.objects.append(descriptor)
                    bindings[descriptor.object_id] = {
                        "source_object": source_object.model_dump(mode="json"),
                        "source_id": manifest.source_id,
                        "source_revision": manifest.revision,
                    }
            for index, source_object in enumerate(
                manifest.objects if dataset.source_kind == "upload" else []
            ):
                target = directory / f"source-{index}"
                await provider.materialize(source_object, target)
                if source_object.sha256 and content_hash(target) != source_object.sha256:
                    raise DataError("A source object changed while it was being imported.")
                try:
                    parsed = await self._parse(
                        target,
                        f"source.{source_object.description.format}",
                        dataset,
                        revision,
                        directory / f"parsed-{index}",
                        source_object.object_path
                        if dataset.source_kind == "analysis_platform"
                        else None,
                    )
                except (ValueError, UnicodeError, RExecutionError, TimeoutError):
                    failed = ObjectDescription(
                        object_id=mapped_ids[source_object.source_object_id],
                        owner_id=dataset.dataset_id,
                        revision_id=revision,
                        name=source_object.description.name,
                        kind="unknown",
                        format=source_object.description.format,
                        readiness="failed",
                        limitations=[
                            "This object could not be inspected with the available parser."
                        ],
                    )
                    dataset.objects.append(failed)
                    continue
                for item in parsed:
                    descriptor = item.description
                    descriptor.object_id = self._object_id(
                        dataset.dataset_id, source_object.source_object_id + ":" + item.selector
                    )
                    if len(parsed) == 1:
                        descriptor.name = Path(source_object.description.name).stem
                    dataset.objects.append(descriptor)
                    bindings[descriptor.object_id] = {
                        "path": str(item.path),
                        "format": descriptor.format,
                        "hash": descriptor.content_hash,
                    }
                if len(dataset.objects) > 100:
                    raise DataError("A collection can contain up to 100 logical objects.")
            for relation in manifest.relationships:
                if (
                    relation.left_object_id not in mapped_ids
                    or relation.right_object_id not in mapped_ids
                ):
                    raise DataError("A source relationship references an unknown object.")
                dataset.relationships.append(
                    relation.model_copy(
                        update={
                            "left_object_id": mapped_ids[relation.left_object_id],
                            "right_object_id": mapped_ids[relation.right_object_id],
                            "origin": "source",
                            "validation": "declared",
                        }
                    )
                )
            if dataset.source_kind == "analysis_platform":
                dataset.interpretation_status = "source_provided"
            else:
                try:
                    interpretation = await self.agent.interpret(
                        {
                            "name": dataset.name,
                            "user_description": dataset.description,
                            "objects": [item.model_dump(mode="json") for item in dataset.objects],
                        }
                    )
                    candidate = dataset.model_copy(deep=True)
                    descriptions = {item.object_id: item for item in candidate.objects}
                    if any(item.object_id not in descriptions for item in interpretation.objects):
                        raise ValueError("Interpretation references an unknown object.")
                    for meaning in interpretation.objects:
                        described_object = descriptions[meaning.object_id]
                        (
                            described_object.name,
                            described_object.description,
                            described_object.observation_unit,
                        ) = (
                            meaning.name,
                            meaning.description,
                            meaning.observation_unit,
                        )
                        described_object.description_origin = "inferred"
                    candidate.description = interpretation.description
                    candidate.relationships = [
                        item.model_copy(update={"origin": "inferred", "validation": "declared"})
                        for item in interpretation.relationships
                    ]
                    validate_relationships(candidate, bindings)
                    candidate.interpretation_status = "interpreted"
                    dataset = candidate
                except (StructuredAgentError, ValueError, DataError):
                    dataset.interpretation_status = "unavailable"
                    dataset.notices.append(
                        "File structures are available. Automatic interpretation could "
                        "not be completed; describe their meaning in the conversation."
                    )
            validate_relationships(dataset, bindings)
            dataset.revision_id, dataset.state, dataset.updated_at = revision, "ready", utc_now()
            self.store.save_revision(dataset, bindings)
        except asyncio.CancelledError:
            dataset = previous or dataset
            dataset.state = "ready" if previous else "failed"
            dataset.notices = ["Data inspection was interrupted. Retry to continue."]
            self.store.save_dataset(dataset)
        except Exception:
            dataset = previous or dataset
            dataset.state = "ready" if previous else "failed"
            dataset.notices = [
                "The collection could not be imported. Check its format or connection and retry."
            ]
            self.store.save_dataset(dataset)

    @staticmethod
    def _object_id(dataset_id: str, source_id: str) -> str:
        return "object_" + hashlib.sha256((dataset_id + ":" + source_id).encode()).hexdigest()[:24]
