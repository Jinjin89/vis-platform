"""Small, deterministic synthetic collections using the platform source contract."""

from __future__ import annotations

import asyncio
import csv
import math
import random
import shutil
from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import Any

from vis_platform_backend.contracts.datasets import (
    ObjectRelationship,
    PlatformDatasetList,
    PlatformDatasetSummary,
)
from vis_platform_backend.data.profiling import content_hash, profile_rows
from vis_platform_backend.data.providers import (
    PlatformConnectionError,
    SourceManifest,
    SourceObject,
    SourceObjectDescription,
)

SINGLE_CELL_ID = "demo.single-cell"
SPATIAL_ID = "demo.spatial"
DEMO_SOURCE_IDS = frozenset({SINGLE_CELL_ID, SPATIAL_ID})
REVISION = "synthetic-v1"
HOUSEKEEPING = ("GAPDH", "ACTB", "RPLP0", "PPIA", "MALAT1", "B2M", "MT-CO1", "MT-ND1")
SINGLE_MARKERS = {
    "T cells": ("CD3D", "CD3E", "IL7R", "LTB"),
    "B cells": ("MS4A1", "CD79A", "CD74", "CD37"),
    "Monocytes": ("LYZ", "S100A8", "LST1", "FCN1"),
    "NK cells": ("NKG7", "GNLY", "PRF1", "KLRD1"),
}
SPATIAL_MARKERS = {
    "Epithelial region": ("EPCAM", "KRT8", "KRT18", "KRT19"),
    "Stromal region": ("COL1A1", "COL1A2", "DCN", "LUM"),
    "Immune region": ("PTPRC", "CD3D", "MS4A1", "LYZ"),
    "Vascular region": ("PECAM1", "VWF", "KDR", "EMCN"),
}


def _poisson(rng: random.Random, rate: float) -> int:
    threshold, product, count = math.exp(-rate), 1.0, 0
    while product > threshold:
        product *= rng.random()
        count += 1
    return max(0, count - 1)


def _expression(
    rng: random.Random,
    genes: list[str],
    weights: dict[str, float],
    markers: Mapping[str, tuple[str, ...]],
) -> dict[str, int]:
    depth = rng.uniform(0.7, 1.5)
    counts = {}
    for gene in genes:
        rate = (
            5.0
            if gene in HOUSEKEEPING
            else 0.35
            + sum(16 * weight for group, weight in weights.items() if gene in markers[group])
        )
        counts[gene] = 0 if rng.random() < 0.12 else _poisson(rng, depth * rate)
    return counts


def _normalized(counts: dict[str, int]) -> dict[str, float]:
    total = max(1, sum(counts.values()))
    return {gene: round(math.log1p(value / total * 10_000), 6) for gene, value in counts.items()}


