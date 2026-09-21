from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from vis_platform_backend.contracts.report_content import (
    MAX_SECTION_BLOCKS,
    LegacyReportContent,
    ReportContent,
    upgrade_report,
)
from vis_platform_backend.contracts.report_operations import ReportOperationsRequest
from vis_platform_backend.contracts.reports import ReportGenerateRequest
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.domain.report_operations import apply_report_operations
from vis_platform_backend.infrastructure.database import utc_now
from vis_platform_backend.infrastructure.reference_images import pin_reference_images
from vis_platform_backend.infrastructure.shared_figures import publish_version, selected_version

ACTIVE = ("running", "awaiting_input", "awaiting_approval")


class ReportRepository:
    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = RLock()
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS shared_figures (
                project_id TEXT NOT NULL REFERENCES projects(project_id),
                plot_id TEXT NOT NULL REFERENCES plots(plot_id),
                version_id TEXT NOT NULL REFERENCES plot_versions(version_id),
                PRIMARY KEY(project_id, plot_id)
            );
            CREATE TABLE IF NOT EXISTS reports (
                report_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(project_id),
                revision INTEGER NOT NULL,
                content_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                request_id TEXT NOT NULL,
                request_json TEXT NOT NULL,
                UNIQUE(project_id, request_id)
            );
            CREATE TABLE IF NOT EXISTS report_revisions (
                report_id TEXT NOT NULL REFERENCES reports(report_id),
                revision INTEGER NOT NULL,
                content_json TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(report_id, revision)
            );
            CREATE TABLE IF NOT EXISTS report_operations (
                report_id TEXT NOT NULL REFERENCES reports(report_id),
                request_id TEXT NOT NULL,
                request_json TEXT NOT NULL,
                result_revision INTEGER NOT NULL,
                PRIMARY KEY(report_id, request_id)
            );
            CREATE TABLE IF NOT EXISTS report_edits (
                edit_id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL REFERENCES reports(report_id),
                request_id TEXT NOT NULL,
                request_json TEXT NOT NULL,
                context_json TEXT NOT NULL,
                state_json TEXT NOT NULL,
                status TEXT NOT NULL,
                UNIQUE(report_id, request_id)
            );
        """)

    def close(self) -> None:
        self.connection.close()

    def get(self, project_id: str, report_id: str) -> dict[str, Any]:
        with self.lock:
            row = self.connection.execute(
                "SELECT * FROM reports WHERE project_id = ? AND report_id = ?",
                (project_id, report_id),
            ).fetchone()
        if row is None:
            raise DataError("Report was not found in this project.", "NOT_FOUND", 404)
        record = dict(row)
        record["content"] = self._content(json.loads(record.pop("content_json")), project_id)
        return record

    def _content(self, value: dict[str, Any], project_id: str) -> dict[str, Any]:
        if value.get("schema_version") == "2.0":
            return ReportContent.model_validate(value).model_dump(mode="json")

        def description(version_id: str) -> str:
            row = self.connection.execute(
                "SELECT r.result_json FROM plot_versions v JOIN plot_runs r ON r.run_id = v.run_id "
                "WHERE v.version_id = ? AND r.project_id = ?",
                (version_id, project_id),
            ).fetchone()
            result = json.loads(row[0]) if row else {}
            return str(result.get("caption") or result.get("preview", {}).get("description", ""))

        return upgrade_report(LegacyReportContent.model_validate(value), description).model_dump(
            mode="json"
        )

    @staticmethod
    def _edit_record(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for key in ("request", "context", "state"):
            item[key] = json.loads(item.pop(key + "_json"))
        item["request"] = ReportGenerateRequest.model_validate(item["request"]).model_dump(
            mode="json"
        )
        state = item["state"]
        if "topic_id" in state:
            state["section_id"] = state.pop("topic_id")
        block = item["context"].get("block")
        if block and block.get("version_id"):
            block["caption"] = ""
        return item

    def _snapshot(self, project_id: str, content: dict[str, Any]) -> str:
        snapshot = json.loads(json.dumps(content))
        for section in snapshot["sections"]:
            for block in section["blocks"]:
                if block["type"] == "figure" and block.get("follow_plot_id"):
                    block["version_id"] = (
                        selected_version(self.connection, project_id, block["follow_plot_id"])
                        or block["version_id"]
                    )
                    block["follow_plot_id"] = None
        return json.dumps(snapshot, sort_keys=True)

    def _pin(self, project_id: str, report_id: str, content: dict[str, Any]) -> None:
        image_ids = [
            block["image_id"]
            for topic in content["sections"]
            for block in topic["blocks"]
            if block["type"] == "figure" and block.get("image_id")
        ]
        pin_reference_images(self.connection, project_id, image_ids, report_id)

    def create(self, project_id: str, content: dict[str, Any], request_id: str) -> str:
        encoded = json.dumps(content, sort_keys=True)
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            previous = self.connection.execute(
                "SELECT report_id, request_json FROM reports "
                "WHERE project_id = ? AND request_id = ?",
                (project_id, request_id),
            ).fetchone()
            if previous:
                if (
                    json.dumps(
                        self._content(json.loads(previous["request_json"]), project_id),
                        sort_keys=True,
                    )
                    != encoded
                ):
                    raise DataError(
                        "This request already created a different report.", "CONFLICT", 409
                    )
                return str(previous["report_id"])
            report_id = "report_" + uuid4().hex
            now = utc_now().isoformat()
            self.connection.execute(
                "INSERT INTO reports VALUES (?, ?, 1, ?, ?, ?, ?, ?)",
                (report_id, project_id, encoded, now, now, request_id, encoded),
            )
            self.connection.execute(
                "INSERT INTO report_revisions VALUES (?, 1, ?, 'Created report', ?)",
                (report_id, self._snapshot(project_id, content), now),
            )
            self._pin(project_id, report_id, content)
        return report_id

    def list_reports(
        self, project_id: str, offset: int, kind: str = "report"
    ) -> tuple[list[dict[str, Any]], int]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT report_id, project_id, revision, updated_at, "
                "json_extract(content_json, '$.title') AS title FROM reports "
                "WHERE project_id = ? "
                "AND COALESCE(json_extract(content_json, '$.kind'), 'report') = ? "
                "ORDER BY updated_at DESC, report_id LIMIT 30 OFFSET ?",
                (project_id, kind, offset),
            ).fetchall()
            total = self.connection.execute(
                "SELECT count(*) FROM reports WHERE project_id = ? "
                "AND COALESCE(json_extract(content_json, '$.kind'), 'report') = ?",
                (project_id, kind),
            ).fetchone()[0]
        return [dict(row) for row in rows], total

    def save(
        self,
        project_id: str,
        report_id: str,
        base_revision: int,
        content: dict[str, Any],
        summary: str,
    ) -> None:
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            record = self.get(project_id, report_id)
            if record["revision"] != base_revision:
                raise DataError(
                    "The report changed. Review the latest version and try again.",
                    "REPORT_CONFLICT",
                    409,
                )
            if record["content"]["kind"] != content.get("kind", "report"):
                raise DataError("The document format cannot be changed.", "CONFLICT", 409)
            self._check_edit_targets(report_id, content)
            self._commit(record, content, summary)

    def _check_edit_targets(self, report_id: str, content: dict[str, Any]) -> None:
        for edit in self.edits(report_id):
            if edit["state"]["status"] not in ACTIVE or edit["request"]["kind"] == "discussion":
                continue
            request = edit["request"]
            topic = next(
                (item for item in content["sections"] if item["id"] == request["section_id"]), None
            )
            if topic is None:
                raise DataError(
                    "Cancel the running edit before removing its topic.", "REPORT_BUSY", 409
                )
            if request.get("block_id"):
                block = next((b for b in topic["blocks"] if b["id"] == request["block_id"]), None)
                if block != edit["context"].get("block"):
                    raise DataError(
                        "This block has a running edit. Cancel it first.", "REPORT_BUSY", 409
                    )

    def _commit(self, record: dict[str, Any], content: dict[str, Any], summary: str) -> None:
        encoded = json.dumps(content, sort_keys=True)
        revision, now = record["revision"] + 1, utc_now().isoformat()
        self._pin(record["project_id"], record["report_id"], content)
        self.connection.execute(
            "UPDATE reports SET content_json = ?, revision = ?, updated_at = ? WHERE report_id = ?",
            (encoded, revision, now, record["report_id"]),
        )
        self.connection.execute(
            "INSERT INTO report_revisions VALUES (?, ?, ?, ?, ?)",
            (
                record["report_id"],
                revision,
                self._snapshot(record["project_id"], content),
                summary,
                now,
            ),
        )

    def history(self, report_id: str, offset: int) -> tuple[list[dict[str, Any]], int]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT revision, summary, created_at FROM report_revisions WHERE report_id = ? "
                "ORDER BY revision DESC LIMIT 30 OFFSET ?",
                (report_id, offset),
            ).fetchall()
            total = self.connection.execute(
                "SELECT count(*) FROM report_revisions WHERE report_id = ?", (report_id,)
            ).fetchone()[0]
        return [dict(row) for row in rows], total

    def revision(self, report_id: str, revision: int) -> dict[str, Any]:
        with self.lock:
            row = self.connection.execute(
                "SELECT v.content_json, r.project_id FROM report_revisions v "
                "JOIN reports r ON r.report_id = v.report_id "
                "WHERE v.report_id = ? AND v.revision = ?",
                (report_id, revision),
            ).fetchone()
        if not row:
            raise DataError("Report revision was not found.", "NOT_FOUND", 404)
        return self._content(json.loads(row[0]), str(row["project_id"]))

    def edits(self, report_id: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM report_edits WHERE report_id = ? ORDER BY rowid"
                if report_id
                else "SELECT * FROM report_edits WHERE status "
                "IN ('running', 'awaiting_input', 'awaiting_approval')",
                (report_id,) if report_id else (),
            ).fetchall()
        return [self._edit_record(row) for row in rows]

    def get_edit(self, edit_id: str) -> dict[str, Any]:
        with self.lock:
            row = self.connection.execute(
                "SELECT * FROM report_edits WHERE edit_id = ?", (edit_id,)
            ).fetchone()
        if not row:
            raise DataError("Report edit was not found.", "NOT_FOUND", 404)
        return self._edit_record(row)

    def edit_for_request(self, report_id: str, request_id: str) -> dict[str, Any]:
        with self.lock:
            row = self.connection.execute(
                "SELECT * FROM report_edits WHERE report_id = ? AND request_id = ?",
                (report_id, request_id),
            ).fetchone()
        if row is None:
            raise DataError("The report edit was not found.", "NOT_FOUND", 404)
        return self._edit_record(row)

    def create_edit(
        self,
        project_id: str,
        report_id: str,
        request: dict[str, Any],
        context: dict[str, Any],
        state: dict[str, Any],
    ) -> str:
        encoded = json.dumps(request, sort_keys=True)
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            previous = self.connection.execute(
                "SELECT edit_id, request_json FROM report_edits "
                "WHERE report_id = ? AND request_id = ?",
                (report_id, request["request_id"]),
            ).fetchone()
            if previous:
                if previous["request_json"] != encoded:
                    raise DataError(
                        "This edit key was used for different instructions.", "CONFLICT", 409
                    )
                return str(previous["edit_id"])
            record = self.get(project_id, report_id)
            if record["revision"] != request["base_revision"]:
                raise DataError(
                    "The report changed. Review the latest version and try again.",
                    "REPORT_CONFLICT",
                    409,
                )
            if (
                request["kind"] != "discussion"
                and request.get("block_id")
                and any(
                    edit["state"]["status"] in ACTIVE
                    and edit["request"]["kind"] != "discussion"
                    and edit["request"].get("block_id") == request["block_id"]
                    for edit in self.edits(report_id)
                )
            ):
                raise DataError("This block already has a running edit.", "REPORT_BUSY", 409)
            if any(
                edit["state"]["status"] in ACTIVE
                and edit["state"]["output_block_id"] == state["output_block_id"]
                for edit in self.edits(report_id)
            ):
                raise DataError(
                    "This output block already has a running request.", "REPORT_BUSY", 409
                )
            self.connection.execute(
                "INSERT INTO report_edits VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    state["edit_id"],
                    report_id,
                    request["request_id"],
                    encoded,
                    json.dumps(context),
                    json.dumps(state),
                    state["status"],
                ),
            )
        return str(state["edit_id"])

    def update_edit(self, edit_id: str, update: dict[str, Any]) -> None:
        with self.lock, self.connection:
            record = self.get_edit(edit_id)
            state = {**record["state"], **update}
            self.connection.execute(
                "UPDATE report_edits SET state_json = ?, status = ? WHERE edit_id = ?",
                (json.dumps(state), state["status"], edit_id),
            )

    def finish_edit(
        self,
        edit_id: str,
        project_id: str,
        block: dict[str, Any],
        *,
        response_text: str | None = None,
        shared_update: tuple[str, str, str | None] | None = None,
    ) -> None:
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            edit = self.get_edit(edit_id)
            if edit["state"]["status"] not in ACTIVE:
                return
            record = self.get(project_id, edit["report_id"])
            content = record["content"]
            topic = next(
                (t for t in content["sections"] if t["id"] == edit["request"]["section_id"]), None
            )
            if topic is None:
                raise DataError("The destination topic no longer exists.", "REPORT_CONFLICT", 409)
            target = edit["request"].get("block_id")
            if target and not edit["request"]["insert_new"]:
                index = next((i for i, b in enumerate(topic["blocks"]) if b["id"] == target), None)
                if index is None or topic["blocks"][index] != edit["context"].get("block"):
                    raise DataError(
                        "The original block changed while this edit ran.", "REPORT_CONFLICT", 409
                    )
                topic["blocks"][index] = block
            else:
                if len(topic["blocks"]) >= MAX_SECTION_BLOCKS:
                    raise DataError("This topic has reached its block limit.", "REPORT_FULL", 409)
                before_id = edit["request"].get("before_block_id")
                after_id = edit["request"].get("after_block_id") or target
                anchor = before_id or after_id
                if anchor and not any(item["id"] == anchor for item in topic["blocks"]):
                    raise DataError(
                        "The insertion anchor changed while content was generated.",
                        "REPORT_CONFLICT",
                        409,
                    )
                after = next(
                    (
                        i + (0 if before_id else 1)
                        for i, item in enumerate(topic["blocks"])
                        if item["id"] == anchor
                    ),
                    len(topic["blocks"]),
                )
                topic["blocks"].insert(after, block)
            content = ReportContent.model_validate(content).model_dump(mode="json")
            if shared_update:
                plot_id, version_id, expected = shared_update
                publish_version(self.connection, project_id, plot_id, version_id, expected)
            self._commit(
                record,
                content,
                "Generated " + edit["request"]["kind"] + " · " + topic["title"][:140],
            )
            state = {
                **edit["state"],
                "status": "completed",
                "error": None,
                "response_text": response_text,
            }
            self.connection.execute(
                "UPDATE report_edits SET state_json = ?, status = 'completed' WHERE edit_id = ?",
                (json.dumps(state), edit_id),
            )

    def apply_operations(
        self,
        project_id: str,
        report_id: str,
        request: ReportOperationsRequest,
        validate: Callable[[ReportContent], None],
    ) -> int:
        encoded = request.model_dump_json()
        with self.lock, self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            record = self.get(project_id, report_id)
            previous = self.connection.execute(
                "SELECT request_json, result_revision FROM report_operations "
                "WHERE report_id = ? AND request_id = ?",
                (report_id, request.request_id),
            ).fetchone()
            if previous:
                if previous["request_json"] != encoded:
                    raise DataError(
                        "This operation key was used for another change.", "CONFLICT", 409
                    )
                return int(previous["result_revision"])
            if record["revision"] != request.base_revision:
                raise DataError(
                    "The report changed while preparing this edit.", "REPORT_CONFLICT", 409
                )
            try:
                updated = apply_report_operations(
                    ReportContent.model_validate(record["content"]), request.operations
                )
            except ValueError as error:
                raise DataError(
                    "The changes violate the report's heading levels, order, or unique IDs.",
                    "INVALID_REPORT_OPERATION",
                    422,
                ) from error
            validate(updated)
            content = updated.model_dump(mode="json")
            self._check_edit_targets(report_id, content)
            self._commit(record, content, request.summary)
            revision = int(record["revision"]) + 1
            self.connection.execute(
                "INSERT INTO report_operations VALUES (?, ?, ?, ?)",
                (report_id, request.request_id, encoded, revision),
            )
            return revision
