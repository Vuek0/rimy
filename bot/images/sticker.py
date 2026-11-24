"""Turn an art into a Telegram sticker: a square crop around the face area, 512×512 WebP."""

import io
import logging

from PIL import Image, ImageOps

log = logging.getLogger(__name__)

STICKER_SIZE = 512
# For tall arts the face is usually near the top: start the square a little below the top edge.
TOP_OFFSET = 0.08


def square_box(width: int, height: int) -> tuple[int, int, int, int]:
    """Crop box (left, top, right, bottom) for a square: top part of tall images, center of wide ones."""
    if height > width:
        top = min(int(height * TOP_OFFSET), height - width)
        return 0, top, width, top + width
    left = (width - height) // 2
    return left, 0, left + height, height


def to_sticker(data: bytes) -> bytes | None:
    """JPEG/PNG/WebP bytes → 512×512 WebP sticker bytes. None if the image can't be read."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGBA")
            image = image.crop(square_box(*image.size))
            image = image.resize((STICKER_SIZE, STICKER_SIZE), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            image.save(out, format="WEBP", quality=90, method=4)
            return out.getvalue()
    except Exception as exc:
        log.info("sticker conversion failed: %r", exc)
        return None
