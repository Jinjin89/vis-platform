"""Deterministic planning fixtures; production planning remains model-driven."""

from vis_platform_backend.contracts.research import ResearchPlan


def transcriptomic_plan(objects: list[dict], *, spatial: bool) -> ResearchPlan:
    coordinates_name, annotations_name = (
        ("Spatial coordinates", "Spot annotations")
        if spatial
        else ("Cell embedding", "Cell annotations")
    )
    names = {item["name"]: item for item in objects}
    selected = {"coordinates": names[coordinates_name], "annotations": names[annotations_name]}
    key, group, x, y = (
        ("spot_id", "tissue_domain", "x_um", "y_um")
        if spatial
        else ("cell_id", "cell_type", "embedding_1", "embedding_2")
    )
    title = "Spatial domains" if spatial else "Single-cell populations"
    y_limits = f"ylim=rev(range(d${y})), " if spatial else ""
    return ResearchPlan.model_validate(
        {
            "title": title,
            "figure_size": {"width": 8, "height": 6} if spatial else {"width": 7, "height": 7},
            "description": "A figure of the selected synthetic transcriptomic collection.",
            "inputs": [
                {
                    "alias": alias,
                    "reference": {
                        "object_id": item["object_id"],
                        "revision_id": item["revision_id"],
                    },
                }
                for alias, item in selected.items()
            ],
            "relationships": [
                {
                    "relationship_id": "coordinates-to-annotations",
                    "left_object_id": selected["coordinates"]["object_id"],
                    "right_object_id": selected["annotations"]["object_id"],
                    "kind": "join",
                    "left_key": key,
                    "right_key": key,
                    "cardinality": "one_to_one",
                }
            ],
            "analysis_code": (
                "list(points=merge(inputs$coordinates, inputs$annotations, "
                f'by="{key}", sort=FALSE))'
            ),
            "outputs": [
                {
                    "key": "points",
                    "name": title,
                    "description": "Coordinates joined to their matching annotations.",
                }
            ],
            "render_code": f"d <- results$points; g <- factor(d${group}); "
            'colors <- hcl.colors(nlevels(g), "Dark 3"); '
            f"par(mar=c(4,4,2,1)); plot(d${x}, d${y}, "
            f"col=colors[g], pch=16, cex=.7, asp=1, {y_limits}"
            f'xlab="{x}", ylab="{y}", main=params$title); '
            'legend("topright", legend=levels(g), col=colors, pch=16, cex=.65, bty="n")',
            "controls": [{"id": "title", "label": "Title", "type": "text", "value": title}],
        }
    )
