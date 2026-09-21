"""Expose a saved version's R program without exposing execution storage."""

from __future__ import annotations

import json
from typing import Any

from vis_platform_backend.contracts.datasets import ObjectReference
from vis_platform_backend.contracts.plot_source import PlotSource


def saved_plot_source(record: dict[str, Any]) -> PlotSource:
    result = record["result"]
    spec = record["interaction"].get("render_spec") or {}
    plan = spec.get("plan") or {}
    render_code = plan.get("render_code")
    parameters = spec.get("parameters") or {}
    code = None
    if render_code:
        size = spec.get("figure_size") or plan.get("figure_size") or {"width": 9, "height": 6}
        encoded = json.dumps(json.dumps(parameters, ensure_ascii=True))
        lines = [
            "# Supply saved analysis objects as a named results list.",
            "# This version runs independently; no parent plot is executed.",
            'plot_main <- function(results, output_file = "plot.svg") {',
            f"  params <- jsonlite::fromJSON({encoded}, simplifyVector = FALSE)",
            f"  set.seed({int(plan.get('random_seed', 1))})",
            f"  grDevices::svg(output_file, width = {float(size['width'])}, "
            f"height = {float(size['height'])}, bg = 'white')",
            "  on.exit(grDevices::dev.off(), add = TRUE)",
            "  par(mar = c(4.1, 4.1, 2.1, 1.1))",
        ]
        if result.get("contains_demo_data"):
            lines.append("  par(oma = c(1.3, 0, 0, 0))")
        lines.extend("  " + line for line in render_code.splitlines())
        if result.get("contains_demo_data"):
            lines.append(
                '  mtext("Contains synthetic demonstration data", side = 1, outer = TRUE, '
                'line = 0.25, cex = 0.65, col = "#7b6d77")'
            )
        lines.extend(["}", ""])
        code = "\n".join(lines)
    return PlotSource(
        project_id=record["project_id"],
        plot_id=result["plot_id"],
        version_id=result["version_id"],
        code=code,
        render_code=render_code,
        parameters=parameters,
        input_objects=result.get("input_objects", []),
        result_bindings={
            obj["extensions"]["output_key"]: ObjectReference(
                object_id=obj["object_id"], revision_id=obj["revision_id"]
            )
            for analysis in result.get("analysis_results", [])
            for obj in analysis["objects"]
            if obj.get("extensions", {}).get("output_key")
        },
        message=(
            "Complete R plotting code with recorded parameters. Supply the saved analysis "
            "objects as the named results list; no parent plot needs to run."
            if code
            else "This illustrative version was rendered without R code."
        ),
    )
