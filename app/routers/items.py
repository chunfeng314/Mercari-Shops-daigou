import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.records import listing_draft_record
from app.audit import entity_events, now_iso, record_event
from app.schemas_management import ItemUpdate
from app.listing_preparation import attach_preparation_status, prepare_listing


router = APIRouter(prefix="/api/items", tags=["商品流程"])


def _parse_vision_review(value: str) -> dict:
    try:
        result = json.loads(value or "{}")
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


@router.get("")
def list_items(include_archived: bool = False, connection: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    rows = connection.execute(
        """SELECT i.*, d.id AS draft_id, d.title_ja, d.price_jpy, d.listing_url,
        d.estimated_profit_cny, d.estimated_margin_pct, d.inventory_quantity,
        (SELECT COUNT(*) FROM china_sources s WHERE s.item_id = i.id AND s.archived_at IS NULL) AS source_count,
        (SELECT MIN(s.price_cny) FROM china_sources s WHERE s.item_id = i.id AND s.archived_at IS NULL) AS source_price_cny,
        (SELECT im.id FROM source_images im JOIN china_sources s ON s.id = im.source_id
         WHERE s.item_id = i.id AND im.excluded_at IS NULL ORDER BY im.created_at DESC LIMIT 1) AS thumbnail_image_id
        FROM items AS i
        LEFT JOIN listing_drafts AS d ON d.item_id = i.id
        WHERE (? OR i.archived_at IS NULL)
        ORDER BY i.created_at DESC""", (include_archived,)
    ).fetchall()
    return [dict(row) for row in rows]


@router.get("/{item_id}")
def get_item(
    item_id: str,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    item = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise HTTPException(status_code=404, detail="未找到商品")
    sources = connection.execute(
        "SELECT * FROM china_sources WHERE item_id = ? ORDER BY created_at DESC", (item_id,)
    ).fetchall()
    source_records = []
    for source in sources:
        source_record = dict(source)
        images = connection.execute(
            "SELECT * FROM source_images WHERE source_id = ? ORDER BY created_at DESC",
            (source["id"],),
        ).fetchall()
        source_record["images"] = [
            {
                "id": image["id"],
                "original_filename": image["original_filename"],
                "image_role": image["image_role"],
                "source_page_url": image["source_page_url"],
                "source_asset_url": image["source_asset_url"],
                "collection_note": image["collection_note"],
                "vision_review": _parse_vision_review(image["vision_review_json"]),
                "vision_review_at": image["vision_review_at"],
                "vision_review_model": image["vision_review_model"],
                "excluded_at": image["excluded_at"], "exclusion_reason": image["exclusion_reason"],
                "content_type": image["content_type"],
                "listing_content_type": image["listing_content_type"],
                "byte_size": image["byte_size"],
                "sha256": image["sha256"],
                "width": image["width"],
                "height": image["height"],
                "created_at": image["created_at"],
                "source_file_url": f"/api/china/source-images/{image['id']}/file?variant=source",
                "listing_file_url": f"/api/china/source-images/{image['id']}/file?variant=listing",
            }
            for image in images
        ]
        source_records.append(source_record)
    draft = connection.execute(
        "SELECT * FROM listing_drafts WHERE item_id = ?", (item_id,)
    ).fetchone()
    return {
        "item": dict(item),
        "china_sources": source_records,
        "listing_draft": listing_draft_record(draft),
        "listing_preparation": attach_preparation_status(connection, item_id, prepare_listing(connection, item_id)),
        "events": entity_events(connection, "item", item_id),
    }


@router.patch("/{item_id}")
def update_item(item_id: str, payload: ItemUpdate, connection: sqlite3.Connection = Depends(get_db)) -> dict:
    item = connection.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if item is None:
        raise HTTPException(404, "未找到商品")
    if item["archived_at"]:
        raise HTTPException(409, "请先恢复已归档商品")
    values = payload.model_dump(exclude_unset=True)
    identity_changed = "japan_url" in values and values["japan_url"] != item["japan_url"]
    if identity_changed and connection.execute("SELECT 1 FROM listing_drafts WHERE item_id=?", (item_id,)).fetchone():
        raise HTTPException(409, "商品已有上架记录，不能换成其他日本商品；请新增选品")
    if values:
        assignments = ",".join(f"{name}=?" for name in values)
        connection.execute(f"UPDATE items SET {assignments} WHERE id=?", (*values.values(), item_id))
        if identity_changed:
            connection.execute("UPDATE china_sources SET match_status='pending',availability_status='unknown',availability_checked_at=NULL WHERE item_id=?", (item_id,))
            connection.execute("UPDATE items SET status=CASE WHEN EXISTS(SELECT 1 FROM china_sources WHERE item_id=? AND archived_at IS NULL) THEN 'sourcing' ELSE 'candidate' END WHERE id=?", (item_id,item_id))
        record_event(connection, "item", item_id, "updated", values)
        connection.commit()
    return dict(connection.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone())


@router.post("/{item_id}/archive")
@router.delete("/{item_id}", summary="归档商品（可恢复）")
def archive_item(item_id: str, connection: sqlite3.Connection = Depends(get_db)) -> dict:
    item = connection.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if item is None:
        raise HTTPException(404, "未找到商品")
    if item["status"] == "listed":
        raise HTTPException(409, "店铺商品仍在销售，不能直接归档")
    if not item["archived_at"]:
        connection.execute("UPDATE items SET archived_at=? WHERE id=?", (now_iso(), item_id))
        record_event(connection, "item", item_id, "archived")
        connection.commit()
    return {"id": item_id, "archived": True}


@router.post("/{item_id}/restore")
def restore_item(item_id: str, connection: sqlite3.Connection = Depends(get_db)) -> dict:
    if connection.execute("SELECT id FROM items WHERE id=?", (item_id,)).fetchone() is None:
        raise HTTPException(404, "未找到商品")
    connection.execute("UPDATE items SET archived_at=NULL WHERE id=?", (item_id,))
    record_event(connection, "item", item_id, "restored")
    connection.commit()
    return {"id": item_id, "archived": False}
