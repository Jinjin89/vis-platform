"""Apply validated document operations to an isolated copy, preserving stable IDs."""

from __future__ import annotations

from typing import Any

from vis_platform_backend.contracts.report_content import ReportContent
from vis_platform_backend.contracts.report_operations import ReportOperation
from vis_platform_backend.data.errors import DataError


def _fail(message: str) -> None:
    raise DataError(message, "INVALID_REPORT_OPERATION", 422)


def _section(sections: list[dict[str, Any]], section_id: str) -> dict[str, Any]:
    for section in sections:
        if section["id"] == section_id:
            return section
    raise DataError("The target section was not found.", "NOT_FOUND", 404)


def _subtree(sections: list[dict[str, Any]], section_id: str) -> list[dict[str, Any]]:
    root = _section(sections, section_id)
    return [root, *[section for section in sections if section["parent_id"] == section_id]]


def _section_index(
    sections: list[dict[str, Any]], parent_id: str | None, before: str | None, after: str | None
) -> int:
    if parent_id:
        parent = _section(sections, parent_id)
        if parent["level"] != 1:
            _fail("Subsections must belong to a first-level section.")
    anchor = before or after
    if anchor:
        section = _section(sections, anchor)
        if section["parent_id"] != parent_id:
            _fail("The section anchor must have the same parent.")
        return (
            sections.index(section)
            if before
            else sections.index(_subtree(sections, anchor)[-1]) + 1
        )
    return sections.index(_subtree(sections, parent_id)[-1]) + 1 if parent_id else len(sections)


def _block_index(blocks: list[dict[str, Any]], before: str | None, after: str | None) -> int:
    if not (before or after):
        return len(blocks)
    for index, block in enumerate(blocks):
        if block["id"] == (before or after):
            return index if before else index + 1
    raise DataError("The insertion anchor no longer exists in that section.", "NOT_FOUND", 404)


def apply_report_operations(
    content: ReportContent, operations: list[ReportOperation]
) -> ReportContent:
    result = content.model_dump(mode="json")
    for operation in operations:
        op = operation.model_dump(mode="json")
        sections = result["sections"]
        kind = op["op"]
        if kind == "set_slide_settings":
            if result["kind"] != "slides":
                _fail("Slide layout settings require a slide document.")
            _section(sections, op["section_id"])["slide"] = op["settings"]
        elif kind == "set_presentation_settings":
            if result["kind"] != "slides":
                _fail("Presentation settings require a slide document.")
            result["presentation"] = op["settings"]
        elif kind == "rename_report":
            result["title"] = op["title"]
        elif kind == "set_datasets":
            result["datasets"] = op["datasets"]
        elif kind == "insert_section":
            section = op["section"]
            index = _section_index(sections, section["parent_id"], op["before_id"], op["after_id"])
            sections.insert(index, section)
        elif kind == "rename_section":
            _section(sections, op["section_id"])["title"] = op["title"]
        elif kind == "remove_section":
            removed = {item["id"] for item in _subtree(sections, op["section_id"])}
            result["sections"] = [item for item in sections if item["id"] not in removed]
        elif kind == "move_section":
            moved = _subtree(sections, op["section_id"])
            if op["parent_id"] in {item["id"] for item in moved}:
                _fail("A section cannot be moved inside itself.")
            if op["parent_id"] and len(moved) > 1:
                _fail("A section with subsections cannot become a subsection.")
            remaining = [section for section in sections if section not in moved]
            index = _section_index(remaining, op["parent_id"], op["before_id"], op["after_id"])
            moved[0]["parent_id"] = op["parent_id"]
            moved[0]["level"] = 2 if op["parent_id"] else 1
            remaining[index:index] = moved
            result["sections"] = remaining
        elif kind in {"insert_block", "replace_block"}:
            blocks = _section(sections, op["section_id"])["blocks"]
            if kind == "insert_block":
                blocks.insert(_block_index(blocks, op["before_id"], op["after_id"]), op["block"])
            else:
                replacement_index = next(
                    (i for i, block in enumerate(blocks) if block["id"] == op["block"]["id"]), None
                )
                if replacement_index is None:
                    _fail("The block to replace was not found in the target section.")
                assert replacement_index is not None
                blocks[replacement_index] = op["block"]
        elif kind in {"remove_block", "move_block"}:
            source = next(
                (
                    section
                    for section in sections
                    if any(block["id"] == op["block_id"] for block in section["blocks"])
                ),
                None,
            )
            if source is None:
                _fail("The target block was not found.")
            assert source is not None
            block = next(block for block in source["blocks"] if block["id"] == op["block_id"])
            source["blocks"].remove(block)
            if kind == "move_block":
                blocks = _section(sections, op["section_id"])["blocks"]
                blocks.insert(_block_index(blocks, op["before_id"], op["after_id"]), block)
        # Validate each transition, so later actions cannot hide an invalid intermediate edit.
        result = ReportContent.model_validate(result).model_dump(mode="json")
    return ReportContent.model_validate(result)
