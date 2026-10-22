from datetime import datetime, timezone
import sqlite3
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.audit import entity_events, now_iso, record_event
from app.schemas_management import OrderCancellation, OrderReturnReceipt, RefundConfirmation
from app.schemas import (
    OrderChinaShipment,
    OrderDomesticShipment,
    OrderJapanReceipt,
    OrderPurchaseConfirmation,
    SalesOrderCreate,
)


router = APIRouter(prefix="/api/orders", tags=["订单采购与日本国内履约"])


def get_order(connection: sqlite3.Connection, order_id: str, active: bool = True, lock: bool = True) -> sqlite3.Row:
    if lock and not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")
    order = connection.execute("SELECT * FROM sales_orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        raise HTTPException(status_code=404, detail="未找到煤炉订单")
    if active and order["order_status"] != "active":
        raise HTTPException(409, "订单已取消，不能继续采购或发货")
    return order


@router.post("", status_code=201)
def create_sales_order(
    payload: SalesOrderCreate,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    return save_sales_order(payload, connection)


def save_sales_order(payload: SalesOrderCreate, connection: sqlite3.Connection, commit: bool = True) -> dict:
    if not connection.in_transaction:
        connection.execute("BEGIN IMMEDIATE")
    item = connection.execute(
        "SELECT * FROM items WHERE id = ?", (payload.item_id,)
    ).fetchone()
    if item is None:
        raise HTTPException(status_code=404, detail="未找到商品")
    if item["status"] != "listed" or item["archived_at"]:
        raise HTTPException(status_code=409, detail="只有已发布商品才能登记店铺订单")

    draft = connection.execute(
        "SELECT * FROM listing_drafts WHERE item_id = ? AND status = 'listed'",
        (payload.item_id,),
    ).fetchone()
    if draft is None:
        raise HTTPException(status_code=409, detail="没有已发布的上架记录")
    already_reserved = connection.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM sales_orders WHERE listing_draft_id = ? AND inventory_released = 0",
        (draft["id"],),
    ).fetchone()[0]
    if already_reserved + payload.quantity > draft["inventory_quantity"]:
        raise HTTPException(status_code=409, detail="订单数量超过剩余预约库存")
    if (
        draft["max_quantity_per_order"] is not None
        and payload.quantity > draft["max_quantity_per_order"]
    ):
        raise HTTPException(status_code=409, detail="订单数量超过每单限购数量")

    order_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        connection.execute(
            """INSERT INTO sales_orders
            (id, mercari_order_id, item_id, listing_draft_id, china_source_id,
             quantity, sold_price_jpy, fulfillment_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'awaiting_purchase', ?)""",
            (
                order_id,
                payload.mercari_order_id,
                payload.item_id,
                draft["id"],
                draft["china_source_id"],
                payload.quantity,
                payload.sold_price_jpy,
                created_at,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="该煤炉订单号已登记") from exc
    record_event(connection, "order", order_id, "created", {"quantity": payload.quantity, "sold_price_jpy": payload.sold_price_jpy})
    if commit:
        connection.commit()
    return dict(connection.execute("SELECT * FROM sales_orders WHERE id = ?", (order_id,)).fetchone())


@router.get("")
def list_sales_orders(
    connection: sqlite3.Connection = Depends(get_db),
) -> list[dict]:
    rows = connection.execute(
        "SELECT o.*, (SELECT COALESCE(SUM(r.amount_jpy),0) FROM order_refunds r WHERE r.order_id=o.id) AS refunded_amount_jpy FROM sales_orders o ORDER BY o.created_at DESC"
    ).fetchall()
    return [dict(row) for row in rows]


@router.post("/{order_id}/purchase-confirmation")
def confirm_order_purchase(
    order_id: str,
    payload: OrderPurchaseConfirmation,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    order = get_order(connection, order_id)
    if order["fulfillment_status"] != "awaiting_purchase":
        raise HTTPException(status_code=409, detail="该订单已记录采购结果")

    source = connection.execute(
        """SELECT * FROM china_sources
        WHERE id = ? AND item_id = ? AND match_status = 'confirmed'
          AND archived_at IS NULL
        """,
        (
            payload.china_source_id,
            order["item_id"],
        ),
    ).fetchone()
    if source is None:
        raise HTTPException(status_code=409, detail="请选用已确认与日本商品同款的中国货源")

    purchased_at = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """UPDATE sales_orders SET china_source_id = ?, actual_purchase_price_cny = ?,
           actual_china_to_japan_shipping_cny = ?, fulfillment_status = 'purchased',
           purchased_at = ? WHERE id = ?""",
        (
            payload.china_source_id,
            payload.actual_price_cny,
            payload.actual_china_to_japan_shipping_cny,
            purchased_at,
            order_id,
        ),
    )
    record_event(connection, "order", order_id, "purchase_confirmed", payload.model_dump())
    connection.commit()
    return dict(connection.execute("SELECT * FROM sales_orders WHERE id = ?", (order_id,)).fetchone())


@router.post("/{order_id}/china-shipment")
def record_china_shipment(
    order_id: str,
    payload: OrderChinaShipment,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    order = get_order(connection, order_id)
    if order["fulfillment_status"] != "purchased":
        raise HTTPException(status_code=409, detail="请先登记中国采购结果")
    if order["inbound_status"] != "awaiting_dispatch":
        raise HTTPException(status_code=409, detail="当前订单不能重复登记国内到日本段发货")

    shipped_at = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """UPDATE sales_orders SET inbound_status = 'in_transit', china_carrier = ?,
           china_tracking_number = ?, china_shipped_at = ? WHERE id = ?""",
        (payload.carrier, payload.tracking_number, shipped_at, order_id),
    )
    record_event(connection, "order", order_id, "china_shipment", payload.model_dump())
    connection.commit()
    return dict(connection.execute("SELECT * FROM sales_orders WHERE id = ?", (order_id,)).fetchone())


@router.post("/{order_id}/japan-receipt")
def record_japan_receipt(
    order_id: str,
    payload: OrderJapanReceipt,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    order = get_order(connection, order_id)
    if order["inbound_status"] not in ("in_transit", "inspection_issue"):
        raise HTTPException(status_code=409, detail="商品需先从中国发往日本")

    received_at = datetime.now(timezone.utc).isoformat()
    inbound_status = "received" if payload.inspection_result == "passed" else "inspection_issue"
    connection.execute(
        """UPDATE sales_orders SET inbound_status = ?, received_at_japan = ?,
           inspection_result = ?, inspection_note = ? WHERE id = ?""",
        (inbound_status, received_at, payload.inspection_result, payload.inspection_note, order_id),
    )
    record_event(connection, "order", order_id, "japan_receipt", payload.model_dump())
    connection.commit()
    return dict(connection.execute("SELECT * FROM sales_orders WHERE id = ?", (order_id,)).fetchone())


@router.post("/{order_id}/domestic-shipment")
def record_domestic_shipment(
    order_id: str,
    payload: OrderDomesticShipment,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    order = get_order(connection, order_id)
    if order["inbound_status"] != "received" or order["inspection_result"] != "passed":
        raise HTTPException(status_code=409, detail="商品到日本并通过验收后才能发给买家")
    if order["domestic_status"] != "not_shipped":
        raise HTTPException(status_code=409, detail="该订单已登记日本境内发货")

    shipped_at = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """UPDATE sales_orders SET domestic_status = 'shipped', japan_carrier = ?,
           japan_tracking_number = ?, shipped_to_buyer_at = ? WHERE id = ?""",
        (payload.carrier, payload.tracking_number, shipped_at, order_id),
    )
    record_event(connection, "order", order_id, "domestic_shipment", payload.model_dump())
    connection.commit()
    return dict(connection.execute("SELECT * FROM sales_orders WHERE id = ?", (order_id,)).fetchone())


@router.post("/{order_id}/delivery-confirmation")
def confirm_delivery(
    order_id: str,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    order = get_order(connection, order_id)
    if order["domestic_status"] != "shipped":
        raise HTTPException(status_code=409, detail="请先登记日本境内发货")

    delivered_at = datetime.now(timezone.utc).isoformat()
    connection.execute(
        "UPDATE sales_orders SET domestic_status = 'delivered', delivered_at = ? WHERE id = ?",
        (delivered_at, order_id),
    )
    record_event(connection, "order", order_id, "delivered")
    connection.commit()
    return dict(connection.execute("SELECT * FROM sales_orders WHERE id = ?", (order_id,)).fetchone())


@router.get("/{order_id}")
def read_order(order_id: str, connection: sqlite3.Connection = Depends(get_db)) -> dict:
    order = dict(get_order(connection, order_id, active=False, lock=False))
    order["events"] = entity_events(connection, "order", order_id)
    order["refunds"] = [dict(row) for row in connection.execute("SELECT * FROM order_refunds WHERE order_id=? ORDER BY created_at", (order_id,))]
    order["refunded_amount_jpy"] = sum(refund["amount_jpy"] for refund in order["refunds"])
    return order


@router.post("/{order_id}/cancellation")
def cancel_order(order_id: str, payload: OrderCancellation, connection: sqlite3.Connection = Depends(get_db)) -> dict:
    order = get_order(connection, order_id)
    if order["domestic_status"] in ("shipped", "delivered") and not order["return_received_at"]:
        raise HTTPException(409, "商品已发给买家，请先登记退货收货再取消")
    connection.execute("UPDATE sales_orders SET order_status='cancelled', cancel_reason=?, cancelled_at=?, inventory_released=? WHERE id=?", (payload.reason, now_iso(), int(payload.release_inventory), order_id))
    record_event(connection, "order", order_id, "cancelled", payload.model_dump())
    connection.commit()
    return read_order(order_id, connection)


@router.post("/{order_id}/return-receipt")
def confirm_return(order_id: str, payload: OrderReturnReceipt, connection: sqlite3.Connection = Depends(get_db)) -> dict:
    order = get_order(connection, order_id, active=False)
    if order["domestic_status"] not in ("shipped", "delivered"):
        raise HTTPException(409, "尚未向买家发货，无需登记买家退货")
    if order["return_received_at"]:
        raise HTTPException(409, "已登记退货收货")
    if not payload.note.strip():
        raise HTTPException(422, "请填写退货收货与检查记录")
    connection.execute("UPDATE sales_orders SET return_received_at=?,return_note=? WHERE id=?", (now_iso(), payload.note.strip(), order_id))
    record_event(connection, "order", order_id, "return_received", payload.model_dump())
    connection.commit()
    return read_order(order_id, connection)


@router.post("/{order_id}/refund-confirmation")
def confirm_refund(order_id: str, payload: RefundConfirmation, connection: sqlite3.Connection = Depends(get_db)) -> dict:
    order = get_order(connection, order_id, active=False)
    existing = connection.execute("SELECT * FROM order_refunds WHERE refund_reference=?", (payload.refund_reference,)).fetchone()
    if existing:
        if existing["order_id"] == order_id and existing["amount_jpy"] == payload.amount_jpy and existing["reason"] == payload.reason:
            connection.rollback()
            return read_order(order_id, connection)
        raise HTTPException(409, "退款流水号已用于其他退款记录")
    total = connection.execute("SELECT COALESCE(SUM(amount_jpy),0) FROM order_refunds WHERE order_id=?", (order_id,)).fetchone()[0]
    if total + payload.amount_jpy > order["sold_price_jpy"]:
        raise HTTPException(422, "累计退款金额不能超过订单成交金额")
    connection.execute("INSERT INTO order_refunds (id,order_id,refund_reference,amount_jpy,reason,created_at) VALUES (?,?,?,?,?,?)", (uuid.uuid4().hex, order_id, payload.refund_reference, payload.amount_jpy, payload.reason, now_iso()))
    record_event(connection, "order", order_id, "refund_recorded", payload.model_dump())
    connection.commit()
    return read_order(order_id, connection)
