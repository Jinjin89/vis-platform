from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vis_platform_backend.contracts.datasets import (
    ColumnDescription,
    NumericProfile,
    ObjectDescription,
)


@dataclass(frozen=True)
class ParsedObject:
    selector: str
    description: ObjectDescription
    path: Path


def content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def profile_rows(names: list[str], rows: list[dict[str, Any]]) -> list[ColumnDescription]:
    columns = []
    for name in names:
        values = [row.get(name) for row in rows]
        present = [value for value in values if value is not None and str(value).strip() != ""]
        numbers = []
        for value in present:
            try:
                number = float(value)
                if not math.isfinite(number):
                    break
                numbers.append(number)
            except (TypeError, ValueError):
                break
        numeric = bool(present) and len(numbers) == len(present)
        columns.append(
            ColumnDescription(
                name=name,
                data_type="number" if numeric else "string" if present else "unknown",
                missing_count=len(values) - len(present),
                unique_count=len({str(value) for value in present}),
                numeric=NumericProfile(
                    minimum=min(numbers),
                    maximum=max(numbers),
                    mean=math.fsum(numbers) / len(numbers),
                )
                if numeric
                else None,
            )
        )
    return columns


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        names = list(reader.fieldnames or [])
        if (
            not names
            or len(names) > 2000
            or len(names) != len(set(names))
            or any(not name.strip() for name in names)
        ):
            raise ValueError("Tables require unique nonempty column names (up to 2,000 columns).")
        rows: list[dict[str, str]] = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Rows do not match the table's column headers.")
            rows.append(row)
            if len(rows) > 250_000:
                raise ValueError("This table exceeds the current 250,000-row inspection limit.")
        return names, rows


def parse_file(
    path: Path,
    name: str,
    owner_id: str,
    revision_id: str,
    output_dir: Path,
    object_path: list[str | int] | None = None,
) -> list[ParsedObject]:
    suffix = Path(name).suffix.lower()
    tables: dict[str, tuple[list[str], list[dict[str, Any]]]] = {}
    if object_path and suffix not in {".json", ".jsonl", ".ndjson"}:
        raise ValueError("This format does not support nested object selectors.")
    if suffix in {".csv", ".tsv", ".txt"}:
        raw = path.read_text(encoding="utf-8-sig")
        reader = csv.DictReader(io.StringIO(raw), delimiter="\t" if suffix == ".tsv" else ",")
        names = list(reader.fieldnames or [])
        rows = list(reader)
        if (
            len(rows) > 250_000
            or not names
            or len(names) > 2000
            or len(names) != len(set(names))
            or any(not key.strip() for key in names)
        ):
            raise ValueError(
                "The table requires unique headers and at most 250,000 rows and 2,000 columns."
            )
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise ValueError("Rows do not match the table's column headers.")
        tables[Path(name).stem] = (names, rows)
    elif suffix in {".json", ".jsonl", ".ndjson"}:
        raw = path.read_text(encoding="utf-8-sig")
        payload = (
            [json.loads(line) for line in raw.splitlines() if line.strip()]
            if suffix != ".json"
            else json.loads(raw)
        )
        for step in object_path or []:
            if isinstance(step, int):
                if not isinstance(payload, list) or not 0 <= step < len(payload):
                    raise ValueError("The selected list entry is not present in this JSON file.")
                payload = payload[step]
            else:
                if not isinstance(payload, dict) or step not in payload:
                    raise ValueError("The selected object key is not present in this JSON file.")
                payload = payload[step]
        candidates = payload if isinstance(payload, dict) else {Path(name).stem: payload}
        for key, value in candidates.items():
            if isinstance(value, list) and value and all(isinstance(row, dict) for row in value):
                if any(isinstance(cell, (dict, list)) for row in value for cell in row.values()):
                    continue
                names = list(dict.fromkeys(column for row in value for column in row))
                if not names or len(names) > 2000 or len(value) > 250_000:
                    raise ValueError("This JSON table exceeds current inspection limits.")
                tables[str(key)] = (names, value)
        if not tables:
            raise ValueError("JSON must contain a table or named arrays of flat records.")
    else:
        return [
            ParsedObject(
                selector=name,
                path=path,
                description=ObjectDescription(
                    object_id="",
                    revision_id=revision_id,
                    owner_id=owner_id,
                    name=name,
                    kind="unknown",
                    format=suffix.lstrip(".") or "unknown",
                    readiness="unsupported",
                    description="Stored original file.",
                    content_hash=content_hash(path),
                    limitations=["A compatible parser is required before this object can be used."],
                ),
            )
        ]
    parsed = []
    for index, (selector, (names, rows)) in enumerate(tables.items()):
        target = output_dir / f"table-{index}.csv"
        with target.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=names)
            writer.writeheader()
            writer.writerows(rows)
        parsed.append(
            ParsedObject(
                selector=selector,
                path=target,
                description=ObjectDescription(
                    object_id="",
                    revision_id=revision_id,
                    owner_id=owner_id,
                    name=selector,
                    format="csv",
                    dimensions=[len(rows), len(names)],
                    columns=profile_rows(names, rows),
                    capabilities=["inspect", "materialize"],
                    description=f"Table with {len(rows):,} rows and {len(names)} columns.",
                    content_hash=content_hash(target),
                ),
            )
        )
    return parsed
