from pathlib import Path
from typing import Any, Literal

from vis_platform_backend.contracts.datasets import Dataset

from .errors import DataError
from .profiling import read_table


def validate_relationships(dataset: Dataset, bindings: dict[str, Any]) -> None:
    objects = {item.object_id: item for item in dataset.objects}
    for relation in dataset.relationships:
        if relation.left_object_id not in objects or relation.right_object_id not in objects:
            raise DataError(
                "A relationship references an unknown object.", "INVALID_RELATIONSHIP", 422
            )
        if relation.kind not in {"join", "annotates"}:
            continue
        left, right = objects[relation.left_object_id], objects[relation.right_object_id]
        if (
            not bindings.get(left.object_id, {}).get("path")
            or not bindings.get(right.object_id, {}).get("path")
            or relation.left_axis is not None
            or relation.right_axis is not None
            or left.format != "csv"
            or right.format != "csv"
            or left.readiness != "ready"
            or right.readiness != "ready"
        ):
            continue
        if (
            not relation.left_key
            or not relation.right_key
            or relation.left_key not in {c.name for c in left.columns}
            or relation.right_key not in {c.name for c in right.columns}
        ):
            relation.validation = "invalid"
            relation.limitations = ["The proposed join keys are not present in both objects."]
            continue
        _, left_rows = read_table(Path(bindings[left.object_id]["path"]))
        _, right_rows = read_table(Path(bindings[right.object_id]["path"]))
        left_values = [row[relation.left_key] for row in left_rows]
        right_values = [row[relation.right_key] for row in right_rows]
        left_unique, right_unique = (
            len(set(left_values)) == len(left_values),
            len(set(right_values)) == len(right_values),
        )
        right_keys = set(right_values)
        relation.matched_rows = sum(value in right_keys for value in left_values)
        actual: Literal["one_to_one", "many_to_one", "one_to_many", "many_to_many", "unknown"] = (
            "one_to_one"
            if left_unique and right_unique
            else "many_to_one"
            if right_unique
            else "one_to_many"
            if left_unique
            else "many_to_many"
        )
        valid = (
            relation.matched_rows > 0
            and all(left_values)
            and all(right_values)
            and relation.cardinality in {"unknown", actual}
        )
        relation.validation = "verified" if valid else "invalid"
        if valid:
            relation.cardinality = actual
        else:
            relation.limitations = [
                "The data does not satisfy the declared join cardinality or matching keys."
            ]
