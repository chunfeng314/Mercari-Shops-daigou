from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings


MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


class InvalidImage(ValueError):
    pass


@dataclass(frozen=True)
class SavedImage:
    image_id: str
    original_filename: str
    source_path: Path
    listing_path: Path
    content_type: str
    listing_content_type: str
    byte_size: int
    digest: str
    width: int
    height: int


def image_root() -> Path:
    return (settings.database_path.parent / "image_assets").resolve()


def _safe_filename(filename: str) -> str:
    name = Path(filename or "image").name
    name = re.sub(r"[^\w.() -]+", "_", name, flags=re.UNICODE).strip(" .")
    return (name or "image")[:160]


def save_image(source_id: str, filename: str, payload: bytes) -> SavedImage:
    if not payload:
        raise InvalidImage("图片文件为空")
    if len(payload) > MAX_IMAGE_BYTES:
        raise InvalidImage("单张图片不能超过 20 MB")

    try:
        with Image.open(BytesIO(payload)) as probe:
            image_format = (probe.format or "").upper()
            width, height = probe.size
            probe.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise InvalidImage("文件不是可读取的图片") from error

    format_info = {
        "JPEG": ("jpg", "image/jpeg"),
        "PNG": ("png", "image/png"),
        "WEBP": ("webp", "image/webp"),
    }
    if image_format not in format_info:
        raise InvalidImage("仅支持 JPEG、PNG、WebP 图片")
    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
        raise InvalidImage("图片尺寸超出处理范围")

    extension, content_type = format_info[image_format]
    image_id = uuid.uuid4().hex
    directory = image_root() / source_id
    directory.mkdir(parents=True, exist_ok=True)
    source_path = directory / f"{image_id}-source.{extension}"
    listing_path = directory / f"{image_id}-listing.jpg"

    try:
        with Image.open(BytesIO(payload)) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                listing_image = background
            else:
                listing_image = image.convert("RGB")
            listing_image.save(listing_path, format="JPEG", quality=94, optimize=True)
        source_path.write_bytes(payload)
    except Exception:
        source_path.unlink(missing_ok=True)
        listing_path.unlink(missing_ok=True)
        raise

    with Image.open(BytesIO(payload)) as image:
        oriented = ImageOps.exif_transpose(image)
        listing_width, listing_height = oriented.size

    return SavedImage(
        image_id=image_id,
        original_filename=_safe_filename(filename),
        source_path=source_path,
        listing_path=listing_path,
        content_type=content_type,
        listing_content_type="image/jpeg",
        byte_size=len(payload),
        digest=sha256(payload).hexdigest(),
        width=listing_width,
        height=listing_height,
    )


def resolve_image_path(relative_path: str) -> Path | None:
    root = image_root()
    path = (root / relative_path).resolve()
    if root not in path.parents or not path.is_file():
        return None
    return path
