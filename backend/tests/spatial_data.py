"""Synthetic spatial data: a tissue section image and cells placed on it, at any size."""

from __future__ import annotations

import io

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image, ImageDraw, ImageFilter

DOMAINS = ["Cortex", "Medulla", "Capsule", "Vessel"]


def tissue_image(width: int = 1200, height: int = 900, seed: int = 3) -> Image.Image:
    """A pink, stained-looking section on a light background."""
    random = np.random.default_rng(seed)
    image = Image.new("RGB", (width, height), (246, 243, 245))
    draw = ImageDraw.Draw(image)
    draw.ellipse((width * 0.1, height * 0.12, width * 0.9, height * 0.88), fill=(228, 170, 200))
    draw.ellipse((width * 0.3, height * 0.3, width * 0.7, height * 0.7), fill=(196, 120, 170))
    noise = random.integers(-18, 18, size=(height, width, 1))
    pixels = np.clip(np.asarray(image, dtype=np.int16) + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(pixels, "RGB").filter(ImageFilter.GaussianBlur(1.2))


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def cells(count: int, width: float, height: float, seed: int = 7) -> pa.Table:
    """Cells inside the section, in the image's pixel coordinates (y increases downward)."""
    random = np.random.default_rng(seed)
    angle = random.uniform(0, 2 * np.pi, count)
    radius = np.sqrt(random.uniform(0, 1, count))
    x = width / 2 + np.cos(angle) * radius * width * 0.4
    y = height / 2 + np.sin(angle) * radius * height * 0.38
    distance = radius
    domain = np.where(
        distance < 0.5, 1, np.where(distance > 0.92, 2, np.where(random.random(count) < 0.04, 3, 0))
    )
    return pa.table(
        {
            "cell_id": pa.array([f"cell_{index}" for index in range(count)]),
            "x_px": pa.array(x),
            "y_px": pa.array(y),
            "domain": pa.array([DOMAINS[index] for index in domain]),
            "marker_a": pa.array(random.gamma(2, 1, count) + (domain == 1) * 3),
            "marker_b": pa.array(random.gamma(2, 1, count) + (domain == 2) * 2),
        }
    )


def parquet_bytes(table: pa.Table) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()
