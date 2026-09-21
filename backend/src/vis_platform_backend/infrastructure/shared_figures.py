"""Explicit shared figure selection, separate from experimental plot history."""

from __future__ import annotations

import sqlite3

from vis_platform_backend.data.errors import DataError


def selected_version(connection: sqlite3.Connection, project_id: str, plot_id: str) -> str | None:
    row = connection.execute(
        "SELECT version_id FROM shared_figures WHERE project_id = ? AND plot_id = ?",
        (project_id, plot_id),
    ).fetchone()
    return str(row[0]) if row else None


def publish_version(
    connection: sqlite3.Connection,
    project_id: str,
    plot_id: str,
    version_id: str,
    expected: str | None,
    *,
    initialize: bool = False,
) -> str:
    owned = connection.execute(
        "SELECT 1 FROM plot_versions v JOIN plots p ON p.plot_id = v.plot_id "
        "WHERE p.project_id = ? AND p.plot_id = ? AND v.version_id = ?",
        (project_id, plot_id, version_id),
    ).fetchone()
    if not owned:
        raise DataError("The figure version was not found in this project.", "NOT_FOUND", 404)
    current = selected_version(connection, project_id, plot_id)
    if initialize and current:
        return current
    if current == version_id:
        return version_id
    if current != expected:
        raise DataError(
            "The linked figure changed. Review it before publishing this version.",
            "FIGURE_CONFLICT",
            409,
        )
    connection.execute(
        "INSERT INTO shared_figures VALUES (?, ?, ?) "
        "ON CONFLICT(project_id, plot_id) DO UPDATE SET version_id = excluded.version_id",
        (project_id, plot_id, version_id),
    )
    return version_id
