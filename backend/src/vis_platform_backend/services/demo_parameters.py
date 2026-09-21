from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from vis_platform_backend.contracts.figures import FigureSize
from vis_platform_backend.contracts.parameters import (
    BooleanControl,
    ChoiceControl,
    ChoiceOption,
    ControlDefinition,
    ControlGroup,
    ControlVisibility,
    NumberControl,
    ParameterValue,
    TextControl,
)
from vis_platform_backend.domain.parameters import resolve_parameters
from vis_platform_backend.services.demo_figures import DemoFigure, DemoFigureKind
from vis_platform_backend.services.figure_controls import (
    figure_controls,
    resolve_figure_size,
)

SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)


@dataclass(frozen=True, slots=True)
class ParameterizedDemo:
    figure_size: FigureSize
    figure: DemoFigure
    controls: list[ControlDefinition]
    groups: list[ControlGroup]
    values: dict[str, ParameterValue]


def demo_controls(
    figure: DemoFigure, size: FigureSize
) -> tuple[list[ControlDefinition], list[ControlGroup]]:
    controls: list[ControlDefinition] = [
        TextControl(id="title", label="Title", value=figure.title, min_length=1, max_length=80),
        NumberControl(
            id="label_size",
            label="Label size",
            value=11,
            minimum=10,
            maximum=14,
            step=0.5,
            unit="pt",
        ),
        ChoiceControl(
            id="palette",
            label="Palette",
            value="original",
            options=[
                ChoiceOption(value="original", label="Forest and clay"),
                ChoiceOption(value="plum", label="Plum and sage"),
                ChoiceOption(value="blue", label="Blue and amber"),
            ],
        ),
    ]
    group = figure.kind.value
    if figure.kind is DemoFigureKind.DISTRIBUTION:
        controls.extend(
            [
                BooleanControl(
                    id="show_points", label="Individual observations", value=True, group=group
                ),
                BooleanControl(id="show_box", label="Median and spread", value=True, group=group),
            ]
        )
    elif figure.kind is DemoFigureKind.RELATIONSHIP:
        controls.extend(
            [
                NumberControl(
                    id="point_size",
                    label="Point size",
                    value=5.5,
                    minimum=2,
                    maximum=8,
                    step=0.5,
                    unit="pt",
                    group=group,
                ),
                BooleanControl(
                    id="show_trend",
                    label="Fitted trend",
                    value=True,
                    group=group,
                    description="Show or hide the existing illustrative fit.",
                ),
                BooleanControl(
                    id="show_band",
                    label="Uncertainty band",
                    value=True,
                    group=group,
                    visible_when=ControlVisibility(control_id="show_trend", equals=True),
                ),
            ]
        )
    elif figure.kind is DemoFigureKind.SURVIVAL:
        controls.append(
            BooleanControl(id="show_censoring", label="Censoring marks", value=True, group=group)
        )
    else:
        controls.append(
            BooleanControl(
                id="show_points", label="Individual observations", value=True, group=group
            )
        )
    groups = [
        ControlGroup(id="essential", label="Appearance"),
        ControlGroup(id=group, label=group.replace("_", " ").capitalize()),
    ]
    return figure_controls(controls, groups, size)


def parameterize_demo(
    figure: DemoFigure, changes: Mapping[str, ParameterValue], initial_size: FigureSize
) -> ParameterizedDemo:
    controls, groups = demo_controls(figure, initial_size)
    values = resolve_parameters(controls, changes, require_change=False)
    size = resolve_figure_size(values, initial_size)
    root = ET.fromstring(figure.svg)
    root.set("width", f"{size.width:g}in")
    root.set("height", f"{size.height:g}in")
    root.set("preserveAspectRatio", "xMidYMid meet")
    title = str(values["title"])
    heading = root.find(".//*[@data-role='plot-title']")
    assert heading is not None
    heading.text = title
    # Fit long user titles in the existing title area without obscuring the disclosure.
    heading.set("font-size", str(min(25.0, 600 / max(len(title) * 0.61, 1))))
    accessible_title = root.find(f"{{{SVG}}}title")
    assert accessible_title is not None
    accessible_title.text = title + " — demonstration only"
    body = root.find(".//*[@data-role='plot-body']")
    assert body is not None
    label_scale = float(values["label_size"]) / 11
    for node in body.iter():
        if node.tag == f"{{{SVG}}}text" and "font-size" in node.attrib:
            node.set("font-size", str(float(node.attrib["font-size"]) * label_scale))
    layer_flags = {
        "observations": values.get("show_points", True),
        "box": values.get("show_box", True),
        "censoring": values.get("show_censoring", True),
        "trend": values.get("show_trend", True),
        "band": values.get("show_trend", True) and values.get("show_band", True),
    }
    for node in body.iter():
        layer = node.get("data-layer")
        if layer in layer_flags and not layer_flags[layer]:
            node.set("display", "none")
        if layer == "observations" and "point_size" in values:
            for point in node.iter(f"{{{SVG}}}circle"):
                point.set("r", str(values["point_size"]))
    palettes = {
        "plum": ("#965e7c", "#65938a", "#6e78a0"),
        "blue": ("#4278a6", "#bd8b45", "#658979"),
    }
    palette = palettes.get(str(values["palette"]))
    if palette is not None:
        colors = {
            **dict.fromkeys(("#2f6f5a", "#397b64", "#397b64", "#3b765f"), palette[0]),
            **dict.fromkeys(("#d17452", "#d27654"), palette[1]),
            "#57749a": palette[2],
        }
        for node in body.iter():
            for attribute in ("fill", "stroke"):
                if node.get(attribute) in colors:
                    node.set(attribute, colors[node.attrib[attribute]])
    labels = {
        DemoFigureKind.DISTRIBUTION: "distribution comparison",
        DemoFigureKind.RELATIONSHIP: "relationship figure",
        DemoFigureKind.SURVIVAL: "survival figure",
        DemoFigureKind.GROUP_COMPARISON: "group comparison",
    }
    description = (
        f"{title}. An illustrative {labels[figure.kind]} using demonstration data "
        "and saved display parameters. "
        "No research dataset was used."
    )
    accessible_description = root.find(f"{{{SVG}}}desc")
    assert accessible_description is not None
    accessible_description.text = description
    resolved_controls = [
        type(control).model_validate({**control.model_dump(), "value": values[control.id]})
        for control in controls
    ]
    return ParameterizedDemo(
        figure_size=size,
        figure=DemoFigure(
            kind=figure.kind,
            title=title,
            description=description,
            svg=ET.tostring(root, encoding="unicode"),
        ),
        controls=resolved_controls,
        groups=groups,
        values=values,
    )
