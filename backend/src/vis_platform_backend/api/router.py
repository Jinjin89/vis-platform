from fastapi import APIRouter

from vis_platform_backend.api.routes.datasets import router as datasets_router

from .routes import (
    artifacts,
    assistant_turns,
    figure_compositions,
    figure_exports,
    health,
    plot_runs,
    plot_versions,
    projects,
    reference_images,
    reports,
    shared_figures,
    slides,
    workspace_sessions,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(projects.router)
api_router.include_router(reference_images.router)
api_router.include_router(assistant_turns.router)
api_router.include_router(workspace_sessions.router)
api_router.include_router(plot_runs.router)
api_router.include_router(plot_versions.router)
api_router.include_router(artifacts.router)
api_router.include_router(figure_exports.router)
api_router.include_router(reports.router)


api_router.include_router(datasets_router)

api_router.include_router(slides.router)

api_router.include_router(shared_figures.router)

api_router.include_router(figure_compositions.router)
