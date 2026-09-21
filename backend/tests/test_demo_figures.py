from __future__ import annotations

from xml.etree import ElementTree

import pytest

from vis_platform_backend.services.demo_figures import (
    DemoFigureKind,
    classify_demo_figure,
    render_demo_figure,
)


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        ("Show a publication-style Kaplan–Meier survival curve by cohort", DemoFigureKind.SURVIVAL),
        ("Compare progression-free survival between arms", DemoFigureKind.SURVIVAL),
        ("Make a violin plot of gene expression by cell type", DemoFigureKind.DISTRIBUTION),
        ("Show the distribution of measured values", DemoFigureKind.DISTRIBUTION),
        (
            "Show a violin distribution of expression versus group",
            DemoFigureKind.DISTRIBUTION,
        ),
        ("Plot a scatter relationship between dose and response", DemoFigureKind.RELATIONSHIP),
        ("Show the correlation between age and response", DemoFigureKind.RELATIONSHIP),
        ("Compare treatment and control", DemoFigureKind.GROUP_COMPARISON),
    ],
)
def test_classifies_scientific_figure_family(request_text: str, expected: DemoFigureKind) -> None:
    assert classify_demo_figure(request_text) is expected


@pytest.mark.parametrize(
    "request_text",
    [
        "Show a Kaplan-Meier survival curve",
        "Make a violin distribution of expression",
        "Plot the relationship between dose and response",
        "Compare control and treatment",
    ],
)
def test_rendered_figures_are_accessible_valid_svg(request_text: str) -> None:
    figure = render_demo_figure(request_text)
    root = ElementTree.fromstring(figure.svg)
    namespace = {"svg": "http://www.w3.org/2000/svg"}

    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.attrib["role"] == "img"
    assert root.attrib["aria-labelledby"] == "demo-figure-title demo-figure-description"
    assert root.attrib["data-demo"] == "true"
    assert root.attrib["data-figure-kind"] == figure.kind.value
    assert root.find("svg:title", namespace).text
    assert root.find("svg:desc", namespace).text == figure.description
    assert "No research dataset was used" in figure.description
    assert "DEMONSTRATION · NO DATASET" in figure.svg
    assert "No research data was used" in figure.svg


def test_each_supported_family_has_distinct_markup() -> None:
    figures = [
        render_demo_figure("survival by cohort"),
        render_demo_figure("violin plot of expression"),
        render_demo_figure("scatter relationship"),
        render_demo_figure("compare the groups"),
    ]

    assert {figure.kind for figure in figures} == set(DemoFigureKind)
    assert len({figure.svg for figure in figures}) == len(figures)
    assert all(figure.title in figure.svg for figure in figures)


def test_request_details_select_specific_variants() -> None:
    dose = render_demo_figure("Draw a dose-response curve")
    scatter = render_demo_figure("Draw a scatter plot of two variables")
    overall = render_demo_figure("Show overall survival")
    progression_free = render_demo_figure("Show progression-free survival")

    assert dose.kind is scatter.kind is DemoFigureKind.RELATIONSHIP
    assert dose.svg != scatter.svg
    assert dose.title == "Dose–response relationship"
    assert scatter.title == "Relationship between measured variables"
    assert overall.title == "Overall survival by cohort"
    assert progression_free.title == "Progression-free survival by cohort"


def test_selected_survival_outcome_overrides_ambiguous_request() -> None:
    progression_free = render_demo_figure(
        "Show a survival curve by cohort",
        survival_outcome="progression_free_survival",
    )
    overall = render_demo_figure(
        "Show a survival curve by cohort",
        survival_outcome="overall_survival",
    )

    assert progression_free.kind is overall.kind is DemoFigureKind.SURVIVAL
    assert progression_free.title == "Progression-free survival by cohort"
    assert overall.title == "Overall survival by cohort"
