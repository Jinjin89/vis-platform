"""Tables too large for row-by-row parsing: read by column and kept as Parquet."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pv
import pyarrow.parquet as pq

from vis_platform_backend.contracts.datasets import (
    ColumnDescription,
    NumericProfile,
    ObjectDescription,
)

# Delimited files up to this size keep the row-by-row path; larger ones are read by column.
SMALL_TABLE_BYTES = 32 * 1024 * 1024
MAX_ROWS = 20_000_000
MAX_COLUMNS = 2000
LARGE_TABLE_NOTE = (
    "Stored by column for large data. It can be shown as a point map; R analysis in this "
    "workspace reads smaller CSV or RDS objects."
)


def read_table(path: Path, suffix: str) -> pa.Table:
    """Read a whole delimited or Parquet table by column."""
    if suffix == ".parquet":
        table = pq.read_table(path)
    else:
        table = pv.read_csv(
            path,
            parse_options=pv.ParseOptions(delimiter="\t" if suffix == ".tsv" else ","),
            convert_options=pv.ConvertOptions(strings_can_be_null=True),
        )
    names = table.column_names
    if (
        not names
        or len(names) > MAX_COLUMNS
        or len(names) != len(set(names))
        or any(not str(name).strip() for name in names)
    ):
        raise ValueError(
            f"Tables require unique nonempty column names (up to {MAX_COLUMNS:,} columns)."
        )
    if table.num_rows > MAX_ROWS:
        raise ValueError(f"This table exceeds the current {MAX_ROWS:,}-row limit.")
    return table


def read_columns(path: Path, columns: list[str]) -> pa.Table:
    """Read only the named columns of a stored large table."""
    return pq.read_table(path, columns=columns)


def profile_table(table: pa.Table) -> list[ColumnDescription]:
    columns = []
    for name in table.column_names:
        values = table.column(name)
        kind = values.type
        numeric = pa.types.is_integer(kind) or pa.types.is_floating(kind)
        present = values
        if pa.types.is_floating(kind):
            present = pc.filter(values, pc.is_finite(values))
        missing = table.num_rows - (len(present) - present.null_count)
        profile = None
        if numeric and len(present) - present.null_count:
            extent = pc.min_max(present)
            profile = NumericProfile(
                minimum=float(extent["min"].as_py()),
                maximum=float(extent["max"].as_py()),
                mean=float(pc.mean(present).as_py()),
            )
        columns.append(
            ColumnDescription(
                name=name,
                data_type="number"
                if numeric
                else "boolean"
                if pa.types.is_boolean(kind)
                else "string"
                if missing < table.num_rows
                else "unknown",
                missing_count=missing,
                unique_count=int(pc.count_distinct(values).as_py()),
                numeric=profile,
            )
        )
    return columns


def store_table(
    table: pa.Table, target: Path, name: str, owner_id: str, revision_id: str
) -> ObjectDescription:
    pq.write_table(table, target, compression="zstd")
    return ObjectDescription(
        object_id="",
        revision_id=revision_id,
        owner_id=owner_id,
        name=name,
        format="parquet",
        dimensions=[table.num_rows, table.num_columns],
        columns=profile_table(table),
        capabilities=["inspect", "materialize"],
        description=(f"Large table with {table.num_rows:,} rows and {table.num_columns} columns."),
        limitations=[LARGE_TABLE_NOTE],
    )
