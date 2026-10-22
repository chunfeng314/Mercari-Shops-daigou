from datetime import datetime, timezone
import json
import sqlite3
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.records import listing_draft_record
from app.schemas import ListingDefaultsUpdate, ListingDraftCreate, ListingPublishConfirmation
from app.workflow import require_transition
from app.audit import now_iso, record_event
from app.schemas_management import StockConfirmation, WithdrawalConfirmation
from app.listing_preparation import (
    attach_preparation_status, listing_requirements, prepare_listing,
    save_listing_preparation,
)


router = APIRouter(prefix="/api/listing", tags=["煤炉上架"])


@router.get("/requirements")
def read_listing_requirements() -> dict:
    return listing_requirements()


@router.get("/items/{item_id}/preparation")
def read_listing_preparation(item_id: str, source_id: str | None = None, connection: sqlite3.Connection = Depends(get_db)) -> dict:
    try:
        preparation = prepare_listing(connection, item_id, source_id)
        return attach_preparation_status(connection, item_id, preparation)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/items/{item_id}/preparation")
def regenerate_listing_preparation(item_id: str, source_id: str | None = None, connection: sqlite3.Connection = Depends(get_db)) -> dict:
    try:
        preparation = save_listing_preparation(connection, item_id, source_id, "manual_refresh")
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    connection.commit()
    preparation.pop("changed", None)
    return preparation


@router.get("/defaults")
def get_listing_defaults(connection: sqlite3.Connection = Depends(get_db)) -> dict:
    row = connection.execute("SELECT * FROM listing_defaults WHERE id = 1").fetchone()
    if row is None:
        raise HTTPException(status_code=500, detail="通用上架设置尚未初始化")
    return dict(row)


