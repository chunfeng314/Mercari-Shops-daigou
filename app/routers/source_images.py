from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse
import json
import sqlite3

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from app.db import get_db
from app.image_assets import InvalidImage, MAX_IMAGE_BYTES, image_root, resolve_image_path, save_image


router = APIRouter(prefix="/api/china", tags=["货源图片"])


class ImageRoleUpdate(BaseModel):
    image_role: Literal["real_photo", "catalog", "screenshot", "other"] | None = None
    excluded: bool | None = None
    exclusion_reason: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_update(self):
        if self.image_role is None and self.excluded is None:
            raise ValueError("请选择图片用途，或指定排除/恢复图片")
        if self.excluded and not self.exclusion_reason.strip():
            raise ValueError("排除图片时请说明原因")
        return self


def _image_record(row: sqlite3.Row) -> dict:
    image = dict(row)
    try:
        image["vision_review"] = json.loads(image.pop("vision_review_json", "{}") or "{}")
    except (json.JSONDecodeError, TypeError):
        image["vision_review"] = {}
    image.pop("source_path", None)
    image.pop("listing_path", None)
    image["source_file_url"] = f"/api/china/source-images/{row['id']}/file?variant=source"
    image["listing_file_url"] = f"/api/china/source-images/{row['id']}/file?variant=listing"
    return image


@router.post("/sources/{source_id}/images", status_code=201)
async def upload_source_image(
    source_id: str,
    source_page_url: str = Form(..., min_length=1, max_length=2048),
    source_asset_url: str = Form(default="", max_length=2048),
    image_role: Literal["real_photo", "catalog", "screenshot", "other"] = Form(default="other"),
    file: UploadFile = File(...),
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    source = connection.execute(
        "SELECT id FROM china_sources WHERE id = ?", (source_id,)
    ).fetchone()
    if source is None:
        raise HTTPException(status_code=404, detail="未找到中国货源候选")
    parsed_page = urlparse(source_page_url)
    if parsed_page.scheme not in ("http", "https") or not parsed_page.netloc:
        raise HTTPException(status_code=422, detail="来源页面需要填写完整的 http 或 https 链接")
    if source_asset_url:
        parsed_asset = urlparse(source_asset_url)
        if parsed_asset.scheme not in ("http", "https") or not parsed_asset.netloc:
            raise HTTPException(status_code=422, detail="图片来源链接需要填写完整的 http 或 https 链接")

    payload = await file.read(MAX_IMAGE_BYTES + 1)
    if len(payload) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="单张图片不能超过 20 MB")
    try:
        saved = save_image(source_id, file.filename or "image", payload)
    except InvalidImage as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    created_at = datetime.now(timezone.utc).isoformat()
    relative_source_path = str(saved.source_path.relative_to(image_root()))
    relative_listing_path = str(saved.listing_path.relative_to(image_root()))
    try:
        connection.execute(
            """INSERT INTO source_images
            (id, source_id, original_filename, source_path, listing_path, content_type,
             listing_content_type, byte_size, sha256, width, height, image_role,
             source_page_url, source_asset_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                saved.image_id,
                source_id,
                saved.original_filename,
                relative_source_path,
                relative_listing_path,
                saved.content_type,
                saved.listing_content_type,
                saved.byte_size,
                saved.digest,
                saved.width,
                saved.height,
                image_role,
                source_page_url,
                source_asset_url,
                created_at,
            ),
        )
        connection.commit()
    except Exception:
        saved.source_path.unlink(missing_ok=True)
        saved.listing_path.unlink(missing_ok=True)
        raise

    row = connection.execute(
        "SELECT * FROM source_images WHERE id = ?", (saved.image_id,)
    ).fetchone()
    return _image_record(row)


@router.get("/sources/{source_id}/images")
def list_source_images(
    source_id: str,
    connection: sqlite3.Connection = Depends(get_db),
) -> list[dict]:
    source = connection.execute(
        "SELECT id FROM china_sources WHERE id = ?", (source_id,)
    ).fetchone()
    if source is None:
        raise HTTPException(status_code=404, detail="未找到中国货源候选")
    rows = connection.execute(
        "SELECT * FROM source_images WHERE source_id = ? ORDER BY created_at DESC",
        (source_id,),
    ).fetchall()
    return [_image_record(row) for row in rows]


@router.patch("/source-images/{image_id}")
def update_source_image_role(
    image_id: str,
    payload: ImageRoleUpdate,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    image = connection.execute(
        "SELECT * FROM source_images WHERE id=?", (image_id,)
    ).fetchone()
    if image is None:
        raise HTTPException(status_code=404, detail="未找到货源图片")
    source = connection.execute(
        "SELECT item_id,archived_at FROM china_sources WHERE id=?", (image["source_id"],)
    ).fetchone()
    if source is None or source["archived_at"]:
        raise HTTPException(status_code=409, detail="货源不存在或已归档")
    from app.audit import now_iso, record_event
    if payload.image_role is not None:
        if image["excluded_at"] and payload.excluded is not False:
            raise HTTPException(409, "请先恢复该图片，再核对其用途")
        connection.execute("UPDATE source_images SET image_role=? WHERE id=?", (payload.image_role, image_id))
        record_event(connection, "item", source["item_id"], "source_image_role_updated", {
            "source_id": image["source_id"], "image_id": image_id,
            "from": image["image_role"], "to": payload.image_role,
        })
    if payload.excluded is not None:
        reason = payload.exclusion_reason.strip() if payload.excluded else ""
        if payload.excluded is False and image["excluded_at"] and payload.image_role is None:
            connection.execute("UPDATE source_images SET image_role='other' WHERE id=?", (image_id,))
        connection.execute("UPDATE source_images SET excluded_at=?,exclusion_reason=? WHERE id=?", (
            now_iso() if payload.excluded else None, reason, image_id,
        ))
        record_event(connection, "item", source["item_id"], "source_image_excluded" if payload.excluded else "source_image_restored", {
            "source_id": image["source_id"], "image_id": image_id, "reason": reason,
        })
    connection.commit()
    return _image_record(connection.execute("SELECT * FROM source_images WHERE id=?", (image_id,)).fetchone())


@router.get("/source-images/{image_id}/file")
def get_source_image_file(
    image_id: str,
    variant: Literal["source", "listing"] = "listing",
    connection: sqlite3.Connection = Depends(get_db),
) -> FileResponse:
    image = connection.execute(
        "SELECT * FROM source_images WHERE id = ?", (image_id,)
    ).fetchone()
    if image is None:
        raise HTTPException(status_code=404, detail="未找到图片")
    path_column = "source_path" if variant == "source" else "listing_path"
    type_column = "content_type" if variant == "source" else "listing_content_type"
    path = resolve_image_path(image[path_column])
    if path is None:
        raise HTTPException(status_code=404, detail="图片文件不存在")
    return FileResponse(path, media_type=image[type_column])
