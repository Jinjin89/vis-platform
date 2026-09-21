from __future__ import annotations

from dataclasses import dataclass, field

from vis_platform_backend.contracts.plot_runs import CreatePlotRunRequest


@dataclass(frozen=True, slots=True)
class PlotCapabilities:
    data_modes: tuple[str, ...] = ("demo",)
    generation_modes: tuple[str, ...] = ("auto",)
    gallery_modes: tuple[str, ...] = ("off",)
    regeneration: bool = False
    parameter_updates: bool = True
    description: str = (
        "Fixed illustrative previews for distributions, survival, relationships, and group "
        "comparisons. Returned plot controls support parameter updates. Research-data plotting "
        "and arbitrary plot regeneration are not connected."
    )

    def blockers(self, request: CreatePlotRunRequest) -> tuple[str, ...]:
        reasons = []
        if request.data_scope.mode not in self.data_modes:
            reasons.append("Research-data access and plotting are not connected in this workspace.")
        if request.request.generation_mode.value not in self.generation_modes:
            reasons.append("The requested plotting engine is not connected in this workspace.")
        if request.request.gallery_mode.value not in self.gallery_modes:
            reasons.append("The requested gallery is not connected in this workspace.")
        if request.base_version_id is not None and not self.regeneration:
            reasons.append(
                "Freeform regeneration is not connected; use the saved figure parameters."
            )
        return tuple(reasons)


@dataclass(frozen=True, slots=True)
class WorkspaceCapabilities:
    plotting: PlotCapabilities = field(default_factory=PlotCapabilities)
    data_upload: bool = False
    data_discovery: bool = False
    chat_workspace_actions: bool = False
    plot_context: str = "Saved request, preview description, execution mode, and validation status."
    ui_actions: tuple[str, ...] = (
        "stop an active run",
        "download a completed SVG",
        "adjust supported plot parameters",
        "browse figure history",
        "restore a figure version",
    )
