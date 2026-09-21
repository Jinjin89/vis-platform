from typing import Literal

from .common import StrictModel


class ArtifactReference(StrictModel):
    artifact_id: str
    role: Literal["preview", "publication", "data", "model", "script", "methods"]
    media_type: str
    href: str
    description: str
