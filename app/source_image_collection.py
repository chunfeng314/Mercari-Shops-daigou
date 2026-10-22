"""Persist browser-captured source image candidates with their provenance."""
from datetime import datetime, timezone
import sqlite3
import re
from pathlib import Path
from urllib.parse import urlsplit

from app.image_assets import InvalidImage, image_root, save_image
from app.audit import now_iso, record_event


def image_asset_key(url: str) -> str:
    parsed = urlsplit(url)
    path = re.sub(r"(\.(?:jpe?g|png|webp|heic))_(?:\d+x\d+|Q\d+).*$", r"\1", parsed.path, flags=re.I)
    return (parsed.hostname or "").lower() + path


def reconcile_collected_images(connection: sqlite3.Connection, source_id: str, item_id: str, detail: dict) -> list[str]:
    """Quarantine proven recommendations and unverified legacy carousel extras.

    A full reconciliation is allowed only when the page explicitly declares a
    single-image gallery. Manual uploads and review-area captures are preserved.
    Files and their original provenance remain available for inspection/restore.
    """
    valid = {image_asset_key(image["url"]) for image in detail.get("images", [])}
    valid.update(image_asset_key(url) for url in detail.get("gallery_asset_urls", []))
    recommended = {image_asset_key(image["url"]) for image in detail.get("excluded_images", [])}
    complete_single_gallery = detail.get("single_image_gallery") and len(valid) == 1
    changed = []
    for row in connection.execute("SELECT * FROM source_images WHERE source_id=? AND excluded_at IS NULL", (source_id,)).fetchall():
        if row["collection_note"] not in ("闲鱼商品详情页图片候选", "闲鱼搜索结果缩略图候选"):
            continue
        key = image_asset_key(row["source_asset_url"])
        if key in valid:
            continue
        if key in recommended:
            reason = "自动排除：已确认来自推荐商品区域，不属于当前商品详情图"
        elif complete_single_gallery:
            reason = "自动排除：当前货源为单图商品，旧自动采集图的商品归属未核实"
        else:
            continue
        connection.execute("UPDATE source_images SET excluded_at=?,exclusion_reason=? WHERE id=?", (now_iso(), reason, row["id"]))
        record_event(connection, "item", item_id, "source_image_excluded", {"source_id": source_id, "image_id": row["id"], "reason": reason})
        changed.append(row["id"])
    return changed


def save_collected_image(
    connection: sqlite3.Connection,
    source_id: str,
    page_url: str,
    asset_url: str,
    collection_note: str,
    payload: bytes,
) -> dict:
    asset_key = image_asset_key(asset_url)
    for existing in connection.execute("SELECT id,source_asset_url FROM source_images WHERE source_id=?", (source_id,)):
        if existing["source_asset_url"] and image_asset_key(existing["source_asset_url"]) == asset_key:
            return {"id": existing["id"], "duplicate": True}
    saved = save_image(source_id, Path(asset_url.split("?", 1)[0]).name or "source-image.png", payload)
    existing = connection.execute(
        "SELECT id FROM source_images WHERE source_id=? AND sha256=?", (source_id, saved.digest)
    ).fetchone()
    if existing:
        saved.source_path.unlink(missing_ok=True)
        saved.listing_path.unlink(missing_ok=True)
        return {"id": existing["id"], "duplicate": True}

    created_at = datetime.now(timezone.utc).isoformat()
    try:
        connection.execute(
            """INSERT INTO source_images
            (id, source_id, original_filename, source_path, listing_path, content_type,
             listing_content_type, byte_size, sha256, width, height, image_role,
             source_page_url, source_asset_url, collection_note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'other', ?, ?, ?, ?)""",
            (
                saved.image_id, source_id, saved.original_filename,
                str(saved.source_path.relative_to(image_root())),
                str(saved.listing_path.relative_to(image_root())),
                saved.content_type, saved.listing_content_type, saved.byte_size,
                saved.digest, saved.width, saved.height, page_url, asset_url,
                (collection_note or "闲鱼详情页图片候选")[:300], created_at,
            ),
        )
    except Exception:
        saved.source_path.unlink(missing_ok=True)
        saved.listing_path.unlink(missing_ok=True)
        raise
    row = connection.execute(
        "SELECT id, image_role, width, height FROM source_images WHERE id=?", (saved.image_id,)
    ).fetchone()
    return {**dict(row), "duplicate": False}


__all__ = ["InvalidImage", "save_collected_image"]
