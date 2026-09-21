"""Figure compositions: validated references, resolved geometry, and page export."""

from __future__ import annotations

from dataclasses import dataclass

from vis_platform_backend.contracts.figure_composition_content import (
    FigureCompositionContent,
    ImagePanelContent,
    PlotPanelContent,
)
from vis_platform_backend.contracts.figure_composition_operations import FigureOperationsRequest
from vis_platform_backend.contracts.figure_compositions import (
    CreateFigureComposition,
    FigureCompositionDocument,
    FigureCompositionHistory,
    FigureCompositionList,
    FigureRenderJob,
    PanelFrame,
    ResolvedPanel,
    SaveFigureComposition,
)
from vis_platform_backend.contracts.figures import FigureExportFormat
from vis_platform_backend.contracts.plot_runs import PlotResultSummary
from vis_platform_backend.contracts.reference_images import ReferenceImage
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.domain.figure_checks import figure_checks
from vis_platform_backend.domain.figure_compositions import (
    MM_PER_INCH,
    check_bounds,
    image_natural_size,
    page_height,
    panel_frames,
    panel_labels,
    plot_natural_size,
)
from vis_platform_backend.infrastructure.database import Repository
from vis_platform_backend.infrastructure.figure_compositions import FigureCompositionRepository
from vis_platform_backend.services.figure_compositor import PanelSource, compose_page
from vis_platform_backend.services.figure_exports import (
    MEDIA_TYPES,
    FigureDownload,
    FigureExporter,
    download_name,
)
from vis_platform_backend.services.figure_svg import smallest_text_pt
from vis_platform_backend.services.reference_images import ReferenceImageService


@dataclass(frozen=True)
class ResolvedComposition:
    figures: dict[str, PlotResultSummary]
    images: dict[str, ReferenceImage]
    natural_sizes: dict[str, tuple[float, float]]
    frames: dict[str, PanelFrame]
    labels: dict[str, str | None]
    page_height_mm: float


