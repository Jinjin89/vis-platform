from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from vis_platform_backend.contracts.figure_composition_content import (
    FigureCompositionContent,
    ImagePanelContent,
)
from vis_platform_backend.contracts.figure_composition_operations import FigureOperationsRequest
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.domain.figure_compositions import apply_figure_operations
from vis_platform_backend.infrastructure.database import utc_now
from vis_platform_backend.infrastructure.reference_images import pin_reference_images

Validator = Callable[[FigureCompositionContent], None]


class FigureCompositionRepository:
    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = RLock()
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS figure_compositions (
                composition_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(project_id),
                revision INTEGER NOT NULL,
                content_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                request_id TEXT NOT NULL,
                request_json TEXT NOT NULL,
                UNIQUE(project_id, request_id)
            );
            CREATE TABLE IF NOT EXISTS figure_composition_revisions (
                composition_id TEXT NOT NULL REFERENCES figure_compositions(composition_id),
                revision INTEGER NOT NULL,
                content_json TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(composition_id, revision)
            );
            CREATE TABLE IF NOT EXISTS figure_composition_operations (
                composition_id TEXT NOT NULL REFERENCES figure_compositions(composition_id),
                request_id TEXT NOT NULL,
                request_json TEXT NOT NULL,
                result_revision INTEGER NOT NULL,
                PRIMARY KEY(composition_id, request_id)
            );
            CREATE TABLE IF NOT EXISTS figure_composition_jobs (
                job_id TEXT PRIMARY KEY,
                composition_id TEXT NOT NULL REFERENCES figure_compositions(composition_id),
                request_key TEXT NOT NULL,
                status TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(composition_id, request_key)
            );
        """)

    def close(self) -> None:
        self.connection.close()

    def get(self, project_id: str, composition_id: str) -> dict[str, Any]:
        with self.lock:
            row = self.connection.execute(
                "SELECT * FROM figure_compositions WHERE project_id = ? AND composition_id = ?",
                (project_id, composition_id),
            ).fetchone()
        if row is None:
            raise DataError("Figure was not found in this project.", "NOT_FOUND", 404)
        record = dict(row)
        record["content"] = FigureCompositionContent.model_validate_json(record.pop("content_json"))
        return record

    def list_compositions(self, project_id: str, offset: int) -> tuple[list[dict[str, Any]], int]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT composition_id, project_id, revision, updated_at, "
                "json_extract(content_json, '$.title') AS title FROM figure_compositions "
                "WHERE project_id = ? ORDER BY updated_at DESC, composition_id "
                "LIMIT 30 OFFSET ?",
                (project_id, offset),
            ).fetchall()
            total = self.connection.execute(
                "SELECT count(*) FROM figure_compositions WHERE project_id = ?", (project_id,)
            ).fetchone()[0]
        return [dict(row) for row in rows], total

    def latest_versions(self, project_id: str, plot_ids: set[str]) -> dict[str, str]:
        """The newest version is an explicit shared selection, otherwise the plot's current one."""
        if not plot_ids:
            return {}
        marks = ", ".join("?" for _ in plot_ids)
        with self.lock:
            rows = self.connection.execute(
                "SELECT plot.plot_id, COALESCE(shared.version_id, plot.current_version_id) "
                "AS version_id FROM plots AS plot LEFT JOIN shared_figures AS shared "
                "ON shared.project_id = plot.project_id AND shared.plot_id = plot.plot_id "
                f"WHERE plot.project_id = ? AND plot.plot_id IN ({marks})",
                (project_id, *sorted(plot_ids)),
            ).fetchall()
        return {row["plot_id"]: row["version_id"] for row in rows if row["version_id"]}

    def create(self, project_id: str, content: FigureCompositionContent, request_id: str) -> str:
        encoded = content.model_dump_json()
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            previous = self.connection.execute(
                "SELECT composition_id, request_json FROM figure_compositions "
                "WHERE project_id = ? AND request_id = ?",
                (project_id, request_id),
            ).fetchone()
            if previous:
                if previous["request_json"] != encoded:
                    raise DataError(
                        "This request already created a different figure.", "CONFLICT", 409
                    )
                return str(previous["composition_id"])
            composition_id = "figure_" + uuid4().hex
            now = utc_now().isoformat()
            self.connection.execute(
                "INSERT INTO figure_compositions VALUES (?, ?, 1, ?, ?, ?, ?, ?)",
                (composition_id, project_id, encoded, now, now, request_id, encoded),
            )
            self.connection.execute(
                "INSERT INTO figure_composition_revisions VALUES (?, 1, ?, 'Created figure', ?)",
                (composition_id, encoded, now),
            )
            self._retain_images(project_id, composition_id, content)
        return composition_id

    def save(
        self,
        project_id: str,
        composition_id: str,
        base_revision: int,
        content: FigureCompositionContent,
        summary: str,
        validate: Validator,
    ) -> None:
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            record = self._current(project_id, composition_id, base_revision)
            validate(content)
            self._commit(record, content, summary)

    def apply_operations(
        self,
        project_id: str,
        composition_id: str,
        request: FigureOperationsRequest,
        validate: Validator,
    ) -> None:
        encoded = request.model_dump_json()
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            previous = self.connection.execute(
                "SELECT request_json FROM figure_composition_operations "
                "WHERE composition_id = ? AND request_id = ?",
                (composition_id, request.request_id),
            ).fetchone()
            if previous:
                if previous["request_json"] != encoded:
                    raise DataError(
                        "This operation key was used for another change.", "CONFLICT", 409
                    )
                return
            record = self._current(project_id, composition_id, request.base_revision)
            updated = apply_figure_operations(record["content"], request.operations)
            validate(updated)
            self._commit(record, updated, request.summary)
            self.connection.execute(
                "INSERT INTO figure_composition_operations VALUES (?, ?, ?, ?)",
                (composition_id, request.request_id, encoded, record["revision"] + 1),
            )

    def change(
        self,
        project_id: str,
        composition_id: str,
        update: Callable[[FigureCompositionContent], FigureCompositionContent | None],
        summary: str,
        validate: Validator,
    ) -> bool:
        """Apply a background change to the latest revision; ``update`` returns None to skip."""
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            record = self.get(project_id, composition_id)
            updated = update(record["content"])
            if updated is None:
                return False
            validate(updated)
            self._commit(record, updated, summary)
            return True

    def create_jobs(
        self, composition_id: str, request_id: str, states: list[dict[str, Any]]
    ) -> list[str]:
        """Record one render per panel; repeating a request returns its original jobs."""
        job_ids = []
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            for state in states:
                key = f"{request_id}:{state['panel_id']}"
                previous = self.connection.execute(
                    "SELECT job_id, state_json FROM figure_composition_jobs "
                    "WHERE composition_id = ? AND request_key = ?",
                    (composition_id, key),
                ).fetchone()
                if previous:
                    saved = json.loads(previous["state_json"])
                    if (saved["width_mm"], saved["height_mm"]) != (
                        state["width_mm"],
                        state["height_mm"],
                    ):
                        raise DataError(
                            "This render key was used for another size.", "CONFLICT", 409
                        )
                    job_ids.append(str(previous["job_id"]))
                    continue
                job_id = "figure_job_" + uuid4().hex
                self.connection.execute(
                    "INSERT INTO figure_composition_jobs VALUES (?, ?, ?, 'running', ?, ?)",
                    (job_id, composition_id, key, json.dumps(state), utc_now().isoformat()),
                )
                job_ids.append(job_id)
        return job_ids

    def job(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            row = self.connection.execute(
                "SELECT * FROM figure_composition_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            raise DataError("The render was not found.", "NOT_FOUND", 404)
        return self._job_record(row)

    def update_job(self, job_id: str, status: str, changes: dict[str, Any]) -> None:
        with self.lock, self.connection:
            row = self.connection.execute(
                "SELECT state_json FROM figure_composition_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            state = {**json.loads(row["state_json"]), **changes}
            self.connection.execute(
                "UPDATE figure_composition_jobs SET status = ?, state_json = ? WHERE job_id = ?",
                (status, json.dumps(state), job_id),
            )

    def jobs(self, composition_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM figure_composition_jobs WHERE composition_id = ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (composition_id, limit),
            ).fetchall()
        return [self._job_record(row) for row in rows]

    def running_jobs(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM figure_composition_jobs WHERE status = 'running'"
            ).fetchall()
        return [self._job_record(row) for row in rows]

    @staticmethod
    def _job_record(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["state"] = json.loads(record.pop("state_json"))
        return record

    def history(self, composition_id: str, offset: int) -> tuple[list[dict[str, Any]], int]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT revision, summary, created_at FROM figure_composition_revisions "
                "WHERE composition_id = ? ORDER BY revision DESC LIMIT 30 OFFSET ?",
                (composition_id, offset),
            ).fetchall()
            total = self.connection.execute(
                "SELECT count(*) FROM figure_composition_revisions WHERE composition_id = ?",
                (composition_id,),
            ).fetchone()[0]
        return [dict(row) for row in rows], total

    def revision(self, composition_id: str, revision: int) -> FigureCompositionContent:
        with self.lock:
            row = self.connection.execute(
                "SELECT content_json FROM figure_composition_revisions "
                "WHERE composition_id = ? AND revision = ?",
                (composition_id, revision),
            ).fetchone()
        if row is None:
            raise DataError("Figure revision was not found.", "NOT_FOUND", 404)
        return FigureCompositionContent.model_validate_json(row["content_json"])

    def _current(self, project_id: str, composition_id: str, base_revision: int) -> dict[str, Any]:
        record = self.get(project_id, composition_id)
        if record["revision"] != base_revision:
            raise DataError(
                "The figure changed. Review the latest version and try again.",
                "FIGURE_CONFLICT",
                409,
            )
        return record

    def _retain_images(
        self, project_id: str, composition_id: str, content: FigureCompositionContent
    ) -> None:
        image_ids = [
            panel.content.image_id
            for panel in content.panels
            if isinstance(panel.content, ImagePanelContent)
        ]
        pin_reference_images(self.connection, project_id, image_ids, composition_id)

    def _commit(
        self, record: dict[str, Any], content: FigureCompositionContent, summary: str
    ) -> None:
        encoded = content.model_dump_json()
        revision, now = record["revision"] + 1, utc_now().isoformat()
        composition_id = record["composition_id"]
        self._retain_images(record["project_id"], composition_id, content)
        self.connection.execute(
            "UPDATE figure_compositions SET content_json = ?, revision = ?, updated_at = ? "
            "WHERE composition_id = ?",
            (encoded, revision, now, composition_id),
        )
        self.connection.execute(
            "INSERT INTO figure_composition_revisions VALUES (?, ?, ?, ?, ?)",
            (composition_id, revision, encoded, summary, now),
        )