@router.put("/defaults")
def update_listing_defaults(
    payload: ListingDefaultsUpdate,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    values = payload.model_dump()
    for name in ("shipping_method", "shipping_payer", "shipping_origin", "handling_days"):
        values[name] = values[name].strip()
        if not values[name]:
            raise HTTPException(status_code=422, detail=f"{name} 不能为空")
    connection.execute(
        """UPDATE listing_defaults SET shipping_method = ?, shipping_payer = ?,
        shipping_origin = ?, handling_days = ?, mercari_fee_rate = ? WHERE id = 1""",
        (
            values["shipping_method"],
            values["shipping_payer"],
            values["shipping_origin"],
            values["handling_days"],
            values["mercari_fee_rate"],
        ),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM listing_defaults WHERE id = 1").fetchone()
    return dict(row)


def validate_reservation_dates(payload: ListingDraftCreate) -> None:
    if not payload.reservation_sale:
        return
    required_dates = (
        payload.reservation_start_date,
        payload.reservation_end_date,
        payload.reservation_release_date,
        payload.reservation_cancel_deadline,
    )
    if any(value is None for value in required_dates):
        raise HTTPException(status_code=422, detail="预约销售需要填写完整的预约日期")
    today_japan = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    if payload.reservation_start_date <= today_japan:
        raise HTTPException(status_code=422, detail="预约开始日必须晚于今天")
    if payload.reservation_end_date < payload.reservation_start_date:
        raise HTTPException(status_code=422, detail="预约结束日不能早于预约开始日")
    if payload.reservation_release_date <= payload.reservation_start_date:
        raise HTTPException(status_code=422, detail="发售日必须晚于预约开始日")
    if payload.reservation_end_date >= payload.reservation_release_date:
        raise HTTPException(status_code=422, detail="预约结束日必须早于发售日")
    if not payload.reservation_start_date <= payload.reservation_cancel_deadline <= payload.reservation_release_date:
        raise HTTPException(status_code=422, detail="取消期限需要在预约开始日与发售日之间")
    try:
        latest_release_date = payload.reservation_start_date.replace(
            year=payload.reservation_start_date.year + 2
        )
    except ValueError:
        latest_release_date = payload.reservation_start_date.replace(
            year=payload.reservation_start_date.year + 2, day=28
        )
    if payload.reservation_release_date > latest_release_date:
        raise HTTPException(status_code=422, detail="发售日需在预约开始日起两年内")


@router.post("/items/{item_id}/drafts", status_code=201)
def create_listing_draft(
    item_id: str,
    payload: ListingDraftCreate,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    return save_listing_draft(item_id, payload, connection)


@router.put("/drafts/{draft_id}")
def update_listing_draft(
    draft_id: str,
    payload: ListingDraftCreate,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    draft = connection.execute("SELECT * FROM listing_drafts WHERE id = ?", (draft_id,)).fetchone()
    if draft is None:
        raise HTTPException(status_code=404, detail="未找到上架草稿")
    if draft["status"] != "draft":
        raise HTTPException(status_code=409, detail="已发布商品不能修改上架草稿")
    return save_listing_draft(draft["item_id"], payload, connection, draft_id=draft_id)


def save_listing_draft(
    item_id: str,
    payload: ListingDraftCreate,
    connection: sqlite3.Connection,
    draft_id: str | None = None,
) -> dict:
    item = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise HTTPException(status_code=404, detail="未找到商品")
    if item["archived_at"]:
        raise HTTPException(409, "请先恢复已归档商品")
    if item["status"] != ("listing_draft" if draft_id else "matched"):
        raise HTTPException(status_code=409, detail="请先确认中国货源与日本商品同款")

    validate_reservation_dates(payload)
    if (
        payload.max_quantity_per_order is not None
        and payload.max_quantity_per_order > payload.inventory_quantity
    ):
        raise HTTPException(status_code=422, detail="每单限购数量不能大于煤炉商品库存")
    if not payload.image_asset_ids and not payload.image_refs:
        raise HTTPException(status_code=422, detail="请至少附加一张商品图片")

    source = connection.execute(
        """SELECT * FROM china_sources
        WHERE id = ? AND item_id = ? AND match_status = 'confirmed'
          AND price_cny IS NOT NULL AND archived_at IS NULL""",
        (
            payload.china_source_id,
            item_id,
        ),
    ).fetchone()
    if source is None:
        raise HTTPException(
            status_code=409,
            detail="货源需确认与日本商品同款并记录中国网站价格",
        )

    if payload.image_asset_ids:
        image_ids = payload.image_asset_ids
        if len(set(image_ids)) != len(image_ids):
            raise HTTPException(status_code=422, detail="商品图片不能重复选择")
        placeholders = ",".join("?" for _ in image_ids)
        image_count = connection.execute(
            f"SELECT COUNT(*) FROM source_images WHERE source_id = ? AND excluded_at IS NULL AND id IN ({placeholders})",
            (payload.china_source_id, *image_ids),
        ).fetchone()[0]
        if image_count != len(image_ids):
            raise HTTPException(status_code=422, detail="图片必须来自本次确认的中国货源，且未被排除")

    if draft_id is None:
        require_transition(item["status"], "listing_draft")
    estimated_profit_cny = estimated_margin_pct = None
    cost_inputs = (payload.exchange_rate_cny_per_jpy, payload.shipping_jpy,
                   payload.other_costs_jpy, payload.estimated_china_to_japan_shipping_cny)
    if all(value is not None for value in cost_inputs):
        sale_revenue_cny = payload.price_jpy * payload.exchange_rate_cny_per_jpy
        estimated_costs_cny = (
            payload.price_jpy * payload.mercari_fee_rate
            + payload.shipping_jpy + payload.other_costs_jpy
        ) * payload.exchange_rate_cny_per_jpy + source["price_cny"]
        estimated_costs_cny += payload.estimated_china_to_japan_shipping_cny
        estimated_profit_cny = round(sale_revenue_cny - estimated_costs_cny, 2)
        estimated_margin_pct = round(estimated_profit_cny / sale_revenue_cny * 100, 2)
    # Only schema-owned field names are interpolated; user values stay parameterized.
    values = payload.model_dump(mode="json")
    for name in ("image_refs", "image_asset_ids", "inventory_variants", "category_attributes"):
        values[name] = json.dumps(values[name], ensure_ascii=False)
    for name in ("reservation_release_date", "reservation_start_date", "reservation_end_date", "reservation_cancel_deadline"):
        values[name] = values[name] or ""
    for name in ("reservation_sale", "multi_variant"):
        values[name] = int(values[name])
    values.update(
        estimated_source_price_cny=source["price_cny"],
        source_checked_at=source["availability_checked_at"],
        estimated_profit_cny=estimated_profit_cny,
        estimated_margin_pct=estimated_margin_pct,
    )
    is_update = draft_id is not None
    if draft_id:
        assignments = ", ".join(f"{name} = ?" for name in values)
        connection.execute(f"UPDATE listing_drafts SET {assignments} WHERE id = ?", (*values.values(), draft_id))
    else:
        draft_id = uuid.uuid4().hex
        values.update(id=draft_id, item_id=item_id, status="draft", created_at=datetime.now(timezone.utc).isoformat())
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        connection.execute(f"INSERT INTO listing_drafts ({columns}) VALUES ({placeholders})", tuple(values.values()))
    connection.execute("UPDATE items SET status = 'listing_draft' WHERE id = ?", (item_id,))
    record_event(connection, "item", item_id, "draft_updated" if is_update else "draft_created", {"draft_id": draft_id, "price_jpy": payload.price_jpy, "estimated_profit_cny": estimated_profit_cny})
    connection.commit()
    return listing_draft_record(
        connection.execute("SELECT * FROM listing_drafts WHERE id = ?", (draft_id,)).fetchone()
    )


@router.post("/drafts/{draft_id}/publish-confirmation")
def confirm_published_listing(
    draft_id: str,
    payload: ListingPublishConfirmation,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    draft = connection.execute(
        "SELECT * FROM listing_drafts WHERE id = ?", (draft_id,)
    ).fetchone()
    if draft is None:
        raise HTTPException(status_code=404, detail="未找到上架草稿")
    item = connection.execute("SELECT * FROM items WHERE id = ?", (draft["item_id"],)).fetchone()
    if draft["status"] != "draft" or item["status"] != "listing_draft":
        raise HTTPException(status_code=409, detail="当前草稿不能登记为已发布")

    require_transition(item["status"], "listed")
    published_at = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """UPDATE listing_drafts SET status = 'listed', listing_url = ?, published_at = ?
        WHERE id = ?""",
        (payload.listing_url, published_at, draft_id),
    )
    connection.execute("UPDATE items SET status = 'listed' WHERE id = ?", (item["id"],))
    record_event(connection, "item", item["id"], "listing_published", {"listing_url": payload.listing_url})
    connection.commit()
    return listing_draft_record(
        connection.execute("SELECT * FROM listing_drafts WHERE id = ?", (draft_id,)).fetchone()
    )


@router.post("/drafts/{draft_id}/inventory-confirmation")
def confirm_shop_stock(draft_id: str, payload: StockConfirmation, connection: sqlite3.Connection = Depends(get_db)) -> dict:
    connection.execute("BEGIN IMMEDIATE")
    draft = connection.execute("SELECT * FROM listing_drafts WHERE id=?", (draft_id,)).fetchone()
    if draft is None:
        raise HTTPException(404, "未找到上架记录")
    if draft["status"] != "listed":
        raise HTTPException(409, "仅能回填已上架商品的店铺库存")
    if not payload.note.strip():
        raise HTTPException(422, "请填写库存核对依据")
    occupied = connection.execute("SELECT COALESCE(SUM(quantity),0) FROM sales_orders WHERE listing_draft_id=? AND inventory_released=0", (draft_id,)).fetchone()[0]
    connection.execute("UPDATE listing_drafts SET inventory_quantity=? WHERE id=?", (occupied + payload.remaining_quantity, draft_id))
    record_event(connection, "item", draft["item_id"], "inventory_confirmed", {"occupied_quantity": occupied, **payload.model_dump()})
    connection.commit()
    return listing_draft_record(connection.execute("SELECT * FROM listing_drafts WHERE id=?", (draft_id,)).fetchone())


@router.post("/drafts/{draft_id}/withdrawal-confirmation")
def confirm_withdrawal(draft_id: str, payload: WithdrawalConfirmation, connection: sqlite3.Connection = Depends(get_db)) -> dict:
    connection.execute("BEGIN IMMEDIATE")
    draft = connection.execute("SELECT * FROM listing_drafts WHERE id=?", (draft_id,)).fetchone()
    if draft is None:
        raise HTTPException(404, "未找到上架记录")
    if draft["status"] != "listed":
        raise HTTPException(409, "仅能登记已上架商品的实际下架结果")
    if not payload.reason.strip():
        raise HTTPException(422, "请填写下架原因")
    connection.execute("UPDATE listing_drafts SET status='withdrawn' WHERE id=?", (draft_id,))
    connection.execute("UPDATE items SET status='withdrawn' WHERE id=?", (draft["item_id"],))
    record_event(connection, "item", draft["item_id"], "withdrawn", payload.model_dump())
    connection.commit()
    return listing_draft_record(connection.execute("SELECT * FROM listing_drafts WHERE id=?", (draft_id,)).fetchone())
