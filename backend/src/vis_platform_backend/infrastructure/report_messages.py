from __future__ import annotations

import json
from typing import Any

from vis_platform_backend.data.errors import DataError
from vis_platform_backend.infrastructure.reports import ReportRepository


class ReportMessageStore:
    """Shares the report transaction/lock so document and conversation snapshots agree."""

    def __init__(self, reports: ReportRepository) -> None:
        self.reports = reports
        self.connection, self.lock = reports.connection, reports.lock
        with self.lock, self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS report_messages (
                    message_id TEXT PRIMARY KEY,
                    report_id TEXT NOT NULL REFERENCES reports(report_id),
                    request_id TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    execution_json TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    UNIQUE(report_id, request_id)
                )
            """)

    @staticmethod
    def decode(row: Any) -> dict[str, Any]:
        record = dict(row)
        for name in ("request", "execution", "state"):
            record[name] = json.loads(record.pop(name + "_json"))
        return record

    def create(
        self, project_id: str, report_id: str, request: dict[str, Any], state: dict[str, Any]
    ) -> str:
        encoded = json.dumps(request, sort_keys=True)
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            self.reports.get(project_id, report_id)
            previous = self.connection.execute(
                "SELECT * FROM report_messages WHERE report_id = ? AND request_id = ?",
                (report_id, request["request_id"]),
            ).fetchone()
            if previous:
                if previous["request_json"] != encoded:
                    raise DataError(
                        "This message key was already used for another request.", "CONFLICT", 409
                    )
                return str(previous["message_id"])
            execution: dict[str, Any] = {
                "plan": None,
                "step": 0,
                "revision": None,
                "step_request": None,
                "answers": [],
            }
            self.connection.execute(
                "INSERT INTO report_messages VALUES (?, ?, ?, ?, ?, ?)",
                (
                    state["message_id"],
                    report_id,
                    request["request_id"],
                    encoded,
                    json.dumps(execution),
                    json.dumps(state),
                ),
            )
        return str(state["message_id"])

    def get(self, message_id: str) -> dict[str, Any]:
        with self.lock:
            row = self.connection.execute(
                "SELECT m.*, r.project_id FROM report_messages m "
                "JOIN reports r ON r.report_id = m.report_id "
                "WHERE m.message_id = ?",
                (message_id,),
            ).fetchone()
        if row is None:
            raise DataError("Report message was not found.", "NOT_FOUND", 404)
        return self.decode(row)

    def list_messages(self, report_id: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM report_messages WHERE report_id = ? ORDER BY rowid"
                if report_id
                else "SELECT * FROM report_messages WHERE json_extract(state_json, '$.status') "
                "IN ('running','awaiting_input','awaiting_approval')",
                (report_id,) if report_id else (),
            ).fetchall()
        return [self.decode(row) for row in rows]

    def list_states(self, report_id: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT state_json FROM report_messages WHERE report_id = ? ORDER BY rowid",
                (report_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def update(
        self,
        message_id: str,
        state: dict[str, Any] | None = None,
        execution: dict[str, Any] | None = None,
    ) -> None:
        with self.lock, self.connection:
            record = self.get(message_id)
            self.connection.execute(
                "UPDATE report_messages SET state_json = ?, execution_json = ? "
                "WHERE message_id = ?",
                (
                    json.dumps({**record["state"], **(state or {})}),
                    json.dumps({**record["execution"], **(execution or {})}),
                    message_id,
                ),
            )
