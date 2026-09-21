from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

from vis_platform_backend.contracts.datasets import AnalysisResult, Dataset


class DatasetRepository:
    """Persistent immutable manifests alongside the application's existing run database."""

    def __init__(self, database_path: Path) -> None:
        self.connection = sqlite3.connect(database_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = RLock()
        with self.connection:
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS datasets (
                    dataset_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    source_kind TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(project_id, source_kind, source_id)
                );
                CREATE TABLE IF NOT EXISTS dataset_revisions (
                    revision_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
                    payload TEXT NOT NULL,
                    bindings TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dataset_files (
                    file_id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    UNIQUE(dataset_id, name)
                );
                CREATE TABLE IF NOT EXISTS analysis_results (
                    result_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    run_id TEXT NOT NULL REFERENCES plot_runs(run_id),
                    payload TEXT NOT NULL,
                    bindings TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS dataset_project ON datasets(project_id);
                CREATE INDEX IF NOT EXISTS result_project ON analysis_results(project_id);
            """)

    def close(self) -> None:
        self.connection.close()

    def save_dataset(self, dataset: Dataset) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO datasets VALUES (?, ?, ?, ?, ?) ON CONFLICT(dataset_id) "
                "DO UPDATE SET payload=excluded.payload",
                (
                    dataset.dataset_id,
                    dataset.project_id,
                    dataset.source_kind,
                    dataset.source_id,
                    dataset.model_dump_json(),
                ),
            )

    def find_source(self, project_id: str, kind: str, source_id: str) -> Dataset | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT payload FROM datasets WHERE project_id=? AND source_kind=? AND source_id=?",
                (project_id, kind, source_id),
            ).fetchone()
        return Dataset.model_validate_json(row[0]) if row else None

    def get_dataset(
        self, project_id: str, dataset_id: str, revision_id: str | None = None
    ) -> Dataset | None:
        with self.lock:
            if revision_id:
                row = self.connection.execute(
                    "SELECT r.payload FROM dataset_revisions r JOIN datasets d USING(dataset_id) "
                    "WHERE d.project_id=? AND d.dataset_id=? AND r.revision_id=?",
                    (project_id, dataset_id, revision_id),
                ).fetchone()
            else:
                row = self.connection.execute(
                    "SELECT payload FROM datasets WHERE project_id=? AND dataset_id=?",
                    (project_id, dataset_id),
                ).fetchone()
        return Dataset.model_validate_json(row[0]) if row else None

    def list_datasets(
        self, project_id: str, offset: int = 0, limit: int = 30
    ) -> tuple[list[Dataset], int]:
        with self.lock:
            total = self.connection.execute(
                "SELECT count(*) FROM datasets WHERE project_id=?",
                (project_id,),
            ).fetchone()[0]
            rows = self.connection.execute(
                (
                    "SELECT payload FROM datasets WHERE project_id=? ORDER BY rowid "
                    "DESC LIMIT ? OFFSET ?"
                ),
                (project_id, limit, offset),
            ).fetchall()
        return [Dataset.model_validate_json(row[0]) for row in rows], total

    def save_revision(self, dataset: Dataset, bindings: dict[str, Any]) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO dataset_revisions VALUES (?, ?, ?, ?)",
                (
                    dataset.revision_id,
                    dataset.dataset_id,
                    dataset.model_dump_json(),
                    json.dumps(bindings),
                ),
            )
            self.connection.execute(
                "UPDATE datasets SET payload=? WHERE dataset_id=?",
                (dataset.model_dump_json(), dataset.dataset_id),
            )

    def add_file(self, dataset_id: str, file_id: str, name: str, path: Path, size: int) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO dataset_files VALUES (?, ?, ?, ?, ?)",
                (file_id, dataset_id, name, str(path), size),
            )

    def files(self, dataset_id: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM dataset_files WHERE dataset_id=? ORDER BY rowid", (dataset_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def bindings(self, project_id: str, revision_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT r.bindings FROM dataset_revisions r JOIN datasets d USING(dataset_id) "
                "WHERE d.project_id=? AND r.revision_id=?",
                (project_id, revision_id),
            ).fetchone()
            if row is None:
                row = self.connection.execute(
                    "SELECT bindings FROM analysis_results WHERE project_id=? AND result_id=?",
                    (project_id, revision_id),
                ).fetchone()
        return json.loads(row[0]) if row else None

    def cache_object(
        self, project_id: str, revision_id: str, object_id: str, materialized: dict[str, Any]
    ) -> None:
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            row = self.connection.execute(
                (
                    "SELECT r.bindings FROM dataset_revisions r JOIN datasets d "
                    "USING(dataset_id) WHERE d.project_id=? AND r.revision_id=?"
                ),
                (project_id, revision_id),
            ).fetchone()
            if row is None:
                raise ValueError("The dataset revision is unavailable.")
            bindings = json.loads(row[0])
            if not bindings[object_id].get("path"):
                bindings[object_id].update(materialized)
                self.connection.execute(
                    "UPDATE dataset_revisions SET bindings=? WHERE revision_id=?",
                    (json.dumps(bindings), revision_id),
                )

    def object_owner(self, project_id: str, revision_id: str) -> Dataset | AnalysisResult | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT r.payload FROM dataset_revisions r JOIN datasets d USING(dataset_id) "
                "WHERE d.project_id=? AND r.revision_id=?",
                (project_id, revision_id),
            ).fetchone()
        return (
            Dataset.model_validate_json(row[0]) if row else self.get_result(project_id, revision_id)
        )

    def save_result(self, result: AnalysisResult, bindings: dict[str, Any]) -> None:
        with self.lock, self.connection:
            self.connection.execute(
                "INSERT INTO analysis_results VALUES (?, ?, ?, ?, ?)",
                (
                    result.result_id,
                    result.project_id,
                    result.run_id,
                    result.model_dump_json(),
                    json.dumps(bindings),
                ),
            )

    def get_result(self, project_id: str, result_id: str) -> AnalysisResult | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT payload FROM analysis_results WHERE project_id=? AND result_id=?",
                (project_id, result_id),
            ).fetchone()
        return AnalysisResult.model_validate_json(row[0]) if row else None

    def list_results(
        self, project_id: str, offset: int = 0, limit: int = 30
    ) -> tuple[list[AnalysisResult], int]:
        with self.lock:
            total = self.connection.execute(
                "SELECT count(*) FROM analysis_results WHERE project_id=?", (project_id,)
            ).fetchone()[0]
            rows = self.connection.execute(
                (
                    "SELECT payload FROM analysis_results WHERE project_id=? ORDER BY"
                    " rowid DESC LIMIT ? OFFSET ?"
                ),
                (project_id, limit, offset),
            ).fetchall()
        return [AnalysisResult.model_validate_json(row[0]) for row in rows], total

    def recover(self) -> None:
        with self.lock, self.connection:
            rows = self.connection.execute("SELECT payload FROM datasets").fetchall()
            for row in rows:
                dataset = Dataset.model_validate_json(row[0])
                if dataset.state == "processing":
                    dataset.state = "failed"
                    dataset.notices = ["Data inspection was interrupted. Retry to continue."]
                    self.connection.execute(
                        "UPDATE datasets SET payload=? WHERE dataset_id=?",
                        (dataset.model_dump_json(), dataset.dataset_id),
                    )
