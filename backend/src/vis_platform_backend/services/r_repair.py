from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from vis_platform_backend.agents.r_repair import RRepairAgent
from vis_platform_backend.contracts.figures import FigureSize
from vis_platform_backend.contracts.plot_runs import EventType
from vis_platform_backend.execution.runner import (
    RExecutionError,
    RWorker,
    WorkerOutput,
    output_file,
)
from vis_platform_backend.infrastructure.database import Repository
from vis_platform_backend.services.figure_svg import validate_svg

MAX_R_REPAIRS = 3


class RepairingRExecution:
    def __init__(self, worker: RWorker, repository: Repository, agent: RRepairAgent | None) -> None:
        self.worker, self.repository, self.agent = worker, repository, agent

    async def execute(
        self,
        run_id: str,
        job: dict[str, Any],
        inputs: dict[str, tuple[Path, str]],
        context: dict[str, Any],
    ) -> tuple[WorkerOutput, str]:
        job = dict(job)
        while True:
            output = None
            try:
                output = await self.worker.execute(job, inputs)
                if job["mode"] == "render":
                    validate_svg(
                        output_file(output, "preview.svg"),
                        FigureSize.model_validate(job["figure_size"]),
                    )
                return output, str(job["code"])
            except RExecutionError as error:
                if output is not None:
                    shutil.rmtree(output.directory.parent, ignore_errors=True)
                record = self.repository.get_run(run_id)
                assert record is not None
                interaction = record["interaction"]
                # Keep private diagnostics after failed worker files are removed.
                interaction["r_execution_errors"] = [
                    *interaction.get("r_execution_errors", []),
                    {"phase": job["mode"], "diagnostic": (error.diagnostic or str(error))[:3000]},
                ][-(MAX_R_REPAIRS + 1) :]
                self.repository.update_interaction(run_id, interaction)
                attempts = int(interaction.get("r_repair_attempts", 0))
                if self.agent is None:
                    raise
                if attempts >= MAX_R_REPAIRS:
                    raise RExecutionError(
                        "R execution still failed after automatic repair. "
                        "Your previous plot is unchanged.",
                        error.diagnostic,
                    ) from error
                self.repository.update_interaction(
                    run_id,
                    {
                        **interaction,
                        "r_repair_attempts": attempts + 1,
                    },
                )
                self.repository.append_event(
                    event_id="event_" + uuid4().hex,
                    run_id=run_id,
                    event_type=EventType.PROGRESS_UPDATED,
                    occurred_at=datetime.now(UTC),
                    payload={
                        "status": "running",
                        "stage": "running_r",
                        "progress": 40,
                        "message": "Correcting an R execution error and retrying.",
                    },
                )
                repaired = await self.agent.repair(
                    {
                        **context,
                        "execution": dict(job),
                        "user_request": record["request"].get("request", {}),
                        "diagnostic": error.diagnostic or str(error),
                        "attempt": attempts + 1,
                    }
                )
                job["code"] = repaired.code