class DemoTranscriptomicsProvider:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = Lock()
        self._manifests: dict[str, SourceManifest] = {}
        self._files: dict[str, Path] = {}

    async def discover(self, cursor: str | None = None) -> PlatformDatasetList:
        await asyncio.to_thread(self._ensure)
        return PlatformDatasetList(
            connected=False,
            datasets=[
                PlatformDatasetSummary(
                    source_id=item.source_id,
                    revision=item.revision,
                    name=item.name,
                    description=item.description,
                    object_count=len(item.objects),
                    contains_demo_data=True,
                )
                for item in self._manifests.values()
            ],
        )

    async def describe(self, source_id: str) -> SourceManifest:
        await asyncio.to_thread(self._ensure)
        manifest = self._manifests.get(source_id)
        if manifest is None:
            raise PlatformConnectionError("The demo collection was not found.")
        return manifest.model_copy(deep=True)

    async def materialize(self, item: SourceObject, destination: Path) -> None:
        await asyncio.to_thread(self._ensure)
        path = self._files.get(item.content_path)
        if path is None or item.sha256 != content_hash(path):
            raise PlatformConnectionError("The demo object reference is invalid.")
        shutil.copyfile(path, destination)

    def _ensure(self) -> None:
        with self._lock:
            if self._manifests:
                return
            self.root.mkdir(parents=True, exist_ok=True)
            self._single_cell()
            self._spatial()

    def _table(
        self,
        source_id: str,
        key: str,
        name: str,
        description: str,
        rows: list[dict[str, Any]],
        observation_unit: str,
        *,
        units: dict[str, str] | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> SourceObject:
        directory = self.root / source_id / REVISION
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{key}.csv"
        fields = list(rows[0])
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        columns = profile_rows(fields, rows)
        for column in columns:
            if units and column.name in units:
                column.unit, column.meaning_origin = units[column.name], "source"
        locator = f"builtin-demo/{source_id}/{REVISION}/{key}.csv"
        self._files[locator] = path
        return SourceObject(
            source_object_id=key,
            content_path=locator,
            sha256=content_hash(path),
            description=SourceObjectDescription(
                name=name,
                description=description,
                kind="table",
                format="csv",
                dimensions=[len(rows), len(fields)],
                columns=columns,
                observation_unit=observation_unit,
                description_origin="source",
                extensions={"synthetic": True, **(extensions or {})},
            ),
        )

    @staticmethod
    def _relationships(key: str, annotation: str, coordinate: str) -> list[ObjectRelationship]:
        return [
            ObjectRelationship(
                relationship_id=f"{left}-to-{annotation}",
                left_object_id=left,
                right_object_id=annotation,
                kind="join",
                left_key=key,
                right_key=key,
                cardinality="one_to_one",
                description=f"Match the same {key} values; row order is not the relationship.",
            )
            for left in ("counts", "expression", coordinate)
        ] + [
            ObjectRelationship(
                relationship_id="expression-to-coordinates",
                left_object_id="expression",
                right_object_id=coordinate,
                kind="join",
                left_key=key,
                right_key=key,
                cardinality="one_to_one",
                description="Align gene expression with the corresponding coordinates.",
            ),
            ObjectRelationship(
                relationship_id="gene-annotations",
                left_object_id="genes",
                right_object_id="expression",
                kind="related",
                description=(
                    "Gene symbols in the gene table name the gene columns in counts "
                    "and normalized expression."
                ),
            ),
        ]

    def _gene_table(self, source_id: str, markers: Mapping[str, tuple[str, ...]]) -> SourceObject:
        genes = [gene for group in markers.values() for gene in group] + list(HOUSEKEEPING)
        rows = [
            {
                "gene_id": f"demo:{gene}",
                "symbol": gene,
                "simulation_group": next(
                    (group for group, panel in markers.items() if gene in panel),
                    "Shared expression",
                ),
            }
            for gene in genes
        ]
        return self._table(
            source_id,
            "genes",
            "Gene annotations",
            (
                "A 24-gene demonstration panel. Associations describe the "
                "simulation and are not validated biological findings."
            ),
            rows,
            "gene",
        )

    def _single_cell(self) -> None:
        rng = random.Random(20260911)
        genes = [gene for panel in SINGLE_MARKERS.values() for gene in panel] + list(HOUSEKEEPING)
        labels = list(SINGLE_MARKERS)
        centers = [(-4.5, 2.5), (3.5, 3.0), (-2.0, -3.5), (4.2, -2.3)]
        cells, counts_rows, expression_rows, embedding = [], [], [], []
        for index in range(360):
            group_index = index % len(labels)
            group, cell_id = labels[group_index], f"cell_{index + 1:04d}"
            counts = _expression(rng, genes, {group: 1}, SINGLE_MARKERS)
            cells.append(
                {
                    "cell_id": cell_id,
                    "cell_type": group,
                    "donor_id": f"donor_{index % 3 + 1}",
                    "condition": "Control" if (index // 12) % 2 == 0 else "Treatment",
                    "total_counts": sum(counts.values()),
                    "detected_genes": sum(value > 0 for value in counts.values()),
                    "mitochondrial_percent": round(
                        100
                        * sum(counts[gene] for gene in ("MT-CO1", "MT-ND1"))
                        / max(1, sum(counts.values())),
                        2,
                    ),
                }
            )
            counts_rows.append({"cell_id": cell_id, **counts})
            expression_rows.append({"cell_id": cell_id, **_normalized(counts)})
            cx, cy = centers[group_index]
            embedding.append(
                {
                    "cell_id": cell_id,
                    "embedding_1": round(rng.gauss(cx, 0.85), 5),
                    "embedding_2": round(rng.gauss(cy, 0.75), 5),
                }
            )
        objects = [
            self._table(
                SINGLE_CELL_ID,
                "cells",
                "Cell annotations",
                (
                    "360 simulated cells in four annotated populations and three "
                    "donors. QC totals refer only to this small gene panel."
                ),
                cells,
                "cell",
            ),
            self._table(
                SINGLE_CELL_ID,
                "counts",
                "Raw gene counts",
                (
                    "Synthetic integer counts, one row per cell and one column per "
                    "gene. No research samples were measured."
                ),
                counts_rows,
                "cell",
                units={gene: "counts" for gene in genes},
            ),
            self._table(
                SINGLE_CELL_ID,
                "expression",
                "Normalized gene expression",
                (
                    "log1p(counts / cell total × 10,000), calculated from the "
                    "supplied counts. Gene symbols are column names."
                ),
                expression_rows,
                "cell",
                units={gene: "log1p(CP10k)" for gene in genes},
            ),
            self._table(
                SINGLE_CELL_ID,
                "embedding",
                "Cell embedding",
                (
                    "Illustrative two-dimensional coordinates for the simulated "
                    "cells. These are not a computed UMAP or t-SNE result. Join to "
                    "cell annotations for population colors or expression for feature"
                    " plots."
                ),
                embedding,
                "cell",
                extensions={"method": "simulated coordinates"},
            ),
            self._gene_table(SINGLE_CELL_ID, SINGLE_MARKERS),
        ]
        self._manifests[SINGLE_CELL_ID] = SourceManifest(
            source_id=SINGLE_CELL_ID,
            revision=REVISION,
            name="Single-cell transcriptomics · Demo",
            description=(
                "360 simulated cells × 24 genes, with counts, normalized "
                "expression, cell annotations, and an illustrative embedding. "
                "Synthetic demonstration data only."
            ),
            contains_demo_data=True,
            objects=objects,
            relationships=self._relationships("cell_id", "cells", "embedding"),
        )

    def _spatial(self) -> None:
        rng = random.Random(20260912)
        genes = [gene for panel in SPATIAL_MARKERS.values() for gene in panel] + list(HOUSEKEEPING)
        labels = list(SPATIAL_MARKERS)
        spots: list[dict[str, Any]] = []
        positions, counts_rows, expression_rows = [], [], []
        for row in range(22):
            for column in range(26):
                x, y = (column - 12.5) / 12.5, (row - 10.5) / 10.5
                if x * x + y * y > 1:
                    continue
                spot_id = f"spot_{len(spots) + 1:04d}"
                weights = {
                    labels[0]: math.exp(-4 * (x * x + y * y)),
                    labels[1]: 0.3 + 0.8 * (x * x + y * y),
                    labels[2]: 1.8 * math.exp(-8 * ((x + 0.55) ** 2 + (y - 0.2) ** 2)),
                    labels[3]: 0.9 * math.exp(-55 * (y - 0.55 * x + 0.15) ** 2),
                }
                total = sum(weights.values())
                weights = {key: value / total for key, value in weights.items()}
                counts = _expression(rng, genes, weights, SPATIAL_MARKERS)
                spots.append(
                    {
                        "spot_id": spot_id,
                        "tissue_domain": max(weights, key=lambda key: weights[key]),
                        "section_id": "section_demo_1",
                        "total_counts": sum(counts.values()),
                        "detected_genes": sum(value > 0 for value in counts.values()),
                    }
                )
                positions.append(
                    {
                        "spot_id": spot_id,
                        "x_um": round(column * 55 + rng.uniform(-3, 3), 3),
                        "y_um": round(row * 55 + rng.uniform(-3, 3), 3),
                        "array_row": row,
                        "array_column": column,
                    }
                )
                counts_rows.append({"spot_id": spot_id, **counts})
                expression_rows.append({"spot_id": spot_id, **_normalized(counts)})
        objects = [
            self._table(
                SPATIAL_ID,
                "spots",
                "Spot annotations",
                (
                    "Simulated tissue domains on one synthetic tissue section. Panel "
                    "totals are not whole-transcriptome QC measurements."
                ),
                spots,
                "spot",
            ),
            self._table(
                SPATIAL_ID,
                "positions",
                "Spatial coordinates",
                (
                    "Spot centers in micrometers on a synthetic tissue footprint; "
                    "array indices identify grid positions. Plot with equal x/y "
                    "scaling to preserve geometry."
                ),
                positions,
                "spot",
                units={"x_um": "µm", "y_um": "µm"},
                extensions={
                    "coordinate_system": "synthetic tissue plane",
                    "y_direction": "increases down the tissue array",
                },
            ),
            self._table(
                SPATIAL_ID,
                "counts",
                "Raw gene counts",
                (
                    "Synthetic integer transcript counts, with spot identifiers and "
                    "gene-symbol columns."
                ),
                counts_rows,
                "spot",
                units={gene: "counts" for gene in genes},
            ),
            self._table(
                SPATIAL_ID,
                "expression",
                "Normalized gene expression",
                (
                    "log1p(counts / spot total × 10,000), calculated from the "
                    "supplied counts. Join spot_id to spatial coordinates for gene "
                    "maps."
                ),
                expression_rows,
                "spot",
                units={gene: "log1p(CP10k)" for gene in genes},
            ),
            self._gene_table(SPATIAL_ID, SPATIAL_MARKERS),
        ]
        self._manifests[SPATIAL_ID] = SourceManifest(
            source_id=SPATIAL_ID,
            revision=REVISION,
            name="Spatial transcriptomics · Demo",
            description=(
                f"{len(spots)} simulated tissue spots × 24 genes, with counts, "
                "normalized expression, domain annotations, and physical coordinates. "
                "Synthetic demonstration data only."
            ),
            contains_demo_data=True,
            objects=objects,
            relationships=self._relationships("spot_id", "spots", "positions"),
        )
