from __future__ import annotations

import hashlib
import io
import shutil
import warnings
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from vis_platform_backend.agents.messages import ModelImage
from vis_platform_backend.contracts.reference_images import ReferenceImage, ReferenceImageLinks
from vis_platform_backend.data.errors import DataError
from vis_platform_backend.infrastructure.database import Repository, utc_now
from vis_platform_backend.infrastructure.reference_images import ReferenceImageRepository

UPLOAD_LIMIT = 10 * 1024 * 1024
PIXEL_LIMIT = 25_000_000
PREPARED_LIMIT = 4 * 1024 * 1024


class ReferenceImageService:
    def __init__(self, repository: Repository, store: ReferenceImageRepository, root: Path) -> None:
        self.repository = repository
        self.store = store
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def check_project(self, project_id: str) -> None:
        if not self.repository.project_exists(project_id):
            raise DataError("The project was not found.", "NOT_FOUND", 404)

    def get(self, project_id: str, image_id: str) -> ReferenceImage:
        metadata = self.store.get(project_id, image_id)
        if metadata is None:
            raise DataError("The reference image was not found in this project.", "NOT_FOUND", 404)
        return ReferenceImage.model_validate(metadata)

    def resolve(self, project_id: str, image_ids: list[str]) -> list[ReferenceImage]:
        return [self.get(project_id, image_id) for image_id in image_ids]

    def content_path(self, project_id: str, image_id: str, *, thumbnail: bool = False) -> Path:
        image = self.get(project_id, image_id)
        path = self.root / image.image_id / ("thumbnail.png" if thumbnail else "image.png")
        if not path.is_file():
            raise DataError("The saved reference image is unavailable.", "NOT_FOUND", 404)
        return path

    def model_images(self, project_id: str, image_ids: list[str]) -> tuple[ModelImage, ...]:
        return tuple(
            ModelImage(image_id=image_id, data=self.content_path(project_id, image_id).read_bytes())
            for image_id in image_ids
        )

    def create(
        self, project_id: str, name: str, data: bytes, request_key: str | None = None
    ) -> ReferenceImage:
        self.check_project(project_id)
        if not name.strip() or len(name) > 200 or any(ord(char) < 32 for char in name):
            raise DataError("Choose an image with a valid filename.", "INVALID_IMAGE_NAME", 422)
        if len(data) > UPLOAD_LIMIT:
            raise DataError("Reference images must be smaller than 10 MB.", "IMAGE_TOO_LARGE", 413)
        if not data:
            raise DataError("The image file is empty.", "INVALID_IMAGE", 422)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as source:
                    if source.format not in {"PNG", "JPEG", "WEBP"}:
                        raise DataError(
                            "Use a PNG, JPEG, or static WebP plot image.",
                            "IMAGE_FORMAT_UNSUPPORTED",
                            415,
                        )
                    if source.width * source.height > PIXEL_LIMIT:
                        raise DataError(
                            "Choose an image with fewer than 25 million pixels.",
                            "IMAGE_TOO_LARGE",
                            413,
                        )
                    if getattr(source, "is_animated", False):
                        raise DataError("Choose a still image.", "IMAGE_FORMAT_UNSUPPORTED", 415)
                    source.load()
                    oriented = ImageOps.exif_transpose(source).convert("RGBA")
                    raster = Image.new("RGB", oriented.size, "white")
                    raster.paste(oriented, mask=oriented.getchannel("A"))
                    # New pixels carry none of the uploaded EXIF or text metadata.
                    raster.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                    encoded = self._png(raster)
                    while len(encoded) > PREPARED_LIMIT:
                        raster.thumbnail(
                            (max(1, raster.width * 3 // 4), max(1, raster.height * 3 // 4)),
                            Image.Resampling.LANCZOS,
                        )
                        encoded = self._png(raster)
                    thumb = raster.copy()
                    thumb.thumbnail((240, 180), Image.Resampling.LANCZOS)
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise DataError(
                "The image dimensions are too large.", "IMAGE_TOO_LARGE", 413
            ) from error
        except UnidentifiedImageError as error:
            raise DataError(
                "This file is not a supported image.", "IMAGE_FORMAT_UNSUPPORTED", 415
            ) from error
        except (OSError, ValueError) as error:
            raise DataError(
                "The image could not be read. Choose another file.", "INVALID_IMAGE", 422
            ) from error
        image_id = f"ref_{uuid4().hex}"
        directory = self.root / image_id
        directory.mkdir()
        base = f"/api/v1/projects/{project_id}/plot-reference-images/{image_id}"
        image = ReferenceImage(
            image_id=image_id,
            project_id=project_id,
            name=name,
            width=raster.width,
            height=raster.height,
            byte_size=len(encoded),
            created_at=utc_now(),
            links=ReferenceImageLinks(content=base + "/content", thumbnail=base + "/thumbnail"),
        )
        fingerprint = hashlib.sha256(name.encode() + b"\0" + data).hexdigest()
        try:
            (directory / "image.png").write_bytes(encoded)
            (directory / "thumbnail.png").write_bytes(self._png(thumb))
            saved_id = self.store.insert(image.model_dump(mode="json"), fingerprint, request_key)
            if saved_id != image_id:
                shutil.rmtree(directory)
                return self.get(project_id, saved_id)
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return image

    @staticmethod
    def _png(image: Image.Image) -> bytes:
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    def delete(self, project_id: str, image_id: str) -> None:
        self.store.delete(project_id, image_id)
        shutil.rmtree(self.root / image_id, ignore_errors=True)

    def cleanup(self) -> None:
        for project_id, image_id in self.store.expired(
            (utc_now() - timedelta(hours=24)).isoformat()
        ):
            try:
                self.delete(project_id, image_id)
            except DataError:
                # A request may have pinned this image since the expiry query.
                continue