class FigureCompositionService:
    def __init__(
        self,
        store: FigureCompositionRepository,
        repository: Repository,
        images: ReferenceImageService,
        exporter: FigureExporter,
    ) -> None:
        self.store, self.repository, self.images, self.exporter = (
            store,
            repository,
            images,
            exporter,
        )
        # Immutable versions have fixed text sizes, so measurements are kept per version.
        self._text_sizes: dict[str, tuple[float, bool]] = {}

    def check_project(self, project_id: str) -> None:
        if not self.repository.project_exists(project_id):
            raise DataError("The project was not found.", "NOT_FOUND", 404)

    def figure(self, project_id: str, version_id: str) -> PlotResultSummary:
        record = self.repository.result_for_version(version_id, project_id)
        if record is None:
            raise DataError("The figure version was not found in this project.", "NOT_FOUND", 404)
        return PlotResultSummary.model_validate(record)

    def _natural_plot_size(self, figure: PlotResultSummary) -> tuple[float, float]:
        size = figure.figure_size or self.exporter.plot_svg(figure)[1]
        return plot_natural_size(size.width, size.height)

    def smallest_text(self, figure: PlotResultSummary) -> tuple[float, bool]:
        if figure.version_id not in self._text_sizes:
            root, size = self.exporter.plot_svg(figure)
            self._text_sizes[figure.version_id] = smallest_text_pt(root, size.width)
        return self._text_sizes[figure.version_id]

    def resolve(self, project_id: str, content: FigureCompositionContent) -> ResolvedComposition:
        """Check every reference against the project and derive the geometry the page uses."""
        self.check_project(project_id)
        figures: dict[str, PlotResultSummary] = {}
        images: dict[str, ReferenceImage] = {}
        natural_sizes: dict[str, tuple[float, float]] = {}
        for panel in content.panels:
            if isinstance(panel.content, PlotPanelContent):
                version_id = panel.content.version_id
                if version_id not in figures:
                    figures[version_id] = self.figure(project_id, version_id)
                natural_sizes[panel.id] = self._natural_plot_size(figures[version_id])
            else:
                image_id = panel.content.image_id
                if image_id not in images:
                    images[image_id] = self.images.get(project_id, image_id)
                image = images[image_id]
                natural_sizes[panel.id] = image_natural_size(image.width, image.height)
        frames = panel_frames(content, natural_sizes)
        check_bounds(content, frames)
        return ResolvedComposition(
            figures=figures,
            images=images,
            natural_sizes=natural_sizes,
            frames=frames,
            labels=panel_labels(content, frames),
            page_height_mm=page_height(content, frames),
        )

    def validate(self, project_id: str, content: FigureCompositionContent) -> None:
        self.resolve(project_id, content)

    def get(self, project_id: str, composition_id: str) -> FigureCompositionDocument:
        record = self.store.get(project_id, composition_id)
        content: FigureCompositionContent = record["content"]
        resolved = self.resolve(project_id, content)
        figures = dict(resolved.figures)
        plot_panels = [
            (panel.id, panel.content)
            for panel in content.panels
            if isinstance(panel.content, PlotPanelContent)
        ]
        latest = self.store.latest_versions(
            project_id, {figures[plot.version_id].plot_id for _, plot in plot_panels}
        )
        updates: dict[str, str] = {}
        for panel_id, plot in plot_panels:
            newest = latest.get(figures[plot.version_id].plot_id)
            known = (plot.version_id, plot.source_version_id, plot.ignored_version_id)
            if newest and newest not in known:
                updates[panel_id] = newest
                if newest not in figures:
                    figures[newest] = self.figure(project_id, newest)
        checks = figure_checks(
            content,
            resolved.frames,
            resolved.labels,
            resolved.page_height_mm,
            {
                panel_id: self.smallest_text(resolved.figures[plot.version_id])
                for panel_id, plot in plot_panels
            },
        )
        jobs = [
            FigureRenderJob(
                job_id=job["job_id"],
                panel_id=job["state"]["panel_id"],
                status=job["status"],
                width_mm=job["state"]["width_mm"],
                height_mm=job["state"]["height_mm"],
                error=job["state"].get("error"),
                created_at=job["created_at"],
            )
            for job in self.store.jobs(composition_id)
        ]
        return FigureCompositionDocument(
            composition_id=composition_id,
            project_id=project_id,
            title=content.title,
            revision=record["revision"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
            content=content,
            page_height_mm=resolved.page_height_mm,
            panels={
                panel.id: ResolvedPanel(
                    label=resolved.labels[panel.id],
                    frame=resolved.frames[panel.id],
                    natural_width_mm=round(resolved.natural_sizes[panel.id][0], 3),
                    natural_height_mm=round(resolved.natural_sizes[panel.id][1], 3),
                )
                for panel in content.panels
            },
            figures=figures,
            images=resolved.images,
            updates=updates,
            checks=checks,
            jobs=jobs,
        )

    def list_compositions(self, project_id: str, offset: int) -> FigureCompositionList:
        self.check_project(project_id)
        items, total = self.store.list_compositions(project_id, offset)
        return FigureCompositionList.model_validate(
            {"compositions": items, "total": total, "offset": offset}
        )

    def create(
        self, project_id: str, request: CreateFigureComposition
    ) -> FigureCompositionDocument:
        self.validate(project_id, request.content)
        composition_id = self.store.create(project_id, request.content, request.request_id)
        return self.get(project_id, composition_id)

    def save(
        self, project_id: str, composition_id: str, request: SaveFigureComposition
    ) -> FigureCompositionDocument:
        self.store.save(
            project_id,
            composition_id,
            request.base_revision,
            request.content,
            request.summary,
            lambda content: self.validate(project_id, content),
        )
        return self.get(project_id, composition_id)

    def operations(
        self, project_id: str, composition_id: str, request: FigureOperationsRequest
    ) -> FigureCompositionDocument:
        self.store.get(project_id, composition_id)
        self.store.apply_operations(
            project_id,
            composition_id,
            request,
            lambda content: self.validate(project_id, content),
        )
        return self.get(project_id, composition_id)

    def history(
        self, project_id: str, composition_id: str, offset: int
    ) -> FigureCompositionHistory:
        self.store.get(project_id, composition_id)
        revisions, total = self.store.history(composition_id, offset)
        return FigureCompositionHistory.model_validate({"revisions": revisions, "total": total})

    def revision(
        self, project_id: str, composition_id: str, revision: int
    ) -> FigureCompositionContent:
        self.store.get(project_id, composition_id)
        return self.store.revision(composition_id, revision)

    def content(self, project_id: str, composition_id: str) -> FigureCompositionContent:
        content: FigureCompositionContent = self.store.get(project_id, composition_id)["content"]
        return content

    def export(
        self, project_id: str, composition_id: str, format: FigureExportFormat
    ) -> FigureDownload:
        record = self.store.get(project_id, composition_id)
        content: FigureCompositionContent = record["content"]
        resolved = self.resolve(project_id, content)
        sources: dict[str, PanelSource] = {}
        for panel in content.panels:
            if isinstance(panel.content, ImagePanelContent):
                path = self.images.content_path(project_id, panel.content.image_id)
                sources[panel.id] = path.read_bytes()
            else:
                figure = resolved.figures[panel.content.version_id]
                sources[panel.id] = self.exporter.plot_svg(figure)[0]
        data = compose_page(
            content, resolved.page_height_mm, resolved.frames, resolved.labels, sources
        )
        destination = self.exporter.convert(
            data,
            content.page.width_mm / MM_PER_INCH,
            resolved.page_height_mm / MM_PER_INCH,
            format,
        )
        return FigureDownload(
            path=destination,
            media_type=MEDIA_TYPES[format],
            filename=download_name(content.title, f"r{record['revision']}", format),
        )
