from pathlib import Path

from vis_platform_backend.contracts.datasets import PlatformDatasetList
from vis_platform_backend.data.demo_transcriptomics import (
    DEMO_SOURCE_IDS,
    DemoTranscriptomicsProvider,
)
from vis_platform_backend.data.providers import (
    AnalysisPlatformProvider,
    PlatformConnectionError,
    SourceManifest,
    SourceObject,
)


class PlatformCatalog:
    """Selectable local demonstrations alongside an independently configured platform."""

    def __init__(
        self, remote: AnalysisPlatformProvider, demonstrations: DemoTranscriptomicsProvider
    ) -> None:
        self.remote, self.demonstrations = remote, demonstrations

    async def discover(self, cursor: str | None = None) -> PlatformDatasetList:
        demos = (
            await self.demonstrations.discover()
            if cursor is None
            else PlatformDatasetList(connected=False)
        )
        try:
            external = await self.remote.discover(cursor)
        except PlatformConnectionError as error:
            return PlatformDatasetList(
                connected=False, datasets=demos.datasets, complete=False, message=str(error)
            )
        if any(item.source_id in DEMO_SOURCE_IDS for item in external.datasets):
            return PlatformDatasetList(
                connected=False,
                datasets=demos.datasets,
                complete=False,
                message="The external catalog contains a reserved demo identifier.",
            )
        return PlatformDatasetList(
            connected=external.connected,
            datasets=[*demos.datasets, *external.datasets],
            next_cursor=external.next_cursor,
            complete=external.complete,
            message=external.message
            if external.connected
            else (
                "Demo collections are ready to use. An external analysis platform is not connected."
            ),
        )

    async def describe(self, source_id: str) -> SourceManifest:
        if source_id in DEMO_SOURCE_IDS:
            return await self.demonstrations.describe(source_id)
        manifest = await self.remote.describe(source_id)
        for item in manifest.objects:
            if item.content_path.startswith("builtin-demo/"):
                raise PlatformConnectionError("The external object uses a reserved demo location.")
            self.remote._url(item.content_path)
        return manifest

    async def materialize(self, item: SourceObject, destination: Path) -> None:
        if item.content_path.startswith("builtin-demo/"):
            await self.demonstrations.materialize(item, destination)
        else:
            await self.remote.materialize(item, destination)
