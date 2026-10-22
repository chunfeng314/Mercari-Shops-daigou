from datetime import datetime, timezone
import sqlite3
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request

from app.db import get_db
from app.schemas import ChinaSourceConfirmation, ChinaSourceCreate
from app.site_catalog import CHINA_SITE_IDS, CHINA_SITES
from app.workflow import require_transition
from app.audit import now_iso, record_event
from app.listing_preparation import save_listing_preparation
from app.schemas_management import SourceUpdate
from app.schemas_automation import ChinaSearch
from app.automation.store import enqueue
from app.modules.china_sourcing.keywords import plan_search_queries


router = APIRouter(prefix="/api/china", tags=["中国网站找货"])


@router.get("/sites")
def list_china_sites() -> list[dict]:
    return CHINA_SITES


@router.post("/search", status_code=202)
def search_xianyu(
    payload: ChinaSearch,
    request: Request,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    item = connection.execute("SELECT * FROM items WHERE id=?", (payload.item_id,)).fetchone()
    if item is None:
        raise HTTPException(404, "未找到日本商品候选")
    if item["archived_at"]:
        raise HTTPException(409, "请先恢复已归档商品")
    queries = plan_search_queries(item["japan_title"], item["note"])
    if not queries:
        raise HTTPException(422, "日本平台采集资料不足以生成闲鱼搜索词；请先补全日本商品标题或说明")
    connection.execute("BEGIN IMMEDIATE")
    job = enqueue(connection, "china_search", {
        "site_id": "xianyu", "item_id": item["id"], "item_title": item["japan_title"],
        "queries": queries, "browser_channel": payload.browser_channel, "limit": payload.limit,
        "browser_mode": payload.browser_mode,
    })
    connection.commit()
    request.app.state.automation.wake.set()
    return job


@router.post("/items/{item_id}/sources", status_code=201)
def add_source(
    item_id: str,
    payload: ChinaSourceCreate,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    item = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise HTTPException(status_code=404, detail="未找到日本商品候选")
    if payload.china_site not in CHINA_SITE_IDS:
        raise HTTPException(status_code=422, detail="未知的中国找货站点")
    if item["archived_at"]:
        raise HTTPException(409, "请先恢复已归档商品")
    if item["status"] == "candidate":
        require_transition(item["status"], "sourcing")
        connection.execute("UPDATE items SET status = 'sourcing' WHERE id = ?", (item_id,))
    elif item["status"] not in ("sourcing", "matched", "listing_draft", "listed", "withdrawn"):
        raise HTTPException(status_code=409, detail="当前商品状态不能添加货源候选")

    source_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """INSERT INTO china_sources
        (id, item_id, china_site, source_url, source_title, price_cny,
         account_note, match_status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (
            source_id,
            item_id,
            payload.china_site,
            payload.source_url,
            payload.source_title,
            payload.price_cny,
            payload.account_note,
            created_at,
        ),
    )
    record_event(connection, "item", item_id, "source_added", {"source_id": source_id, "source_url": payload.source_url})
    connection.commit()
    return dict(connection.execute("SELECT * FROM china_sources WHERE id = ?", (source_id,)).fetchone())


@router.get("/items/{item_id}/sources")
def list_sources(
    item_id: str,
    connection: sqlite3.Connection = Depends(get_db),
) -> list[dict]:
    item = connection.execute("SELECT id FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        raise HTTPException(status_code=404, detail="未找到日本商品候选")
    rows = connection.execute(
        "SELECT * FROM china_sources WHERE item_id = ? AND archived_at IS NULL ORDER BY created_at DESC",
        (item_id,),
    ).fetchall()
    return [dict(row) for row in rows]


@router.post("/sources/{source_id}/confirm")
def confirm_source(
    source_id: str,
    payload: ChinaSourceConfirmation,
    connection: sqlite3.Connection = Depends(get_db),
) -> dict:
    source = connection.execute(
        "SELECT * FROM china_sources WHERE id = ?", (source_id,)
    ).fetchone()
    if source is None:
        raise HTTPException(status_code=404, detail="未找到中国货源候选")
    item = connection.execute(
        "SELECT * FROM items WHERE id = ?", (source["item_id"],)
    ).fetchone()
    if source["archived_at"] or item["archived_at"]:
        raise HTTPException(409, "请先恢复已归档商品或货源")
    if item["status"] not in ("sourcing", "matched", "listing_draft", "listed", "withdrawn"):
        raise HTTPException(status_code=409, detail="当前商品状态不能确认货源")

    match_note = payload.match_note.strip()
    if not match_note:
        raise HTTPException(status_code=422, detail="请填写同款或供货核验依据")
    checked_at = datetime.now(timezone.utc).isoformat()
    price_cny = payload.price_cny if payload.price_cny is not None else source["price_cny"]
    if payload.availability_status == "available" and price_cny is None:
        raise HTTPException(status_code=422, detail="确认可供货时请填写当前货源价格")
    if payload.availability_commitment:
        if payload.availability_status != "available":
            raise HTTPException(status_code=422, detail="只有当前有货的货源才能登记供货承诺")
        if payload.committed_quantity is None or payload.commitment_valid_until is None:
            raise HTTPException(status_code=422, detail="供货承诺需要填写承诺数量和有效日期")
        today_japan = datetime.now(ZoneInfo("Asia/Tokyo")).date()
        if payload.commitment_valid_until < today_japan:
            raise HTTPException(status_code=422, detail="供货承诺有效日期不能早于今天")

    committed_quantity = payload.committed_quantity if payload.availability_commitment else 0
    commitment_valid_until = (
        payload.commitment_valid_until.isoformat() if payload.availability_commitment else None
    )

    if item["status"] == "sourcing":
        require_transition(item["status"], "matched")
    connection.execute(
        """UPDATE china_sources SET match_status = 'confirmed', match_note = ?,
           availability_status = ?, availability_commitment = ?, committed_quantity = ?,
           commitment_valid_until = ?, availability_checked_at = ?,
           price_cny = COALESCE(?, price_cny)
           WHERE id = ?""",
        (
            match_note,
            payload.availability_status,
            int(payload.availability_commitment),
            committed_quantity,
            commitment_valid_until,
            checked_at,
            price_cny,
            source_id,
        ),
    )
    if item["status"] == "sourcing":
        connection.execute("UPDATE items SET status = 'matched' WHERE id = ?", (item["id"],))
    record_event(connection, "item", item["id"], "source_confirmed", {"source_id": source_id, "price_cny": price_cny, "availability_status": payload.availability_status, "match_note": match_note})
    preparation = None
    if item["status"] in ("sourcing", "matched"):
        preparation = save_listing_preparation(connection, item["id"], source_id, "source_confirmed")
        preparation.pop("changed", None)
    connection.commit()
    result = dict(connection.execute("SELECT * FROM china_sources WHERE id = ?", (source_id,)).fetchone())
    if preparation is not None:
        result["listing_preparation"] = preparation
    return result


@router.patch("/sources/{source_id}")
def update_source(source_id: str, payload: SourceUpdate, connection: sqlite3.Connection = Depends(get_db)) -> dict:
    source = connection.execute("SELECT * FROM china_sources WHERE id=?", (source_id,)).fetchone()
    if source is None:
        raise HTTPException(404, "未找到中国货源")
    if source["archived_at"]:
        raise HTTPException(409, "请先恢复已归档货源")
    if connection.execute("SELECT archived_at FROM items WHERE id=?", (source["item_id"],)).fetchone()["archived_at"]:
        raise HTTPException(409, "请先恢复已归档商品")
    values = payload.model_dump(exclude_unset=True)
    identity_changed = any(name in values and values[name] != source[name] for name in ("source_url", "source_title"))
    used = connection.execute("SELECT 1 FROM listing_drafts WHERE china_source_id=? UNION SELECT 1 FROM sales_orders WHERE china_source_id=? LIMIT 1", (source_id, source_id)).fetchone()
    if identity_changed and used:
        raise HTTPException(409, "该货源已用于上架或采购，更换商品请新增货源；可修改价格和备注")
    if values:
        assignments = ",".join(f"{name}=?" for name in values)
        connection.execute(f"UPDATE china_sources SET {assignments} WHERE id=?", (*values.values(), source_id))
        if identity_changed:
            connection.execute("UPDATE china_sources SET match_status='pending', availability_status='unknown', availability_checked_at=NULL, availability_commitment=0, committed_quantity=0, commitment_valid_until=NULL WHERE id=?", (source_id,))
            connection.execute("UPDATE items SET status='sourcing' WHERE id=? AND status='matched' AND NOT EXISTS (SELECT 1 FROM china_sources WHERE item_id=? AND match_status='confirmed' AND archived_at IS NULL)", (source["item_id"], source["item_id"]))
        record_event(connection, "item", source["item_id"], "source_updated", {"source_id": source_id, "changes": values})
        connection.commit()
    return dict(connection.execute("SELECT * FROM china_sources WHERE id=?", (source_id,)).fetchone())


@router.post("/sources/{source_id}/archive")
@router.delete("/sources/{source_id}", summary="归档未使用货源（可恢复）")
def archive_source(source_id: str, connection: sqlite3.Connection = Depends(get_db)) -> dict:
    source = connection.execute("SELECT * FROM china_sources WHERE id=?", (source_id,)).fetchone()
    if source is None:
        raise HTTPException(404, "未找到中国货源")
    used = connection.execute("SELECT 1 FROM listing_drafts WHERE china_source_id=? UNION SELECT 1 FROM sales_orders WHERE china_source_id=? LIMIT 1", (source_id, source_id)).fetchone()
    if used:
        raise HTTPException(409, "货源已用于上架或采购，需保留履约记录")
    connection.execute("UPDATE china_sources SET archived_at=? WHERE id=?", (now_iso(), source_id))
    connection.execute("UPDATE items SET status='sourcing' WHERE id=? AND status='matched' AND NOT EXISTS (SELECT 1 FROM china_sources WHERE item_id=? AND match_status='confirmed' AND archived_at IS NULL)", (source["item_id"], source["item_id"]))
    record_event(connection, "item", source["item_id"], "source_archived", {"source_id": source_id})
    connection.commit()
    return {"id": source_id, "archived": True}


@router.post("/sources/{source_id}/restore")
def restore_source(source_id: str, connection: sqlite3.Connection = Depends(get_db)) -> dict:
    source = connection.execute("SELECT * FROM china_sources WHERE id=?", (source_id,)).fetchone()
    if source is None:
        raise HTTPException(404, "未找到中国货源")
    connection.execute("UPDATE china_sources SET archived_at=NULL WHERE id=?", (source_id,))
    if source["match_status"] == "confirmed":
        connection.execute("UPDATE items SET status='matched' WHERE id=? AND status='sourcing'", (source["item_id"],))
    record_event(connection, "item", source["item_id"], "source_restored", {"source_id": source_id})
    connection.commit()
    return {"id": source_id, "archived": False}
