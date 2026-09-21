from __future__ import annotations

import json
from typing import Any

from vis_platform_backend.data.errors import DataError
from vis_platform_backend.infrastructure.figure_compositions import FigureCompositionRepository

ACTIVE = ("running", "awaiting_input", "awaiting_approval")


class FigureMessageStore:
    """Shares the figure store's connection so a message and its edits commit consistently."""

    def __init__(self, figures: FigureCompositionRepository) -> None:
        self.figures = figures
        self.connection, self.lock = figures.connection, figures.lock
        with self.lock, self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS figure_composition_messages (
                    message_id TEXT PRIMARY KEY,
                    composition_id TEXT NOT NULL REFERENCES figure_compositions(composition_id),
                    request_id TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    execution_json TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    UNIQUE(composition_id, request_id)
                )
            """)

    @staticmethod
    def _decode(row: Any) -> dict[str, Any]:
        record = dict(row)
        for name in ("request", "execution", "state"):
            record[name] = json.loads(record.pop(name + "_json"))
        return record

    def create(
        self, project_id: str, composition_id: str, request: dict[str, Any], state: dict[str, Any]
    ) -> str:
        encoded = json.dumps(request, sort_keys=True)
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            self.figures.get(project_id, composition_id)
            previous = self.connection.execute(
                "SELECT message_id, request_json FROM figure_composition_messages "
                "WHERE composition_id = ? AND request_id = ?",
                (composition_id, request["request_id"]),
            ).fetchone()
            if previous:
                if previous["request_json"] != encoded:
                    raise DataError(
                        "This message key was already used for another request.", "CONFLICT", 409
                    )
                return str(previous["message_id"])
            execution: dict[str, Any] = {
                "steps": None,
                "step": 0,
                "answers": [],
                "reviews": 0,
                "plot": None,
            }
            self.connection.execute(
                "INSERT INTO figure_composition_messages VALUES (?, ?, ?, ?, ?, ?)",
                (
                    state["message_id"],
                    composition_id,
                    request["request_id"],
                    encoded,
                    json.dumps(execution),
                    json.dumps(state),
                ),
            )
        return str(state["message_id"])

    def submitted(self, composition_id: str, request_id: str) -> bool:
        with self.lock:
            row = self.connection.execute(
                "SELECT 1 FROM figure_composition_messages "
                "WHERE composition_id = ? AND request_id = ?",
                (composition_id, request_id),
            ).fetchone()
        return row is not None

    def get(self, message_id: str) -> dict[str, Any]:
        with self.lock:
            row = self.connection.execute(
                "SELECT m.*, f.project_id FROM figure_composition_messages m "
                "JOIN figure_compositions f ON f.composition_id = m.composition_id "
                "WHERE m.message_id = ?",
                (message_id,),
            ).fetchone()
        if row is None:
            raise DataError("Figure message was not found.", "NOT_FOUND", 404)
        return self._decode(row)

    def list_messages(self, composition_id: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM figure_composition_messages WHERE composition_id = ? ORDER BY rowid",
                (composition_id,),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def active_messages(self) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM figure_composition_messages "
                "WHERE json_extract(state_json, '$.status') IN "
                "('running', 'awaiting_input', 'awaiting_approval')"
            ).fetchall()
        return [self._decode(row) for row in rows]

    def update(
        self,
        message_id: str,
        state: dict[str, Any] | None = None,
        execution: dict[str, Any] | None = None,
    ) -> None:
        with self.lock, self.connection:
            record = self.get(message_id)
            self.connection.execute(
                "UPDATE figure_composition_messages SET state_json = ?, execution_json = ? "
                "WHERE message_id = ?",
                (
                    json.dumps({**record["state"], **(state or {})}),
                    json.dumps({**record["execution"], **(execution or {})}),
                    message_id,
                ),
            )
