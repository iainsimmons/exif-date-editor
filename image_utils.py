#!/usr/bin/env python3
from __future__ import annotations

import io
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

from exif_utils import EXIFTOOL

PREVIEW_TAGS = ("PreviewImage", "JpgFromRaw", "ThumbnailImage")


def _open_image(data: bytes) -> Image.Image | None:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        image = ImageOps.exif_transpose(image)
        return image.copy()
    except Exception:
        return None


def load_preview_image(file_path) -> Image.Image | None:
    path = Path(file_path)
    extension = path.suffix.lower()
    if extension in {".jpg", ".jpeg"}:
        try:
            with Image.open(path) as image:
                image.load()
                oriented = ImageOps.exif_transpose(image)
                return oriented.copy()
        except Exception:
            return None
    if extension in {".orf"}:
        for tag in PREVIEW_TAGS:
            try:
                proc = subprocess.run(
                    [EXIFTOOL, "-b", f"-{tag}", str(path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=60,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if proc.returncode != 0 or len(proc.stdout) < 1000:
                continue
            image = _open_image(proc.stdout)
            if image is not None and image.width > 1 and image.height > 1:
                return image
    return None
