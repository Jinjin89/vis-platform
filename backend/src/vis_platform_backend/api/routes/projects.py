from fastapi import APIRouter, status

from vis_platform_backend.api.dependencies import CoordinatorDependency
from vis_platform_backend.api.errors import NOT_FOUND_RESPONSE, VALIDATION_RESPONSE
from vis_platform_backend.contracts.projects import CreateProjectRequest, Project

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "",
    response_model=Project,
    status_code=status.HTTP_201_CREATED,
    responses=VALIDATION_RESPONSE,
)
def create_project(
    request: CreateProjectRequest,
    coordinator: CoordinatorDependency,
) -> Project:
    return coordinator.create_project(request)


@router.get("/{project_id}", response_model=Project, responses=NOT_FOUND_RESPONSE)
def get_project(project_id: str, coordinator: CoordinatorDependency) -> Project:
    return coordinator.get_project(project_id)
