from collections.abc import Mapping, Sequence

from vis_platform_backend.contracts.figures import FigureSize
from vis_platform_backend.contracts.parameters import (
    ControlDefinition,
    ControlGroup,
    NumberControl,
    ParameterValue,
)

SIZE_CONTROL_IDS = frozenset({"figure_width", "figure_height"})


def figure_controls(
    controls: Sequence[ControlDefinition], groups: list[ControlGroup], size: FigureSize
) -> tuple[list[ControlDefinition], list[ControlGroup]]:
    """Geometry belongs to the renderer contract and is never optional model output."""
    remaining = [control for control in controls if control.id not in SIZE_CONTROL_IDS]
    dimensions: list[ControlDefinition] = [
        NumberControl(
            id=f"figure_{dimension}",
            label=f"Figure {dimension}",
            group="figure_size",
            value=getattr(size, dimension),
            minimum=2,
            maximum=30,
            step=0.01,
            unit="in",
            input_mode="number",
        )
        for dimension in ("width", "height")
    ]
    resolved_groups = [
        ControlGroup(id="figure_size", label="Figure size"),
        *[group for group in groups if group.id != "figure_size"],
    ]
    for control in remaining:
        if not any(group.id == control.group for group in resolved_groups):
            resolved_groups.append(
                ControlGroup(
                    id=control.group,
                    label="Appearance"
                    if control.group == "essential"
                    else control.group.replace("_", " ").title(),
                )
            )
    return [*dimensions, *remaining], resolved_groups


def resolve_figure_size(values: Mapping[str, ParameterValue], default: FigureSize) -> FigureSize:
    return FigureSize.model_validate(
        {
            "width": values.get("figure_width", default.width),
            "height": values.get("figure_height", default.height),
        }
    )
