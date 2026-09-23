from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from .artifacts import ArtifactReference
from .common import StrictModel


class ObjectReference(StrictModel):
    object_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)


class NumericProfile(StrictModel):
    minimum: float
    maximum: float
    mean: float


class ColumnDescription(StrictModel):
    name: str
    data_type: Literal["number", "boolean", "string", "unknown"]
    missing_count: int = Field(default=0, ge=0)
    unique_count: int | None = Field(default=None, ge=0)
    numeric: NumericProfile | None = None
    description: str | None = None
    unit: str | None = None
    meaning_origin: Literal["source", "inferred", "user"] | None = None


class ObjectDescription(StrictModel):
    object_id: str
    revision_id: str
    owner_id: str
    owner_kind: Literal["dataset", "analysis_result"] = "dataset"
    name: str
    description: str = ""
    kind: Literal["table", "matrix", "model", "scalar", "image", "unknown"] = "table"
    format: str = Field(pattern=r"^[A-Za-z0-9_+-]{1,32}$")
    dimensions: list[int] = Field(default_factory=list)
    scalar: float | bool | None = None
    columns: list[ColumnDescription] = Field(default_factory=list)
    observation_unit: str | None = None
    description_origin: Literal["source", "parser", "inferred", "user"] = "parser"
    readiness: Literal["ready", "unsupported", "unavailable", "failed"] = "ready"
    limitations: list[str] = Field(default_factory=list)
    capabilities: list[Literal["inspect", "materialize"]] = Field(default_factory=list)
    content_hash: str | None = None
    extensions: dict[str, JsonValue] = Field(default_factory=dict)
    artifact: ArtifactReference | None = None

    @property
    def reference(self) -> ObjectReference:
        return ObjectReference(object_id=self.object_id, revision_id=self.revision_id)


class ObjectRelationship(StrictModel):
    relationship_id: str
    left_object_id: str
    right_object_id: str
    kind: Literal["join", "annotates", "derived_from", "related"] = "related"
    left_key: str | None = Field(
        default=None,
        description=(
            "A table column containing the left join keys; mutually exclusive with left_axis."
        ),
    )
    right_key: str | None = Field(
        default=None,
        description=(
            "A table column containing the right join keys; mutually exclusive with right_axis."
        ),
    )
    left_axis: Literal["rows", "columns"] | None = Field(
        default=None,
        description="Matrix axis identifiers only. Leave null when using a table column key.",
    )
    right_axis: Literal["rows", "columns"] | None = Field(
        default=None,
        description="Matrix axis identifiers only. Leave null when using a table column key.",
    )
    cardinality: Literal["one_to_one", "many_to_one", "one_to_many", "many_to_many", "unknown"] = (
        "unknown"
    )
    description: str = ""
    origin: Literal["source", "inferred", "user"] = "source"
    validation: Literal["declared", "verified", "invalid"] = "declared"
    matched_rows: int | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_selectors(self) -> ObjectRelationship:
        if self.kind in {"join", "annotates"}:
            for key, axis in ((self.left_key, self.left_axis), (self.right_key, self.right_axis)):
                if (key is None) == (axis is None):
                    raise ValueError(
                        "Each join side needs either a table-column key or a matrix axis,"
                        " never both."
                    )
        return self


class Dataset(StrictModel):
    contains_demo_data: bool = False
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: str
    project_id: str
    name: str
    description: str = ""
    source_kind: Literal["upload", "analysis_platform"]
    source_id: str
    source_revision: str | None = None
    revision_id: str | None = None
    state: Literal["uploading", "processing", "ready", "failed"] = "uploading"
    objects: list[ObjectDescription] = Field(default_factory=list)
    relationships: list[ObjectRelationship] = Field(default_factory=list)
    interpretation_status: Literal["pending", "source_provided", "interpreted", "unavailable"] = (
        "pending"
    )
    notices: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class DatasetList(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    datasets: list[Dataset]
    total: int
    offset: int = 0
    complete: bool


class CreateDatasetRequest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    source_kind: Literal["upload", "analysis_platform"] = "upload"
    source_id: str | None = Field(default=None, min_length=1, max_length=250)

    @model_validator(mode="after")
    def require_source(self) -> CreateDatasetRequest:
        if self.source_kind == "analysis_platform" and self.source_id is None:
            raise ValueError("A platform dataset requires a source identifier.")
        return self


class UploadReceipt(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    file_id: str
    name: str
    size: int


class ColumnMeaningPatch(StrictModel):
    name: str
    description: str | None = Field(default=None, max_length=2000)
    unit: str | None = Field(default=None, max_length=80)


class ObjectMeaningPatch(StrictModel):
    object_id: str
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    observation_unit: str | None = Field(default=None, max_length=200)
    columns: list[ColumnMeaningPatch] = Field(default_factory=list, max_length=2000)


class DatasetMetadataPatch(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    project_id: str
    base_revision_id: str
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    relationships: list[ObjectRelationship] | None = None
    objects: list[ObjectMeaningPatch] = Field(default_factory=list, max_length=100)


class PlatformDatasetSummary(StrictModel):
    contains_demo_data: bool = False
    source_id: str
    revision: str
    name: str
    description: str = ""
    object_count: int = 0


class PlatformDatasetList(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    connected: bool
    datasets: list[PlatformDatasetSummary] = Field(default_factory=list)
    next_cursor: str | None = None
    complete: bool = True
    message: str | None = None


class AnalysisResult(StrictModel):
    contains_demo_data: bool = False
    result_id: str
    project_id: str
    run_id: str
    name: str
    description: str
    created_at: datetime
    inputs: list[ObjectReference]
    objects: list[ObjectDescription]
    artifacts: list[ArtifactReference] = Field(default_factory=list)
    code_hash: str
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    environment: dict[str, str] = Field(default_factory=dict)
    random_seed: int
    relationships_used: list[ObjectRelationship] = Field(default_factory=list)


class AnalysisResultList(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    results: list[AnalysisResult]
    total: int
    offset: int = 0
    complete: bool
