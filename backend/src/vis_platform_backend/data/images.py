"""Images such as tissue sections, kept to be shown under plotted points."""

from __future__ import annotations

import warnings
from pathlib import Path

from PIL import Image

from vis_platform_backend.contracts.datasets import ObjectDescription

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
# The stored copy is enough for printed figures and on-screen detail; larger originals are
# resampled, and the object records the scale so pixel coordinates still line up.
STORED_LONG_SIDE = 8192


def store_image(
    path: Path, target: Path, name: str, owner_id: str, revision_id: str
) -> ObjectDescription:
    try:
        with warnings.catch_warnings():
            # Section images are routinely larger than Pillow's warning size; its hard limit
            # (about 179 million pixels) still applies.
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(path) as source:
                if getattr(source, "n_frames", 1) > 1 and source.format != "TIFF":
                    raise ValueError("Use a still image.")
                width, height = source.size
                # Pixel coordinates refer to the image as stored, so orientation tags are ignored.
                image = source.convert("RGB")
    except Image.DecompressionBombError as error:
        raise ValueError(
            "Images can have up to about 179 million pixels. Upload a downsampled image and "
            "state how many data units one of its pixels spans."
        ) from error
    scale = min(1.0, STORED_LONG_SIDE / max(width, height))
    if scale < 1:
        image = image.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS
        )
    image.save(target, format="PNG")
    return ObjectDescription(
        object_id="",
        revision_id=revision_id,
        owner_id=owner_id,
        name=name,
        kind="image",
        format="png",
        dimensions=[height, width],
        capabilities=["inspect", "materialize"],
        description=f"Image, {width:,} × {height:,} pixels.",
        limitations=[
            "An image, not a data table. It can be shown under a point map, placed by the "
            "data units one of its pixels spans."
        ],
        extensions={"pixel_width": width, "pixel_height": height, "stored_scale": scale},
    )
