from __future__ import annotations

import json
from pathlib import Path

from vis_platform_backend.app import create_app
from vis_platform_backend.contracts.figure_composition_content import FigureCompositionContent
from vis_platform_backend.contracts.figure_composition_operations import FigureOperationsRequest
from vis_platform_backend.contracts.plot_runs import RUN_EVENT_ADAPTER
from vis_platform_backend.contracts.report_content import LegacyReportContent
from vis_platform_backend.contracts.report_operations import ReportOperationsRequest
from vis_platform_backend.contracts.reports import ReportContent
from vis_platform_backend.contracts.slides import SlideDeckContent
from vis_platform_backend.data.providers import SourceManifest

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"


def main() -> None:
    CONTRACTS.mkdir(parents=True, exist_ok=True)
    app = create_app()
    (CONTRACTS / "analysis-platform-source-v1.schema.json").write_text(
        json.dumps(SourceManifest.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )
    (CONTRACTS / "figure-composition-v1.schema.json").write_text(
        json.dumps(FigureCompositionContent.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )
    (CONTRACTS / "figure-composition-operations-v1.schema.json").write_text(
        json.dumps(FigureOperationsRequest.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )
    (CONTRACTS / "slide-deck-v1.schema.json").write_text(
        json.dumps(SlideDeckContent.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )
    (CONTRACTS / "report-content-v1.schema.json").write_text(
        json.dumps(LegacyReportContent.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )
    (CONTRACTS / "report-content-v2.schema.json").write_text(
        json.dumps(ReportContent.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )
    (CONTRACTS / "report-operations-v1.schema.json").write_text(
        json.dumps(ReportOperationsRequest.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )
    (CONTRACTS / "openapi-v1.json").write_text(
        json.dumps(app.openapi(), indent=2) + "\n",
        encoding="utf-8",
    )
    (CONTRACTS / "run-events-v1.schema.json").write_text(
        json.dumps(RUN_EVENT_ADAPTER.json_schema(), indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
