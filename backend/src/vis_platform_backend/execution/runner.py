from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4


class RExecutionError(RuntimeError):
    def __init__(self, message: str, diagnostic: str = "") -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


@dataclass(frozen=True)
class WorkerOutput:
    directory: Path
    response: dict[str, Any]


class RWorker:
    def __init__(self, r_home: Path | None, sandbox: Path | None, work_root: Path) -> None:
        self.r_home = r_home.resolve() if r_home else None
        self.sandbox = sandbox.resolve() if sandbox else None
        self.work_root = work_root.resolve()
        self._slots = asyncio.Semaphore(2)
        self.available = self._probe()

    def _probe(self) -> bool:
        if (
            self.r_home is None
            or self.sandbox is None
            or not (self.r_home / "bin/exec/R").is_file()
            or not self.sandbox.is_file()
            or not self.sandbox.with_suffix(".so").is_file()
        ):
            return False
        try:
            return (
                subprocess.run(
                    [str(self.sandbox), "--check"], capture_output=True, timeout=3, check=False
                ).returncode
                == 0
            )
        except (OSError, subprocess.TimeoutExpired):
            return False

    async def verify(self) -> None:
        if not self.available:
            return
        try:
            probe = await self.execute({"mode": "check"}, {})
            self.available = probe.response.get("ready") is True
            shutil.rmtree(probe.directory.parent, ignore_errors=True)
        except (RExecutionError, OSError, TimeoutError):
            self.available = False

    async def execute(
        self, payload: dict[str, Any], inputs: dict[str, tuple[Path, str]]
    ) -> WorkerOutput:
        if not self.available or self.r_home is None or self.sandbox is None:
            raise RExecutionError("The restricted R runtime is unavailable.")
        async with self._slots:
            root = self.work_root / f"job_{uuid4().hex}"
            source_dir, output_dir = root / "inputs", root / "outputs"
            source_dir.mkdir(parents=True)
            output_dir.mkdir()
            materialized = {}
            for index, (alias, (path, format_name)) in enumerate(inputs.items()):
                destination = source_dir / f"input-{index}.{format_name}"
                shutil.copyfile(path, destination)
                materialized[alias] = {"path": str(destination), "format": format_name}
            job = {
                **payload,
                "output_dir": str(output_dir),
                "inputs": materialized,
                "job_dir": str(root),
                "sandbox_library": str(root / "sandbox.so"),
            }
            if payload.get("mode") == "profile":
                job["input"] = next(iter(materialized.values()))
            shutil.copyfile(self.sandbox.with_suffix(".so"), root / "sandbox.so")
            script = root / "worker.R"
            shutil.copyfile(Path(__file__).with_name("worker.R"), script)
            manifest = root / "job.json"
            manifest.write_text(json.dumps(job), encoding="utf-8")
            environment = {
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "R_HOME": str(self.r_home),
                "R_LIBS_SITE": str(self.r_home / "site-library"),
                "R_LIBS_USER": str(source_dir / "no-user-library"),
                "LD_LIBRARY_PATH": str(self.r_home / "lib"),
                "TMPDIR": str(output_dir),
                "OPENBLAS_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
            }
            log = (output_dir / "worker.log").open("wb")
            process = await asyncio.create_subprocess_exec(
                str(self.sandbox),
                "--bootstrap",
                str(self.r_home),
                str(root),
                str(output_dir),
                str(self.r_home / "bin/exec/R"),
                "--vanilla",
                "--slave",
                "-f",
                str(script),
                "--args",
                str(manifest),
                cwd=output_dir,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=log,
                start_new_session=True,
            )
            log.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=45)
            except (TimeoutError, asyncio.CancelledError):
                if process.returncode is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
                shutil.rmtree(root, ignore_errors=True)
                raise
            response_path = output_dir / "response.json"
            if (
                response_path.is_symlink()
                or not response_path.is_file()
                or response_path.stat().st_size > 1024 * 1024
            ):
                raise RExecutionError(
                    "The analysis did not produce a valid result description.",
                    f"R worker exit status: {process.returncode}",
                )
            try:
                response = json.loads(response_path.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError) as error:
                raise RExecutionError("The analysis result could not be read.") from error
            if not isinstance(response, dict):
                raise RExecutionError("The analysis result description is invalid.")
            if process.returncode != 0 or "error" in response:
                diagnostic = str(response.get("error", "R execution failed"))[:3000].replace(
                    str(root), "<job>"
                )
                shutil.rmtree(root, ignore_errors=True)
                raise RExecutionError(
                    "The analysis could not be completed with these inputs.", diagnostic
                )
            return WorkerOutput(directory=output_dir, response=response)


def output_file(output: WorkerOutput, filename: str) -> Path:
    path = output.directory / filename
    if (
        Path(filename).name != filename
        or path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 64 * 1024 * 1024
    ):
        raise RExecutionError("The worker returned an invalid output file.")
    return path
