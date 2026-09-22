from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from vis_platform_backend.data.errors import DataError

# Created by the main repository, whose assistant turns and history depend on these tables.
WORKSPACE_SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_sessions (
    session_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    title TEXT NOT NULL,
    request_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, request_id)
);
CREATE TABLE IF NOT EXISTS workspace_session_turns (
    turn_id TEXT PRIMARY KEY REFERENCES assistant_turns(turn_id),
    session_id TEXT NOT NULL REFERENCES workspace_sessions(session_id)
);
CREATE INDEX IF NOT EXISTS workspace_session_turns_by_session
    ON workspace_session_turns(session_id);
"""


def link_session_turn(
    connection: sqlite3.Connection, project_id: str, session_id: str, turn_id: str
) -> None:
    """Add a new turn to its conversation inside the caller's transaction."""
    updated = connection.execute(
        "UPDATE workspace_sessions SET updated_at = ? WHERE session_id = ? AND project_id = ?",
        (datetime.now(UTC).isoformat(), session_id, project_id),
    ).rowcount
    if not updated:
        raise DataError("The conversation was not found in this project.", "NOT_FOUND", 404)
    connection.execute(
        "INSERT INTO workspace_session_turns (turn_id, session_id) VALUES (?, ?)",
        (turn_id, session_id),
    )


class WorkspaceSessionRepository:
    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.lock = RLock()

    def close(self) -> None:
        self.connection.close()

    def create(self, project_id: str, title: str, request_id: str) -> str:
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            previous = self.connection.execute(
                "SELECT session_id, title FROM workspace_sessions "
                "WHERE project_id = ? AND request_id = ?",
                (project_id, request_id),
            ).fetchone()
            if previous:
                if previous["title"] != title:
                    raise DataError(
                        "This request already started a different conversation.", "CONFLICT", 409
                    )
                return str(previous["session_id"])
            session_id = "session_" + uuid4().hex
            now = datetime.now(UTC).isoformat()
            self.connection.execute(
                "INSERT INTO workspace_sessions VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, project_id, title, request_id, now, now),
            )
        return session_id

    def get(self, project_id: str, session_id: str) -> dict[str, Any]:
        with self.lock:
            row = self.connection.execute(
                "SELECT session_id, project_id, title, created_at, updated_at "
                "FROM workspace_sessions WHERE project_id = ? AND session_id = ?",
                (project_id, session_id),
            ).fetchone()
        if row is None:
            raise DataError("The conversation was not found in this project.", "NOT_FOUND", 404)
        return dict(row)

    def list_sessions(self, project_id: str, offset: int) -> tuple[list[dict[str, Any]], int]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT session_id, project_id, title, created_at, updated_at "
                "FROM workspace_sessions WHERE project_id = ? "
                "ORDER BY updated_at DESC, rowid DESC LIMIT 30 OFFSET ?",
                (project_id, offset),
            ).fetchall()
            total = self.connection.execute(
                "SELECT count(*) FROM workspace_sessions WHERE project_id = ?", (project_id,)
            ).fetchone()[0]
        return [dict(row) for row in rows], total

    def turn_ids(self, session_id: str) -> list[str]:
        """The conversation's turns in the order they were sent."""
        with self.lock:
            rows = self.connection.execute(
                "SELECT turn.turn_id FROM workspace_session_turns AS link "
                "JOIN assistant_turns AS turn ON turn.turn_id = link.turn_id "
                "WHERE link.session_id = ? ORDER BY turn.rowid",
                (session_id,),
            ).fetchall()
        return [str(row["turn_id"]) for row in rows]
