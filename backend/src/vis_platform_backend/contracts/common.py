from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION: Final[Literal["1.0"]] = "1.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiError(StrictModel):
    code: str
    message: str
    recoverable: bool = False
    details: dict[str, Any] | None = None


class ApiErrorEnvelope(StrictModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    error: ApiError
