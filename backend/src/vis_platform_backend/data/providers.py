from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, urljoin, urlsplit

import httpx
from pydantic import Field

from vis_platform_backend.contracts.common import StrictModel
from vis_platform_backend.contracts.datasets import (
    ObjectDescription,
    ObjectRelationship,
    PlatformDatasetList,
    PlatformDatasetSummary,
)


class SourceObjectDescription(ObjectDescription):
    object_id: str = ""
    revision_id: str = ""
    owner_id: str = ""


class SourceObject(StrictModel):
    source_object_id: str
    description: SourceObjectDescription
    content_path: str
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    object_path: list[str | int] = Field(default_factory=list, max_length=32)


class SourceManifest(StrictModel):
    contains_demo_data: bool = False
    source_id: str
    revision: str
    name: str
    description: str = ""
    objects: list[SourceObject] = Field(min_length=1, max_length=100)
    relationships: list[ObjectRelationship] = Field(default_factory=list)


class SourceProvider(Protocol):
    async def discover(self, cursor: str | None = None) -> PlatformDatasetList: ...
    async def describe(self, source_id: str) -> SourceManifest: ...
    async def materialize(self, item: SourceObject, destination: Path) -> None: ...


class PlatformConnectionError(RuntimeError):
    pass


class AnalysisPlatformProvider:
    """Adapter for the documented Vis source contract; never accepts arbitrary client URLs."""

    def __init__(self, base_url: str | None, token: str | None, byte_limit: int) -> None:
        self.base_url = base_url.rstrip("/") + "/" if base_url else None
        self.token, self.byte_limit = token, byte_limit

    def _url(self, path: str) -> str:
        if not self.base_url:
            raise PlatformConnectionError("The analysis platform is not connected.")
        url = urljoin(self.base_url, path)
        base, resolved = urlsplit(self.base_url), urlsplit(url)
        if (
            base.scheme not in {"http", "https"}
            or (base.scheme, base.netloc) != (resolved.scheme, resolved.netloc)
            or not resolved.path.startswith(base.path)
            or resolved.username
            or resolved.password
        ):
            raise PlatformConnectionError("The platform returned an invalid object location.")
        return url

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=30,
            follow_redirects=False,
            headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
        )

    async def discover(self, cursor: str | None = None) -> PlatformDatasetList:
        if self.base_url is None:
            return PlatformDatasetList(
                connected=False, message="The analysis platform is not connected."
            )
        try:
            async with self._client() as client:
                response = await client.get(
                    self._url("datasets"), params={"cursor": cursor} if cursor else {}
                )
                response.raise_for_status()
                payload = response.json()
            return PlatformDatasetList(
                connected=True,
                datasets=[
                    PlatformDatasetSummary.model_validate(item) for item in payload["datasets"]
                ],
                next_cursor=payload.get("next_cursor"),
                complete=not payload.get("next_cursor"),
            )
        except (httpx.HTTPError, ValueError, KeyError) as error:
            raise PlatformConnectionError(
                "The platform dataset list could not be loaded."
            ) from error

    async def describe(self, source_id: str) -> SourceManifest:
        try:
            async with self._client() as client:
                response = await client.get(self._url("datasets/" + quote(source_id, safe="")))
                response.raise_for_status()
                manifest = SourceManifest.model_validate(response.json())
            if manifest.source_id != source_id:
                raise PlatformConnectionError("The platform returned a different dataset.")
            return manifest
        except (httpx.HTTPError, ValueError) as error:
            raise PlatformConnectionError(
                "The platform dataset description could not be loaded."
            ) from error

    async def materialize(self, item: SourceObject, destination: Path) -> None:
        try:
            async with (
                self._client() as client,
                client.stream("GET", self._url(item.content_path)) as response,
            ):
                response.raise_for_status()
                total = 0
                with destination.open("wb") as stream:
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > self.byte_limit:
                            raise PlatformConnectionError(
                                "The selected object exceeds the current import size limit."
                            )
                        stream.write(chunk)
        except httpx.HTTPError as error:
            raise PlatformConnectionError(
                "The selected platform object could not be retrieved."
            ) from error


class UploadedFilesProvider:
    """An upload session exposes source objects through the same ingestion interface."""

    def __init__(
        self, source_id: str, name: str, description: str, files: list[dict[str, object]]
    ) -> None:
        self.source_id, self.name, self.description = source_id, name, description
        self.files = {str(item["file_id"]): item for item in files}

    async def discover(self, cursor: str | None = None) -> PlatformDatasetList:
        return PlatformDatasetList(
            connected=True,
            datasets=[
                PlatformDatasetSummary(
                    source_id=self.source_id,
                    revision="upload",
                    name=self.name,
                    description=self.description,
                    object_count=len(self.files),
                )
            ],
        )

    async def describe(self, source_id: str) -> SourceManifest:
        if source_id != self.source_id:
            raise PlatformConnectionError("The upload session was not found.")
        return SourceManifest(
            source_id=source_id,
            revision="upload",
            name=self.name,
            description=self.description,
            objects=[
                SourceObject(
                    source_object_id=file_id,
                    description=SourceObjectDescription(
                        name=str(item["name"]),
                        kind="unknown",
                        format=(
                            Path(str(item["name"])).suffix.lstrip(".").lower()
                            if re.fullmatch(
                                r"[A-Za-z0-9_+-]{1,32}", Path(str(item["name"])).suffix.lstrip(".")
                            )
                            else "unknown"
                        ),
                    ),
                    content_path=file_id,
                )
                for file_id, item in self.files.items()
            ],
        )

    async def materialize(self, item: SourceObject, destination: Path) -> None:
        import shutil

        source = self.files.get(item.source_object_id)
        if source is None or item.content_path != item.source_object_id:
            raise PlatformConnectionError("The uploaded source object was not found.")
        shutil.copyfile(str(source["path"]), destination)
