from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

from vis_platform_backend.contracts.developer_trace import DeveloperTraceEntry
from vis_platform_backend.contracts.plot_runs import (
    RUN_EVENT_ADAPTER,
    EventType,
    RunEvent,
    RunStage,
    RunStatus,
    build_run_event,
)
from vis_platform_backend.contracts.projects import Project
from vis_platform_backend.infrastructure.reference_images import (
    REFERENCE_IMAGE_SCHEMA,
    pin_reference_images,
)
from vis_platform_backend.infrastructure.workspace_sessions import (
    WORKSPACE_SESSION_SCHEMA,
    link_session_turn,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class RequestConflictError(ValueError):
    pass


class Repository:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()

    def initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plot_runs (
                    run_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    request_json TEXT NOT NULL,
                    interaction_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plot_run_keys (
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    idempotency_key TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    run_id TEXT NOT NULL REFERENCES plot_runs(run_id),
                    PRIMARY KEY (project_id, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS run_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES plot_runs(run_id),
                    sequence INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE (run_id, sequence)
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES plot_runs(run_id),
                    media_type TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    storage_path TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plots (
                    plot_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    current_version_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plot_versions (
                    version_id TEXT PRIMARY KEY,
                    plot_id TEXT NOT NULL REFERENCES plots(plot_id),
                    run_id TEXT NOT NULL UNIQUE REFERENCES plot_runs(run_id),
                    parent_version_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS assistant_turns (
                    turn_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    request_json TEXT NOT NULL,
                    intent_json TEXT,
                    outcome TEXT,
                    message TEXT,
                    run_id TEXT REFERENCES plot_runs(run_id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS assistant_request_keys (
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    request_key TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    turn_id TEXT NOT NULL REFERENCES assistant_turns(turn_id),
                    PRIMARY KEY (project_id, request_key)
                );

                CREATE TABLE IF NOT EXISTS assistant_execution (
                    turn_id TEXT PRIMARY KEY REFERENCES assistant_turns(turn_id),
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    response_json TEXT,
                    question_json TEXT,
                    answer_batches_json TEXT NOT NULL DEFAULT '[]',
                    error_json TEXT
                );
                CREATE TABLE IF NOT EXISTS assistant_activity (
                    turn_id TEXT NOT NULL REFERENCES assistant_turns(turn_id),
                    sequence INTEGER NOT NULL,
                    entry_json TEXT NOT NULL,
                    PRIMARY KEY (turn_id, sequence)
                );

                CREATE TABLE IF NOT EXISTS developer_traces (
                    trace_id TEXT PRIMARY KEY,
                    turn_id TEXT NOT NULL REFERENCES assistant_turns(turn_id),
                    run_id TEXT REFERENCES plot_runs(run_id),
                    sequence INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    duration_ms INTEGER,
                    input_json TEXT,
                    output_json TEXT,
                    error_json TEXT,
                    UNIQUE (turn_id, sequence)
                );
                """
            )

            self._connection.executescript(REFERENCE_IMAGE_SCHEMA)
            self._connection.executescript(WORKSPACE_SESSION_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def create_project(self, project: Project) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO projects (project_id, name, created_at) VALUES (?, ?, ?)",
                (project.project_id, project.name, project.created_at.isoformat()),
            )

    def get_project(self, project_id: str) -> Project | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        return Project.model_validate(dict(row)) if row is not None else None

    def project_exists(self, project_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        return row is not None

    def create_run(
        self,
        *,
        run_id: str,
        project_id: str,
        request: dict[str, Any],
        status: RunStatus,
        stage: RunStage,
        created_at: datetime,
        idempotency_key: str | None = None,
    ) -> str:
        timestamp = created_at.isoformat()
        encoded = json.dumps(request, sort_keys=True)
        with self._lock, self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                previous = self._connection.execute(
                    "SELECT request_json, run_id FROM plot_run_keys "
                    "WHERE project_id = ? AND idempotency_key = ?",
                    (project_id, idempotency_key),
                ).fetchone()
                if previous is not None:
                    if previous["request_json"] != encoded:
                        raise RequestConflictError(
                            "This request key was already used for different changes."
                        )
                    return str(previous["run_id"])
            pin_reference_images(
                self._connection,
                project_id,
                request.get("request", {}).get("reference_image_ids") or [],
                run_id,
            )
            self._connection.execute(
                """
                INSERT INTO plot_runs (
                    run_id, project_id, request_json, interaction_json, status, stage,
                    result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    run_id,
                    project_id,
                    encoded,
                    json.dumps({}),
                    status.value,
                    stage.value,
                    timestamp,
                    timestamp,
                ),
            )
            if idempotency_key is not None:
                self._connection.execute(
                    "INSERT INTO plot_run_keys (project_id, idempotency_key, request_json, run_id) "
                    "VALUES (?, ?, ?, ?)",
                    (project_id, idempotency_key, encoded, run_id),
                )
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM plot_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["request"] = json.loads(result.pop("request_json"))
        result["interaction"] = json.loads(result.pop("interaction_json"))
        result_json = result.pop("result_json")
        result["result"] = json.loads(result_json) if result_json is not None else None
        return result

    def update_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        stage: RunStage,
        result: dict[str, Any] | None = None,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE plot_runs
                SET status = ?, stage = ?, result_json = COALESCE(?, result_json), updated_at = ?
                WHERE run_id = ?
                """,
                (
                    status.value,
                    stage.value,
                    json.dumps(result) if result is not None else None,
                    utc_now().isoformat(),
                    run_id,
                ),
            )

    def update_interaction(self, run_id: str, interaction: dict[str, Any]) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE plot_runs
                SET interaction_json = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (json.dumps(interaction), utc_now().isoformat(), run_id),
            )

    def commit_completed_run(
        self,
        *,
        run_id: str,
        project_id: str,
        plot_id: str,
        version_id: str,
        parent_version_id: str | None,
        stage: RunStage,
        result: dict[str, Any],
        artifact_id: str,
        artifact_media_type: str,
        artifact_filename: str,
        artifact_storage_path: Path,
        make_current: bool = True,
    ) -> None:
        """Save a version; placement renders for figure panels leave the current version as is."""
        timestamp = utc_now().isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO artifacts (
                    artifact_id, run_id, media_type, filename, storage_path
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    run_id,
                    artifact_media_type,
                    artifact_filename,
                    str(artifact_storage_path),
                ),
            )
            if parent_version_id is None:
                self._connection.execute(
                    """
                    INSERT INTO plots (plot_id, project_id, current_version_id, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (plot_id, project_id, version_id, timestamp),
                )
            self._connection.execute(
                """
                INSERT INTO plot_versions (
                    version_id, plot_id, run_id, parent_version_id, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (version_id, plot_id, run_id, parent_version_id, timestamp),
            )
            if make_current:
                self._connection.execute(
                    "UPDATE plots SET current_version_id = ? WHERE plot_id = ?",
                    (version_id, plot_id),
                )
            self._connection.execute(
                """
                UPDATE plot_runs
                SET status = ?, stage = ?, result_json = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    RunStatus.COMPLETED.value,
                    stage.value,
                    json.dumps(result),
                    timestamp,
                    run_id,
                ),
            )

    def version_exists(self, version_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM plot_versions WHERE version_id = ?", (version_id,)
            ).fetchone()
        return row is not None

    def version_belongs_to_project(self, version_id: str, project_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT 1
                FROM plot_versions AS version
                JOIN plots AS plot ON plot.plot_id = version.plot_id
                WHERE version.version_id = ? AND plot.project_id = ?
                """,
                (version_id, project_id),
            ).fetchone()
        return row is not None

    def plot_id_for_version(self, version_id: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT plot_id FROM plot_versions WHERE version_id = ?", (version_id,)
            ).fetchone()
        return str(row["plot_id"]) if row is not None else None

    def run_id_for_version(self, project_id: str, plot_id: str, version_id: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                """SELECT version.run_id FROM plot_versions AS version
                   JOIN plots AS plot ON plot.plot_id = version.plot_id
                   WHERE plot.project_id = ? AND plot.plot_id = ? AND version.version_id = ?
                """,
                (project_id, plot_id, version_id),
            ).fetchone()
        return str(row["run_id"]) if row else None

    def current_run_id(self, project_id: str, plot_id: str) -> str | None:
        """The run that produced the plot's current version."""
        with self._lock:
            row = self._connection.execute(
                """SELECT version.run_id FROM plots AS plot
                   JOIN plot_versions AS version ON version.version_id = plot.current_version_id
                   WHERE plot.project_id = ? AND plot.plot_id = ?""",
                (project_id, plot_id),
            ).fetchone()
        return str(row["run_id"]) if row else None

    def plot_versions(self, project_id: str, plot_id: str) -> dict[str, Any] | None:
        with self._lock:
            plot = self._connection.execute(
                "SELECT current_version_id FROM plots WHERE project_id = ? AND plot_id = ?",
                (project_id, plot_id),
            ).fetchone()
            if plot is None:
                return None
            rows = self._connection.execute(
                """SELECT version.*, run.request_json, run.result_json
                   FROM plot_versions AS version
                   JOIN plot_runs AS run ON run.run_id = version.run_id
                   WHERE version.plot_id = ? ORDER BY version.rowid DESC""",
                (plot_id,),
            ).fetchall()
        return {
            "current_version_id": plot["current_version_id"],
            "versions": [
                {
                    "version_id": row["version_id"],
                    "run_id": row["run_id"],
                    "parent_version_id": row["parent_version_id"],
                    "created_at": row["created_at"],
                    "change_summary": json.loads(row["request_json"])["request"]["text"],
                    "result": json.loads(row["result_json"]),
                }
                for row in rows
            ],
        }

    def request_history_for_version(self, version_id: str) -> list[dict[str, Any]]:
        """Return the persisted run requests for a version lineage, root first."""
        with self._lock:
            rows = self._connection.execute(
                """
                WITH RECURSIVE version_lineage (run_id, parent_version_id, depth) AS (
                    SELECT run_id, parent_version_id, 0
                    FROM plot_versions
                    WHERE version_id = ?

                    UNION ALL

                    SELECT parent.run_id, parent.parent_version_id, lineage.depth + 1
                    FROM plot_versions AS parent
                    JOIN version_lineage AS lineage
                      ON parent.version_id = lineage.parent_version_id
                )
                SELECT run.request_json
                FROM version_lineage AS lineage
                JOIN plot_runs AS run ON run.run_id = lineage.run_id
                ORDER BY lineage.depth DESC
                """,
                (version_id,),
            ).fetchall()
        return [json.loads(row["request_json"]) for row in rows]

    def active_run_ids(self) -> list[str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT run_id FROM plot_runs WHERE status IN (?, ?)",
                (RunStatus.QUEUED.value, RunStatus.RUNNING.value),
            ).fetchall()
        return [str(row["run_id"]) for row in rows]

    def create_assistant_turn(
        self,
        *,
        turn_id: str,
        project_id: str,
        request: dict[str, Any],
        created_at: datetime,
        idempotency_key: str | None = None,
    ) -> str:
        timestamp = created_at.isoformat()
        encoded = json.dumps(request, sort_keys=True)
        with self._lock, self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                previous = self._connection.execute(
                    "SELECT request_json, turn_id FROM assistant_request_keys "
                    "WHERE project_id = ? AND request_key = ?",
                    (project_id, idempotency_key),
                ).fetchone()
                if previous is not None:
                    if previous["request_json"] != encoded:
                        raise RequestConflictError(
                            "This request key was already used for another message."
                        )
                    return str(previous["turn_id"])
            pin_reference_images(
                self._connection,
                project_id,
                request.get("request", {}).get("reference_image_ids") or [],
                turn_id,
            )
            self._connection.execute(
                """
                INSERT INTO assistant_turns (
                    turn_id, project_id, request_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    turn_id,
                    project_id,
                    encoded,
                    timestamp,
                    timestamp,
                ),
            )
            if request.get("session_id"):
                link_session_turn(self._connection, project_id, request["session_id"], turn_id)
            if idempotency_key is not None:
                self._connection.execute(
                    "INSERT INTO assistant_request_keys VALUES (?, ?, ?, ?)",
                    (project_id, idempotency_key, encoded, turn_id),
                )
        return turn_id

    def complete_assistant_turn(
        self,
        *,
        turn_id: str,
        intent: dict[str, Any],
        outcome: str,
        message: str | None,
        run_id: str | None,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                UPDATE assistant_turns
                SET intent_json = ?, outcome = ?, message = ?, run_id = ?, updated_at = ?
                WHERE turn_id = ?
                """,
                (
                    json.dumps(intent),
                    outcome,
                    message,
                    run_id,
                    utc_now().isoformat(),
                    turn_id,
                ),
            )

    def get_assistant_turn(self, turn_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM assistant_turns WHERE turn_id = ?", (turn_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["request"] = json.loads(result.pop("request_json"))
        intent_json = result.pop("intent_json")
        result["intent"] = json.loads(intent_json) if intent_json is not None else None
        return result

    def assistant_history(
        self, project_id: str, *, before_turn_id: str, limit: int = 12
    ) -> list[dict[str, Any]]:
        """Read completed prior turns of the same conversation, oldest first, in a bounded window.

        Turns outside a workspace conversation share one history, as before conversations existed.
        """
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT turn.request_json, turn.message, run.status AS run_status, run.result_json
                FROM assistant_turns AS turn
                LEFT JOIN plot_runs AS run ON run.run_id = turn.run_id
                LEFT JOIN workspace_session_turns AS link ON link.turn_id = turn.turn_id
                WHERE turn.project_id = ? AND turn.outcome IS NOT NULL
                  AND turn.rowid < (SELECT rowid FROM assistant_turns WHERE turn_id = ?)
                  AND link.session_id IS (
                      SELECT session_id FROM workspace_session_turns WHERE turn_id = ?
                  )
                ORDER BY turn.rowid DESC
                LIMIT ?
                """,
                (project_id, before_turn_id, before_turn_id, limit),
            ).fetchall()
        return [
            {
                "text": json.loads(row["request_json"])["request"]["text"],
                "reference_image_ids": json.loads(row["request_json"])["request"].get(
                    "reference_image_ids"
                )
                or [],
                "message": row["message"],
                "run_status": row["run_status"],
                "result": json.loads(row["result_json"]) if row["result_json"] else None,
            }
            for row in reversed(rows)
        ]

    def result_for_version(self, version_id: str, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT run.result_json
                FROM plot_versions AS version
                JOIN plot_runs AS run ON run.run_id = version.run_id
                WHERE version.version_id = ? AND run.project_id = ?
                """,
                (version_id, project_id),
            ).fetchone()
        return json.loads(row["result_json"]) if row is not None else None

    def initialize_assistant_execution(self, turn_id: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO assistant_execution (turn_id, status) VALUES (?, 'running')",
                (turn_id,),
            )

    def assistant_execution(self, turn_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM assistant_execution WHERE turn_id = ?",
                (turn_id,),
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        for key in ("response", "question", "answer_batches", "error"):
            encoded = record.pop(key + "_json")
            record[key] = json.loads(encoded) if encoded is not None else None
        return record

    def update_assistant_execution(
        self,
        turn_id: str,
        *,
        status: str,
        response: dict[str, Any] | None = None,
        question: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """UPDATE assistant_execution SET status = ?, response_json = ?,
                   question_json = ?, error_json = ?, revision = revision + 1 WHERE turn_id = ?""",
                (
                    status,
                    json.dumps(response) if response is not None else None,
                    json.dumps(question) if question is not None else None,
                    json.dumps(error) if error is not None else None,
                    turn_id,
                ),
            )

    def append_assistant_activity(self, turn_id: str, entry: dict[str, Any]) -> None:
        with self._lock, self._connection:
            sequence = self._connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM assistant_activity WHERE turn_id = ?",
                (turn_id,),
            ).fetchone()[0]
            self._connection.execute(
                "INSERT INTO assistant_activity (turn_id, sequence, entry_json) VALUES (?, ?, ?)",
                (turn_id, sequence, json.dumps({**entry, "sequence": sequence})),
            )
            self._connection.execute(
                "UPDATE assistant_execution SET revision = revision + 1 WHERE turn_id = ?",
                (turn_id,),
            )

    def assistant_activity(self, turn_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT entry_json FROM assistant_activity WHERE turn_id = ? ORDER BY sequence",
                (turn_id,),
            ).fetchall()
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            entry = json.loads(row["entry_json"])
            latest[entry["step_id"]] = entry
        return list(latest.values())

    def claim_assistant_answer(self, turn_id: str, payload: dict[str, Any]) -> bool:
        with self._lock, self._connection:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                "SELECT * FROM assistant_execution WHERE turn_id = ?",
                (turn_id,),
            ).fetchone()
            if row is None:
                raise RequestConflictError("The request is no longer available.")
            batches = json.loads(row["answer_batches_json"])
            for batch in batches:
                if batch["answer"]["interaction_id"] == payload["interaction_id"]:
                    if batch["answer"] != payload:
                        raise RequestConflictError("This question already has a different answer.")
                    return False
            question = json.loads(row["question_json"]) if row["question_json"] else None
            if (
                row["status"] != "awaiting_input"
                or question is None
                or question["interaction_id"] != payload["interaction_id"]
            ):
                raise RequestConflictError("This question is no longer waiting for an answer.")
            batches.append({"question": question, "answer": payload})
            self._connection.execute(
                """UPDATE assistant_execution SET status = 'running', question_json = NULL,
                   response_json = NULL, answer_batches_json = ?, revision = revision + 1
                   WHERE turn_id = ?""",
                (json.dumps(batches), turn_id),
            )
        return True

    def running_assistant_ids(self) -> list[str]:
        with self._lock:
            return [
                str(row[0])
                for row in self._connection.execute(
                    "SELECT turn_id FROM assistant_execution WHERE status = 'running'",
                ).fetchall()
            ]

    def current_project_results(self, project_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT run.result_json FROM plots AS plot
                   JOIN plot_versions AS version ON version.version_id = plot.current_version_id
                   JOIN plot_runs AS run ON run.run_id = version.run_id
                   WHERE plot.project_id = ? ORDER BY version.created_at DESC LIMIT 8""",
                (project_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_figure_results(
        self, project_id: str, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT run.result_json FROM plots AS plot
                   JOIN plot_versions AS version ON version.version_id = plot.current_version_id
                   JOIN plot_runs AS run ON run.run_id = version.run_id
                   WHERE plot.project_id = ? ORDER BY version.created_at DESC, plot.plot_id
                   LIMIT 30 OFFSET ?""",
                (project_id, offset),
            ).fetchall()
            total = self._connection.execute(
                "SELECT count(*) FROM plots WHERE project_id = ? "
                "AND current_version_id IS NOT NULL",
                (project_id,),
            ).fetchone()[0]
        return [json.loads(row[0]) for row in rows], total

    def turn_id_for_run(self, run_id: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT turn_id FROM assistant_turns WHERE run_id = ?", (run_id,)
            ).fetchone()
        return str(row["turn_id"]) if row is not None else None

    def append_developer_trace(
        self,
        *,
        turn_id: str,
        run_id: str | None,
        entry: DeveloperTraceEntry,
    ) -> DeveloperTraceEntry:
        with self._lock, self._connection:
            row = self._connection.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) + 1 AS value
                FROM developer_traces
                WHERE turn_id = ?
                """,
                (turn_id,),
            ).fetchone()
            persisted = entry.model_copy(update={"sequence": int(row["value"])})
            self._connection.execute(
                """
                INSERT INTO developer_traces (
                    trace_id, turn_id, run_id, sequence, kind, actor, name, status,
                    occurred_at, duration_ms, input_json, output_json, error_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    persisted.trace_id,
                    turn_id,
                    run_id,
                    persisted.sequence,
                    persisted.kind.value,
                    persisted.actor,
                    persisted.name,
                    persisted.status.value,
                    persisted.occurred_at.isoformat(),
                    persisted.duration_ms,
                    json.dumps(persisted.input) if persisted.input is not None else None,
                    json.dumps(persisted.output) if persisted.output is not None else None,
                    json.dumps(persisted.error) if persisted.error is not None else None,
                ),
            )
        return persisted

    def list_developer_trace(self, turn_id: str) -> list[DeveloperTraceEntry]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT * FROM developer_traces
                WHERE turn_id = ?
                ORDER BY sequence ASC
                """,
                (turn_id,),
            ).fetchall()
        return [
            DeveloperTraceEntry(
                trace_id=row["trace_id"],
                sequence=row["sequence"],
                kind=row["kind"],
                actor=row["actor"],
                name=row["name"],
                status=row["status"],
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
                duration_ms=row["duration_ms"],
                input=(json.loads(row["input_json"]) if row["input_json"] is not None else None),
                output=(json.loads(row["output_json"]) if row["output_json"] is not None else None),
                error=(json.loads(row["error_json"]) if row["error_json"] is not None else None),
            )
            for row in rows
        ]

    def next_event_sequence(self, run_id: str) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS value FROM run_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return int(row["value"])

    def add_event(self, event: RunEvent) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO run_events (
                    event_id, run_id, sequence, type, occurred_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.run_id,
                    event.sequence,
                    event.type,
                    event.occurred_at.isoformat(),
                    json.dumps(event.payload.model_dump(mode="json")),
                ),
            )

    def append_event(
        self,
        *,
        event_id: str,
        run_id: str,
        event_type: EventType,
        occurred_at: datetime,
        payload: dict[str, object],
    ) -> RunEvent:
        with self._lock, self._connection:
            row = self._connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS value FROM run_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            event = build_run_event(
                event_id=event_id,
                run_id=run_id,
                sequence=int(row["value"]),
                event_type=event_type,
                occurred_at=occurred_at,
                payload=payload,
            )
            self._connection.execute(
                """
                INSERT INTO run_events (
                    event_id, run_id, sequence, type, occurred_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.run_id,
                    event.sequence,
                    event.type,
                    event.occurred_at.isoformat(),
                    json.dumps(event.payload.model_dump(mode="json")),
                ),
            )
        return event

    def list_events(self, run_id: str, *, after_sequence: int = 0) -> list[RunEvent]:
        with self._lock:
            rows: Iterable[sqlite3.Row] = self._connection.execute(
                """
                SELECT * FROM run_events
                WHERE run_id = ? AND sequence > ?
                ORDER BY sequence ASC
                """,
                (run_id, after_sequence),
            ).fetchall()
        return [
            RUN_EVENT_ADAPTER.validate_python(
                {
                    "event_id": row["event_id"],
                    "run_id": row["run_id"],
                    "sequence": row["sequence"],
                    "type": row["type"],
                    "occurred_at": datetime.fromisoformat(row["occurred_at"]),
                    "payload": json.loads(row["payload_json"]),
                }
            )
            for row in rows
        ]

    def sequence_for_event(self, run_id: str, event_id: str) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT sequence FROM run_events WHERE run_id = ? AND event_id = ?",
                (run_id, event_id),
            ).fetchone()
        return int(row["sequence"]) if row is not None else 0

    def create_artifact(
        self,
        *,
        artifact_id: str,
        run_id: str,
        media_type: str,
        filename: str,
        storage_path: Path,
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO artifacts (artifact_id, run_id, media_type, filename, storage_path)
                VALUES (?, ?, ?, ?, ?)
                """,
                (artifact_id, run_id, media_type, filename, str(storage_path)),
            )

    def get_artifact(self, artifact_id: str) -> dict[str, str] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        return dict(row) if row is not None else None
