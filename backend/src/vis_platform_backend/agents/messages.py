from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelImage:
    image_id: str
    data: bytes = field(repr=False)
    label: str = "Plot reference"

    def part(self) -> dict[str, Any]:
        return {
            "type": "image_url",
            "image_url": {
                "url": "data:image/png;base64," + base64.b64encode(self.data).decode("ascii"),
                "detail": "high",
            },
        }


class ModelContext(dict[str, Any]):
    """JSON context and image bytes have separate transport and persistence boundaries."""

    def __init__(self, values: dict[str, Any], *, images: tuple[ModelImage, ...] = ()) -> None:
        super().__init__(values)
        self.images = images


def user_content(text: str, images: tuple[ModelImage, ...] = ()) -> str | list[dict[str, Any]]:
    if not images:
        return text
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for image in images:
        parts.extend(
            [
                {"type": "text", "text": f"{image.label}: {image.image_id}"},
                image.part(),
            ]
        )
    return parts


def redact_images(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[image redacted]" if key == "image_url" else redact_images(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_images(item) for item in value]
    return value
