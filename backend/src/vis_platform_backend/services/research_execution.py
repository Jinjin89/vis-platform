from __future__ import annotations

import hashlib
import shutil
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from vis_platform_backend.agents.r_repair import RRepairAgent
from vis_platform_backend.contracts.artifacts import ArtifactReference
from vis_platform_backend.contracts.datasets import AnalysisResult, ObjectDescription
from vis_platform_backend.contracts.research import ResearchPlan
from vis_platform_backend.data.profiling import content_hash
from vis_platform_backend.data.service import DataError, DatasetService
from vis_platform_backend.domain.plot_marks import PLOT_MAP
from vis_platform_backend.execution.runner import RExecutionError, RWorker, output_file
from vis_platform_backend.infrastructure.database import Repository, utc_now
from vis_platform_backend.services.figure_controls import figure_controls, resolve_figure_size
from vis_platform_backend.services.figure_svg import validate_svg as validate_svg
from vis_platform_backend.services.point_maps import PointMapService
from vis_platform_backend.services.r_repair import RepairingRExecution


@dataclass(frozen=True)
class ResearchExecution:
    result: AnalysisResult
    preview: Path | None
    spec: dict[str, Any]


class ResearchExecutor:
    def __init__(
        self,
        data: DatasetService,
        worker: RWorker,
        repository: Repository,
        artifact_root: Path,
        repair_agent: RRepairAgent | None = None,
    ) -> None:
        self.data, self.worker, self.repository = data, worker, repository
        self.artifact_root = artifact_root.resolve()
        self.execution = RepairingRExecution(worker, repository, repair_agent)
        self.points = PointMapService(data, repository, artifact_root)

    def validate_plan(
        self, project_id: str, plan: ResearchPlan, selected_ids: list[str] | None = None
    ) -> None:
        if not self.worker.available and plan.point_map is None:
            raise DataError("The restricted R runtime is unavailable.")
        if plan.reuse_result_id:
            result = self.data.store.get_result(project_id, plan.reuse_result_id)
            if result is None:
                raise DataError(
                    "The requested analysis result was not found in this project.", "NOT_FOUND", 404
                )
            source_dataset_ids = self.data.dataset_ids_for_objects(project_id, result.inputs)
        else:
            for item in plan.inputs:
                descriptor = self.data.inspect(project_id, item.reference)
                if descriptor.readiness != "ready" or "materialize" not in descriptor.capabilities:
                    raise DataError("The plan requires an object that is not ready for execution.")
                # R reads CSV and RDS objects; large tables and images are for point maps.
                if plan.point_map is None and (
                    descriptor.kind == "image" or descriptor.format == "parquet"
                ):
                    raise DataError(
                        f"“{descriptor.name}” is too large for R analysis in this workspace. "
                        "Show it as a point map in Pinpoint.",
                        "INPUT_NOT_SUPPORTED",
                        422,
                    )
            source_dataset_ids = self.data.dataset_ids_for_objects(
                project_id, [item.reference for item in plan.inputs]
            )
        if selected_ids and not source_dataset_ids.issubset(set(selected_ids)):
            raise DataError(
                "The plan uses inputs outside your selected data scope.",
                "INVALID_DATA_SELECTION",
                422,
            )
        selected_objects = {item.reference.object_id for item in plan.inputs}
        for relationship in plan.relationships:
            if (
                relationship.left_object_id not in selected_objects
                or relationship.right_object_id not in selected_objects
            ):
                raise DataError(
                    "An analysis relationship references an unselected object.",
                    "INVALID_RELATIONSHIP",
                    422,
                )
            if relationship.validation == "invalid":
                raise DataError(
                    (
                        "The selected relationship does not match the data. Resolve the "
                        "join before analysis."
                    ),
                    "INVALID_RELATIONSHIP",
                    422,
                )

    def _artifact(
        self,
        run_id: str,
        source: Path,
        destination: Path,
        role: str,
        media_type: str,
        description: str,
    ) -> ArtifactReference:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        artifact_id = f"artifact_{uuid4().hex}"
        self.repository.create_artifact(
            artifact_id=artifact_id,
            run_id=run_id,
            media_type=media_type,
            filename=destination.name,
            storage_path=destination,
        )
        return ArtifactReference.model_validate(
            {
                "artifact_id": artifact_id,
                "role": role,
                "media_type": media_type,
                "href": f"/api/v1/artifacts/{artifact_id}",
                "description": description,
            }
        )

    async def execute(
        self,
        project_id: str,
        run_id: str,
        plan: ResearchPlan,
        parameters: dict[str, Any] | None = None,
    ) -> ResearchExecution:
        if plan.point_map is not None:
            self.validate_plan(project_id, plan)
            drawn = await self.points.execute(project_id, run_id, plan, parameters)
            return ResearchExecution(result=drawn.result, preview=drawn.preview, spec=drawn.spec)
        if plan.render_code is not None:
            assert plan.figure_size is not None
            controls, groups = figure_controls(plan.controls, plan.control_groups, plan.figure_size)
            plan = ResearchPlan.model_validate(
                {
                    **plan.model_dump(),
                    "controls": [control.model_dump() for control in controls],
                    "control_groups": [group.model_dump() for group in groups],
                }
            )
        self.validate_plan(project_id, plan)
        result = (
            self.data.store.get_result(project_id, plan.reuse_result_id)
            if plan.reuse_result_id
            else None
        )
        if result is None:
            materialized = {}
            alias_by_object = {}
            for item in plan.inputs:
                _, path, format_name = await self.data.materialize(project_id, item.reference)
                materialized[item.alias] = (path, format_name)
                alias_by_object[item.reference.object_id] = item.alias
            relationships = [
                {
                    **relationship.model_dump(mode="json"),
                    "left_alias": alias_by_object[relationship.left_object_id],
                    "right_alias": alias_by_object[relationship.right_object_id],
                }
                for relationship in plan.relationships
                if relationship.kind in {"join", "annotates"}
            ]
            output, analysis_code = await self.execution.execute(
                run_id,
                {
                    "mode": "analyze",
                    "code": plan.analysis_code,
                    "params": plan.analysis_parameters,
                    "random_seed": plan.random_seed,
                    "output_names": [item.key for item in plan.outputs],
                    "relationships": relationships,
                },
                materialized,
                {
                    "plan": plan.model_dump(mode="json"),
                    "objects": {
                        item.alias: self.data.inspect(project_id, item.reference).model_dump(
                            mode="json", exclude={"artifact"}
                        )
                        for item in plan.inputs
                    },
                },
            )
            plan = plan.model_copy(update={"analysis_code": analysis_code})
            result_id = f"result_{uuid4().hex}"
            directory = self.artifact_root / run_id / result_id
            directory.mkdir(parents=True)
            objects, artifacts, bindings = [], [], {}
            definitions = {item.key: item for item in plan.outputs}
            actual_objects = output.response.get("objects", [])
            if not isinstance(actual_objects, list) or {
                item.get("selector") for item in actual_objects
            } != set(definitions):
                raise RExecutionError("The analysis outputs do not match their declared names.")
            for index, item in enumerate(actual_objects):
                definition = definitions[item["selector"]]
                source = output_file(output, item["filename"])
                # Inspect saved objects independently of the generated analysis code.
                inspection = await self.worker.execute(
                    {"mode": "profile", "expand_collection": False}, {"object": (source, "rds")}
                )
                measured = inspection.response["objects"][0]
                destination = directory / f"output-{index}.rds"
                artifact = self._artifact(
                    run_id,
                    source,
                    destination,
                    "model" if measured["kind"] == "model" else "data",
                    "application/x-r-rds",
                    definition.description,
                )
                artifacts.append(artifact)
                if measured.get("csv_filename"):
                    artifacts.append(
                        self._artifact(
                            run_id,
                            output_file(inspection, measured["csv_filename"]),
                            directory / f"output-{index}.csv",
                            "data",
                            "text/csv",
                            definition.description,
                        )
                    )
                descriptor = ObjectDescription.model_validate(
                    {
                        "object_id": f"object_{uuid4().hex}",
                        "revision_id": result_id,
                        "owner_id": result_id,
                        "owner_kind": "analysis_result",
                        "name": definition.name,
                        "description": definition.description,
                        "description_origin": "inferred",
                        "format": "rds",
                        "kind": measured["kind"],
                        "dimensions": measured["dimensions"] or [],
                        "scalar": measured.get("scalar"),
                        "columns": measured["columns"],
                        "capabilities": ["inspect", "materialize"],
                        "content_hash": content_hash(destination),
                        "artifact": artifact.model_dump(mode="json"),
                        "extensions": {
                            "output_key": definition.key,
                            "r_class": measured.get("native_class", []),
                        },
                    }
                )
                objects.append(descriptor)
                bindings[descriptor.object_id] = {
                    "path": str(destination),
                    "format": "rds",
                    "hash": descriptor.content_hash,
                    "key": definition.key,
                }
                shutil.rmtree(inspection.directory.parent, ignore_errors=True)
            script = output.directory / "analysis.R"
            script.write_text(plan.analysis_code or "", encoding="utf-8")
            artifacts.append(
                self._artifact(
                    run_id,
                    script,
                    directory / "analysis.R",
                    "script",
                    "text/plain",
                    "Code used for this analysis.",
                )
            )
            checked_relationships = [
                item.model_copy(update={"validation": "verified"})
                if item.kind in {"join", "annotates"}
                else item
                for item in plan.relationships
            ]
            demo_inputs = any(
                bool(
                    getattr(
                        self.data.store.object_owner(project_id, item.reference.revision_id),
                        "contains_demo_data",
                        False,
                    )
                )
                for item in plan.inputs
            )
            result = AnalysisResult(
                contains_demo_data=demo_inputs,
                result_id=result_id,
                project_id=project_id,
                run_id=run_id,
                name=plan.title,
                description=plan.description,
                created_at=utc_now(),
                inputs=[item.reference for item in plan.inputs],
                objects=objects,
                artifacts=artifacts,
                code_hash=hashlib.sha256((plan.analysis_code or "").encode()).hexdigest(),
                parameters=plan.analysis_parameters,
                environment=output.response.get("environment", {}),
                random_seed=plan.random_seed,
                relationships_used=checked_relationships,
            )
            self.data.store.save_result(result, bindings)
            shutil.rmtree(output.directory.parent, ignore_errors=True)
        record = self.repository.get_run(run_id)
        assert record is not None
        self.repository.update_interaction(
            run_id, {**record["interaction"], "analysis_result_ids": [result.result_id]}
        )
        render_parameters = {item.id: item.value for item in plan.controls}
        if parameters is not None:
            render_parameters.update(parameters)
        size = (
            resolve_figure_size(render_parameters, plan.figure_size)
            if plan.render_code is not None and plan.figure_size is not None
            else None
        )
        plan = plan.model_copy(update={"figure_size": size})
        spec = {
            "figure_size": size.model_dump(mode="json") if size is not None else None,
            "renderer": "r-v1",
            "result_id": result.result_id,
            "plan": plan.model_dump(mode="json"),
            "parameters": render_parameters,
        }
        if plan.render_code is None:
            return ResearchExecution(result=result, preview=None, spec=spec)
        assert size is not None
        inputs = {}
        for result_object in result.objects:
            _, path, format_name = await self.data.materialize(project_id, result_object.reference)
            inputs[str(result_object.extensions["output_key"])] = (path, format_name)
        rendered, render_code = await self.execution.execute(
            run_id,
            {
                "mode": "render",
                "figure_size": size.model_dump(mode="json"),
                "contains_demo_data": result.contains_demo_data,
                "code": plan.render_code,
                "params": render_parameters,
                "random_seed": plan.random_seed,
            },
            inputs,
            {
                "plan": plan.model_dump(mode="json"),
                "objects": {
                    str(item.extensions["output_key"]): item.model_dump(
                        mode="json", exclude={"artifact"}
                    )
                    for item in result.objects
                },
            },
        )
        plan = plan.model_copy(update={"render_code": render_code})
        spec["plan"] = plan.model_dump(mode="json")
        preview = output_file(rendered, "preview.svg")
        validate_svg(preview, size)
        destination = self.artifact_root / run_id / "preview.svg"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(preview, destination)
        # Where the plotting regions are, so marks on the image can be read in data units.
        with suppress(RExecutionError):
            shutil.copyfile(output_file(rendered, PLOT_MAP), destination.with_name(PLOT_MAP))
        shutil.rmtree(rendered.directory.parent, ignore_errors=True)
        return ResearchExecution(result=result, preview=destination, spec=spec)
