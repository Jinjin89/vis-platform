from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

from vis_platform_backend.data.errors import DataError

REFERENCE_IMAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS reference_images (
    image_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    metadata_json TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    request_key TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, request_key)
);
CREATE TABLE IF NOT EXISTS reference_image_links (
    image_id TEXT NOT NULL REFERENCES reference_images(image_id),
    owner_id TEXT NOT NULL,
    PRIMARY KEY(image_id, owner_id)
);
"""


def pin_reference_images(
    connection: sqlite3.Connection, project_id: str, image_ids: list[str], owner_id: str
) -> None:
    for image_id in image_ids:
        row = connection.execute(
            "SELECT 1 FROM reference_images WHERE image_id = ? AND project_id = ?",
            (image_id, project_id),
        ).fetchone()
        if row is None:
            raise DataError("The reference image was not found in this project.", "NOT_FOUND", 404)
        connection.execute(
            "INSERT OR IGNORE INTO reference_image_links (image_id, owner_id) VALUES (?, ?)",
            (image_id, owner_id),
        )


class ReferenceImageRepository:
    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.lock = RLock()

    def close(self) -> None:
        self.connection.close()

    def get(self, project_id: str, image_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT metadata_json FROM reference_images WHERE project_id = ? AND image_id = ?",
                (project_id, image_id),
            ).fetchone()
        return json.loads(row["metadata_json"]) if row else None

    def insert(self, metadata: dict[str, Any], fingerprint: str, request_key: str | None) -> str:
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if request_key:
                existing = self.connection.execute(
                    "SELECT image_id, fingerprint FROM reference_images "
                    "WHERE project_id = ? AND request_key = ?",
                    (metadata["project_id"], request_key),
                ).fetchone()
                if existing:
                    if existing["fingerprint"] != fingerprint:
                        raise DataError(
                            "This upload key was already used for another image.",
                            "IDEMPOTENCY_CONFLICT",
                            409,
                        )
                    return str(existing["image_id"])
            self.connection.execute(
                "INSERT INTO reference_images VALUES (?, ?, ?, ?, ?, ?)",
                (
                    metadata["image_id"],
                    metadata["project_id"],
                    json.dumps(metadata),
                    fingerprint,
                    request_key,
                    metadata["created_at"],
                ),
            )
        return str(metadata["image_id"])

    def delete(self, project_id: str, image_id: str) -> None:
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if self.get(project_id, image_id) is None:
                raise DataError("The reference image was not found.", "NOT_FOUND", 404)
            linked = self.connection.execute(
                "SELECT 1 FROM reference_image_links WHERE image_id = ? LIMIT 1", (image_id,)
            ).fetchone()
            if linked:
                raise DataError(
                    "This image is retained by a saved request or figure.", "IMAGE_IN_USE", 409
                )
            self.connection.execute("DELETE FROM reference_images WHERE image_id = ?", (image_id,))

    def expired(self, before: str) -> list[tuple[str, str]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT project_id, image_id FROM reference_images AS image "
                "WHERE created_at < ? AND NOT EXISTS "
                "(SELECT 1 FROM reference_image_links AS link "
                "WHERE link.image_id = image.image_id) "
                "LIMIT 100",
                (before,),
            ).fetchall()
        return [(row["project_id"], row["image_id"]) for row in rows]
