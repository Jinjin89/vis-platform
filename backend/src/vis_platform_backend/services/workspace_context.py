from typing import Any

from vis_platform_backend.contracts.plot_runs import PlotResultSummary
from vis_platform_backend.data.service import DatasetService
from vis_platform_backend.infrastructure.database import Repository


class WorkspaceContextTools:
    def __init__(self, repository: Repository, data: DatasetService | None = None) -> None:
        self.repository = repository
        self.data = data

    def get_current_data(self, project_id: str) -> dict[str, Any]:
        if self.data is not None:
            catalog = self.data.list_datasets(project_id)
            return {
                "discovery_available": True,
                "datasets": [
                    {
                        "dataset_id": item.dataset_id,
                        "revision_id": item.revision_id,
                        "name": item.name,
                        "description": item.description,
                        "state": item.state,
                        "source": item.source_kind,
                        "contains_demo_data": item.contains_demo_data,
                        "object_count": len(item.objects),
                    }
                    for item in catalog.datasets
                ],
                "objects": [
                    {
                        "object_id": obj.object_id,
                        "revision_id": obj.revision_id,
                        "dataset_id": item.dataset_id,
                        "name": obj.name,
                        "kind": obj.kind,
                        "description": obj.description,
                        "readiness": obj.readiness,
                    }
                    for item in catalog.datasets
                    for obj in item.objects
                ][:60],
                "total": catalog.total,
                "complete": catalog.complete
                and sum(len(item.objects) for item in catalog.datasets) <= 60,
                "summary": f"{catalog.total} datasets are registered. Uploads are connected.",
            }
        objects = {}
        for payload in self.repository.current_project_results(project_id):
            result = PlotResultSummary.model_validate(payload)
            for item in result.data_used:
                objects[item.object_id] = item.model_dump(mode="json")
        return {
            "discovery_available": False,
            "objects": list(objects.values()),
            "summary": "External data discovery and uploads are not connected. "
            + (
                f"{len(objects)} data objects are recorded with saved figures."
                if objects
                else "No research data objects are recorded with recent figures."
            ),
        }

    def get_current_results(self, project_id: str) -> dict[str, Any]:
        results = [
            PlotResultSummary.model_validate(payload)
            for payload in self.repository.current_project_results(project_id)
        ]
        return {
            "figures": [
                {
                    "plot_id": result.plot_id,
                    "version_id": result.version_id,
                    "title": result.title,
                    "description": result.preview.description,
                    "execution_mode": result.execution_mode,
                }
                for result in results
            ],
            "summary": f"{len(results)} recent saved figures are available in this project.",
            "analysis_results": [
                item.model_dump(mode="json") for item in self.data.results(project_id).results
            ]
            if self.data
            else [],
            "analysis_results_available": self.data is not None,
            "external_analysis_results_available": bool(
                self.data and self.data.settings.analysis_platform_url
            ),
        }
