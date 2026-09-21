from pathlib import Path

from vis_platform_backend.contracts.plot_runs import RunStage, RunStatus
from vis_platform_backend.contracts.projects import Project
from vis_platform_backend.infrastructure.database import Repository, utc_now


def _commit_version(
    repository: Repository,
    artifact_root: Path,
    *,
    run_id: str,
    version_id: str,
    plot_id: str,
    project_id: str,
    prompt: str,
    parent_version_id: str | None,
) -> None:
    created_at = utc_now()
    request = {
        "schema_version": "1.0",
        "project_id": project_id,
        "request": {
            "text": prompt,
            "generation_mode": "auto",
            "gallery_mode": "off",
            "controls_mode": "hybrid",
        },
        "data_scope": {"mode": "auto"},
        "base_version_id": parent_version_id,
    }
    repository.create_run(
        run_id=run_id,
        project_id=project_id,
        request=request,
        status=RunStatus.QUEUED,
        stage=RunStage.RECEIVED,
        created_at=created_at,
    )
    artifact_path = artifact_root / f"{run_id}.svg"
    artifact_path.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    repository.commit_completed_run(
        run_id=run_id,
        project_id=project_id,
        plot_id=plot_id,
        version_id=version_id,
        parent_version_id=parent_version_id,
        stage=RunStage.COMMITTING_VERSION,
        result={},
        artifact_id=f"artifact_{run_id}",
        artifact_media_type="image/svg+xml",
        artifact_filename=artifact_path.name,
        artifact_storage_path=artifact_path,
    )


def test_request_history_for_version_returns_full_lineage_root_first(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "repository.sqlite3")
    repository.initialize()
    project = Project(project_id="project_one", name="Study", created_at=utc_now())
    repository.create_project(project)

    try:
        versions = (
            ("run_root", "version_root", "Create a survival curve", None),
            ("run_child", "version_child", "Move the legend below", "version_root"),
            ("run_grandchild", "version_grandchild", "Make labels larger", "version_child"),
        )
        for run_id, version_id, prompt, parent_version_id in versions:
            _commit_version(
                repository,
                tmp_path,
                run_id=run_id,
                version_id=version_id,
                plot_id="plot_one",
                project_id=project.project_id,
                prompt=prompt,
                parent_version_id=parent_version_id,
            )

        history = repository.request_history_for_version("version_grandchild")

        assert [item["request"]["text"] for item in history] == [
            "Create a survival curve",
            "Move the legend below",
            "Make labels larger",
        ]
    finally:
        repository.close()


def test_request_history_for_unknown_version_is_empty(tmp_path: Path) -> None:
    repository = Repository(tmp_path / "repository.sqlite3")
    repository.initialize()

    try:
        assert repository.request_history_for_version("version_missing") == []
    finally:
        repository.close()
