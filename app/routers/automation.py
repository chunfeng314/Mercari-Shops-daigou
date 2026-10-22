from datetime import datetime, timezone
import json
import os
import sqlite3
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.audit import now_iso, record_event
from app.automation.store import TERMINAL, WAITING, enqueue, job_record, schedule_next
from app.db import get_db
from app.config import settings
from app.modules.japan_selection.mercari import canonical_url, has_eligible_jpy_price, validate_mercari_url
from app.modules.china_sourcing.xianyu import validate_item_url as validate_xianyu_item_url
from app.modules.mercari_listing.browser_adapter import validate_shop_management_url
from app.routers.orders import save_sales_order
from app.workflow import require_transition
from app.schemas import SalesOrderCreate
from app.schemas_automation import (
    BrowserSessionTask, ImportSelection, JapanCollection, JapanSearch, ShopBrowserSettings, ShopOrderMapping, ShopTask,
    WatchCreate, WatchUpdate,
)
from app.browser.shop_connection import shop_root


router = APIRouter(tags=["采集、监控与店铺浏览器"])


def checked_url(url, kind):
    try:
        return validate_mercari_url(url, kind)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


def create_job(request, connection, kind, payload, watch_id=None):
    connection.execute("BEGIN IMMEDIATE")
    if kind == "shop_fill_draft":
        pending = connection.execute("SELECT * FROM automation_jobs WHERE kind=? AND status IN ('queued','running','waiting_login','waiting_review')", (kind,)).fetchall()
        for row in pending:
            if json.loads(row["payload"]).get("draft_id") == payload["draft_id"]:
                connection.commit()
                return job_record(row)
    if kind == "china_image_review":
        pending = connection.execute("SELECT * FROM automation_jobs WHERE kind=? AND status IN ('queued','running')", (kind,)).fetchall()
        for row in pending:
            if json.loads(row["payload"]).get("source_id") == payload["source_id"]:
                connection.commit()
                return job_record(row)
    if connection.execute("SELECT COUNT(*) FROM automation_jobs WHERE status='queued'").fetchone()[0] >= 30:
        raise HTTPException(409, "待执行任务较多，请等待或取消不需要的任务")
    job = enqueue(connection, kind, payload, watch_id)
    connection.commit()
    request.app.state.automation.wake.set()
    return job


@router.post("/api/japan/search", status_code=202)
def search_japan(payload: JapanSearch, request: Request, connection: sqlite3.Connection = Depends(get_db)):
    return create_job(request, connection, "japan_search", payload.model_dump())


@router.post("/api/japan/collect/item", status_code=202)
def collect_item(payload: JapanCollection, request: Request, connection: sqlite3.Connection = Depends(get_db)):
    values = payload.model_dump()
    values["url"] = checked_url(values["url"], "item")
    return create_job(request, connection, "japan_item", values)


@router.post("/api/japan/collect/shop", status_code=202)
def collect_shop(payload: JapanCollection, request: Request, connection: sqlite3.Connection = Depends(get_db)):
    values = payload.model_dump()
    values["url"] = checked_url(values["url"], "shop")
    return create_job(request, connection, "japan_shop", values)


@router.post("/api/china/sources/{source_id}/image-review", status_code=202)
def review_china_source_images(source_id: str, request: Request, connection: sqlite3.Connection = Depends(get_db)):
    if not settings.image_review_enabled or not settings.dashscope_api_key.strip():
        raise HTTPException(409, "千问图片筛选未启用或未配置 DASHSCOPE_API_KEY")
    source = connection.execute(
        "SELECT id,item_id FROM china_sources WHERE id=? AND archived_at IS NULL", (source_id,)
    ).fetchone()
    if source is None:
        raise HTTPException(404, "货源不存在或已归档")
    return create_job(request, connection, "china_image_review", {
        "source_id": source["id"], "item_id": source["item_id"],
    })


@router.get("/api/automation/status")
def automation_status(request: Request):
    service = request.app.state.automation
    return {"worker_running": bool(service.thread and service.thread.is_alive()),
            "temporary_shop_session": service.shop_page is not None and service.shop_mode == "temporary",
            "shop_session_active": service.shop_page is not None,
            "shop_browser_mode": service.shop_mode,
            "supported_collection_sites": ["mercari", "xianyu"], "ai_enabled": False,
            "image_review_enabled": settings.image_review_enabled,
            "image_review_configured": bool(settings.dashscope_api_key.strip()),
            "image_review_model": settings.qwen_vl_model if settings.image_review_enabled and settings.dashscope_api_key.strip() else None,
            "supported_scheduled_tasks": ["japan_search", "japan_shop", "listing_prepare"],
            "monitor_requires_running_app": True, "credentials_persisted": False,
            "managed_browser_sessions": service.managed_browser.status(),
            "managed_browser_requires_control_prompt": False,
            "shop_adapter_requires_live_verification": True}


@router.post("/api/automation/browser/open", status_code=202)
def open_managed_browser(payload: BrowserSessionTask, request: Request, connection: sqlite3.Connection = Depends(get_db)):
    return create_job(request, connection, "browser_session", payload.model_dump())


@router.post("/api/automation/browser/close", status_code=202)
def close_managed_browser(payload: BrowserSessionTask, request: Request, connection: sqlite3.Connection = Depends(get_db)):
    return create_job(request, connection, "browser_close", payload.model_dump())


@router.post("/api/automation/shops/cdp-browser/open", status_code=202)
def open_shop_cdp_browser(payload: ShopTask, request: Request, connection: sqlite3.Connection = Depends(get_db)):
    if os.name != "nt":
        raise HTTPException(501, "CDP 登录浏览器启动目前仅支持 Windows 工作台")
    requested = ShopTask(url=payload.url, browser_mode="existing_chrome", browser_channel="chrome")
    values = checked_shop_task(requested, connection)
    if not values["url"]:
        raise HTTPException(422, "请先填写 Mercari Shops 店铺管理页面链接")
    connection.execute(
        "UPDATE shop_browser_settings SET browser_mode=?,browser_channel=?,url=? WHERE id=1",
        ("existing_chrome", "chrome", values["url"]),
    )
    connection.commit()
    shop_id = values["url"].rstrip("/").rsplit("/", 1)[-1]
    return create_job(request, connection, "shop_cdp_open", {
        "shop_id": shop_id,
        "url": values["url"],
        "browser_channel": "chrome",
    })


@router.get("/api/automation/shops/settings")
def shop_browser_settings(connection: sqlite3.Connection = Depends(get_db)):
    return dict(connection.execute("SELECT * FROM shop_browser_settings WHERE id=1").fetchone())


@router.put("/api/automation/shops/settings")
def save_shop_browser_settings(payload: ShopBrowserSettings, connection: sqlite3.Connection = Depends(get_db)):
    values = checked_shop_task(payload, connection)
    connection.execute("UPDATE shop_browser_settings SET browser_mode=?,browser_channel=?,url=? WHERE id=1", (values["browser_mode"], values["browser_channel"], values["url"]))
    connection.commit()
    return shop_browser_settings(connection)


def checked_shop_task(payload, connection):
    saved = shop_browser_settings(connection)
    values = {
        "url": payload.url.strip() or saved["url"],
        "browser_mode": payload.browser_mode or saved["browser_mode"],
        "browser_channel": payload.browser_channel or saved["browser_channel"],
    }
    try:
        if values["url"]:
            validate_shop_management_url(values["url"])
        if values["browser_mode"] == "existing_chrome" or (values["browser_mode"] == "managed" and values["url"]):
            values["url"] = shop_root(values["url"])
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    return values


@router.get("/api/automation/jobs")
def list_jobs(limit: int = Query(50, ge=1, le=200), connection: sqlite3.Connection = Depends(get_db)):
    return [job_record(row) for row in connection.execute("SELECT * FROM automation_jobs ORDER BY created_at DESC LIMIT ?", (limit,))]


@router.get("/api/automation/jobs/{job_id}")
def read_job(job_id: str, connection: sqlite3.Connection = Depends(get_db)):
    row = connection.execute("SELECT * FROM automation_jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "未找到任务")
    return job_record(row)


@router.post("/api/automation/jobs/{job_id}/resume")
def resume_job(job_id: str, request: Request, connection: sqlite3.Connection = Depends(get_db)):
    job = read_job(job_id, connection)
    if job["status"] not in WAITING:
        raise HTTPException(409, "该任务当前没有等待人工操作")
    try:
        request.app.state.automation.resume(job_id)
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    return {"id": job_id, "resuming": True}


@router.post("/api/automation/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request, connection: sqlite3.Connection = Depends(get_db)):
    connection.execute("BEGIN IMMEDIATE")
    job = read_job(job_id, connection)
    if job["status"] in TERMINAL:
        connection.rollback()
        return job
    connection.execute("UPDATE automation_jobs SET cancel_requested=1 WHERE id=?", (job_id,))
    if job["status"] == "queued":
        connection.execute("UPDATE automation_jobs SET status='cancelled',finished_at=?,progress='已取消' WHERE id=?", (now_iso(), job_id))
    connection.commit()
    request.app.state.automation.cancel(job_id)
    return read_job(job_id, connection)


@router.post("/api/automation/jobs/{job_id}/import")
def import_candidates(job_id: str, payload: ImportSelection, connection: sqlite3.Connection = Depends(get_db)):
    connection.execute("BEGIN IMMEDIATE")
    job = read_job(job_id, connection)
    if job["status"] != "succeeded" or not job["kind"].startswith("japan_"):
        raise HTTPException(409, "请等待日本采集任务成功后再导入")
    items = (job["result"] or {}).get("items", [])
    if len(set(payload.indexes)) != len(payload.indexes) or any(index < 0 or index >= len(items) for index in payload.indexes):
        raise HTTPException(422, "选择了无效或重复的商品索引")
    imported, skipped, images_updated = [], [], []
    for index in payload.indexes:
        item = items[index]
        url = canonical_url(checked_url(item["url"], "item"))
        existing = connection.execute("SELECT id,archived_at,japan_image_url FROM items WHERE japan_url=?", (url,)).fetchone()
        if existing:
            if not existing["japan_image_url"] and item.get("image_url"):
                connection.execute("UPDATE items SET japan_image_url=? WHERE id=?", (item["image_url"], existing["id"]))
                record_event(connection, "item", existing["id"], "japan_image_backfilled", {"job_id": job_id, "source_url": url})
                images_updated.append({"index": index, "id": existing["id"]})
            skipped.append({"index": index, "id": existing["id"], "archived": bool(existing["archived_at"])})
            continue
        if not has_eligible_jpy_price(item.get("price")):
            price = item.get("price")
            reason = "price_unavailable" if price is None else "price_below_minimum"
            skipped.append({"index": index, "reason": reason, "price": price})
            continue
        candidate_id = uuid.uuid4().hex
        note = f"Mercari 页面采集：{job['result'].get('collected_at', now_iso())}"
        if item.get("description"):
            note += "\n" + item["description"][:8000]
        connection.execute("INSERT INTO items (id,japan_site,japan_url,japan_title,japan_price_jpy,japan_image_url,note,status,created_at) VALUES (?,?,?,?,?,?,?,'candidate',?)",
                           (candidate_id, "mercari", url, item["title"][:500], item.get("price"), item.get("image_url"), note, now_iso()))
        record_event(connection, "item", candidate_id, "imported", {"job_id": job_id, "source_url": url})
        imported.append({"index": index, "id": candidate_id})
    connection.commit()
    return {"imported": imported, "skipped": skipped, "images_updated": images_updated}


@router.post("/api/automation/jobs/{job_id}/import-china-sources")
def import_china_sources(job_id: str, payload: ImportSelection, request: Request, connection: sqlite3.Connection = Depends(get_db)):
    connection.execute("BEGIN IMMEDIATE")
    job = read_job(job_id, connection)
    if job["status"] != "succeeded" or job["kind"] != "china_search":
        raise HTTPException(409, "请等待闲鱼搜索任务成功后再导入")
    result = job["result"] or {}
    item_id = result.get("item_id") or job["payload"].get("item_id")
    item = connection.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if item is None:
        raise HTTPException(404, "原日本商品已不存在")
    if item["archived_at"]:
        raise HTTPException(409, "请先恢复已归档商品")
    candidates = result.get("items", [])
    if len(set(payload.indexes)) != len(payload.indexes) or any(index < 0 or index >= len(candidates) for index in payload.indexes):
        raise HTTPException(422, "选择了无效或重复的闲鱼商品索引")
    if item["status"] == "candidate":
        require_transition(item["status"], "sourcing")
        connection.execute("UPDATE items SET status='sourcing' WHERE id=?", (item_id,))
    elif item["status"] not in ("sourcing", "matched", "listing_draft", "listed", "withdrawn"):
        raise HTTPException(409, "当前商品状态不能添加货源候选")
    pending_image_sources = set()
    for pending in connection.execute(
        "SELECT payload FROM automation_jobs WHERE kind='china_source_images' AND status IN ('queued','running')"
    ).fetchall():
        try:
            pending_image_sources.update(json.loads(pending["payload"]).get("source_ids", []))
        except (TypeError, ValueError):
            continue
    imported, skipped, image_source_ids, thumbnail_urls = [], [], [], {}
    for index in payload.indexes:
        candidate = candidates[index]
        try:
            source_url = validate_xianyu_item_url(candidate.get("url", ""))
        except ValueError as error:
            raise HTTPException(422, f"第 {index + 1} 条结果不是有效的闲鱼商品链接") from error
        existing = connection.execute(
            "SELECT id FROM china_sources WHERE item_id=? AND china_site='xianyu' AND source_url=? AND archived_at IS NULL",
            (item_id, source_url),
        ).fetchone()
        if existing:
            skipped.append({"index": index, "id": existing["id"]})
            image_count = connection.execute(
                "SELECT COUNT(*) FROM source_images WHERE source_id=? AND excluded_at IS NULL", (existing["id"],)
            ).fetchone()[0]
            if image_count < 5 and existing["id"] not in pending_image_sources:
                image_source_ids.append(existing["id"])
                if candidate.get("image_url"):
                    thumbnail_urls[existing["id"]] = candidate["image_url"]
            continue
        source_id = uuid.uuid4().hex
        provenance = "闲鱼自动采集；日本商品：" + str(item["japan_title"])[:180]
        search_query = candidate.get("search_query")
        if search_query:
            provenance += "；日本商品资料生成的搜索词：" + str(search_query)[:180]
        connection.execute(
            "INSERT INTO china_sources (id,item_id,china_site,source_url,source_title,price_cny,account_note,match_status,created_at) VALUES (?,?,?,?,?,?,?,'pending',?)",
            (source_id, item_id, "xianyu", source_url, str(candidate.get("title", ""))[:500], candidate.get("price"), provenance[:500], now_iso()),
        )
        record_event(connection, "item", item_id, "source_added", {"source_id": source_id, "source_url": source_url, "job_id": job_id})
        imported.append({"index": index, "id": source_id})
        image_source_ids.append(source_id)
        if candidate.get("image_url"):
            thumbnail_urls[source_id] = candidate["image_url"]
    image_jobs = []
    unique_image_sources = list(dict.fromkeys(image_source_ids))
    for offset in range(0, len(unique_image_sources), 10):
        batch = unique_image_sources[offset:offset + 10]
        image_jobs.append(enqueue(connection, "china_source_images", {
            "item_id": item_id,
            "source_ids": batch,
            "thumbnail_urls": {source_id: thumbnail_urls[source_id] for source_id in batch if source_id in thumbnail_urls},
            "browser_channel": job["payload"].get("browser_channel", "chrome"),
            "browser_mode": job["payload"].get("browser_mode", "managed"),
        }))
    connection.commit()
    if image_jobs:
        request.app.state.automation.wake.set()
    return {"imported": imported, "skipped": skipped,
            "image_job": image_jobs[0] if image_jobs else None, "image_jobs": image_jobs}


@router.post("/api/automation/watches", status_code=201)
def add_watch(payload: WatchCreate, request: Request, connection: sqlite3.Connection = Depends(get_db)):
    if not payload.name.strip():
        raise HTTPException(422, "请填写监控名称")
    if payload.kind == "japan_search" and not payload.query.strip():
        raise HTTPException(422, "关键词监控需要填写关键词")
    url = checked_url(payload.url, "shop") if payload.kind == "japan_shop" else ""
    if payload.kind == "listing_prepare" and (payload.query.strip() or payload.url.strip()):
        raise HTTPException(422, "上架资料自动整理任务不需要关键词或店铺链接")
    watch_id = uuid.uuid4().hex
    connection.execute("INSERT INTO watches (id,name,kind,site_id,query,url,interval_minutes,result_limit,created_at,next_run_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (watch_id, payload.name.strip(), payload.kind, payload.site_id, payload.query.strip(), url, payload.interval_minutes, payload.result_limit, now_iso(), now_iso()))
    connection.commit()
    request.app.state.automation.wake.set()
    return dict(connection.execute("SELECT * FROM watches WHERE id=?", (watch_id,)).fetchone())


@router.get("/api/automation/watches")
def list_watches(include_archived: bool = False, connection: sqlite3.Connection = Depends(get_db)):
    return [dict(row) for row in connection.execute("SELECT * FROM watches WHERE (? OR archived_at IS NULL) ORDER BY created_at DESC", (include_archived,))]


@router.patch("/api/automation/watches/{watch_id}")
def edit_watch(watch_id: str, payload: WatchUpdate, request: Request, connection: sqlite3.Connection = Depends(get_db)):
    watch = connection.execute("SELECT * FROM watches WHERE id=?", (watch_id,)).fetchone()
    if watch is None:
        raise HTTPException(404, "未找到监控任务")
    if watch["archived_at"]:
        raise HTTPException(409, "该监控已归档")
    values = payload.model_dump(exclude_unset=True)
    if any(value is None for value in values.values()):
        raise HTTPException(422, "监控设置不能为 null")
    if values:
        if values.get("enabled"):
            values["next_run_at"] = now_iso()
        elif "interval_minutes" in values:
            values["next_run_at"] = schedule_next(values["interval_minutes"])
        assignments = ",".join(f"{name}=?" for name in values)
        connection.execute(f"UPDATE watches SET {assignments} WHERE id=?", (*values.values(), watch_id))
        connection.commit()
    request.app.state.automation.wake.set()
    return dict(connection.execute("SELECT * FROM watches WHERE id=?", (watch_id,)).fetchone())


@router.delete("/api/automation/watches/{watch_id}")
def archive_watch(watch_id: str, connection: sqlite3.Connection = Depends(get_db)):
    if connection.execute("SELECT id FROM watches WHERE id=?", (watch_id,)).fetchone() is None:
        raise HTTPException(404, "未找到监控任务")
    connection.execute("UPDATE watches SET enabled=0,archived_at=? WHERE id=?", (now_iso(), watch_id))
    connection.commit()
    return {"id": watch_id, "archived": True}


@router.get("/api/automation/watches/{watch_id}/changes")
def watch_changes(watch_id: str, connection: sqlite3.Connection = Depends(get_db)):
    if connection.execute("SELECT id FROM watches WHERE id=?", (watch_id,)).fetchone() is None:
        raise HTTPException(404, "未找到监控任务")
    return [dict(row) for row in connection.execute("SELECT * FROM watch_changes WHERE watch_id=? ORDER BY created_at DESC LIMIT 200", (watch_id,))]


@router.post("/api/automation/watches/{watch_id}/restore")
def restore_watch(watch_id: str, connection: sqlite3.Connection = Depends(get_db)):
    if connection.execute("SELECT id FROM watches WHERE id=?", (watch_id,)).fetchone() is None:
        raise HTTPException(404, "未找到监控任务")
    connection.execute("UPDATE watches SET archived_at=NULL,enabled=0 WHERE id=?", (watch_id,))
    connection.commit()
    return {"id": watch_id, "archived": False, "enabled": False}


@router.post("/api/automation/watches/{watch_id}/run", status_code=202)
def run_watch(watch_id: str, request: Request, connection: sqlite3.Connection = Depends(get_db)):
    connection.execute("BEGIN IMMEDIATE")
    watch = connection.execute("SELECT * FROM watches WHERE id=? AND archived_at IS NULL", (watch_id,)).fetchone()
    if watch is None:
        raise HTTPException(404, "未找到监控任务")
    if connection.execute("SELECT 1 FROM automation_jobs WHERE watch_id=? AND status IN ('queued','running','waiting_login','waiting_review')", (watch_id,)).fetchone():
        raise HTTPException(409, "该监控已有未完成任务")
    job = enqueue(connection, watch["kind"], {
        "query": watch["query"], "url": watch["url"], "limit": watch["result_limit"],
        "available_only": True, "sort": "newest",
    }, watch_id)
    connection.execute("UPDATE watches SET last_job_id=?,last_run_at=?,next_run_at=? WHERE id=?", (job["id"], now_iso(), schedule_next(watch["interval_minutes"]), watch_id))
    connection.commit()
    request.app.state.automation.wake.set()
    return job


@router.post("/api/automation/shops/session", status_code=202)
def open_shop_session(request: Request, payload: ShopTask = ShopTask(), connection: sqlite3.Connection = Depends(get_db)):
    return create_job(request, connection, "shop_session", checked_shop_task(payload, connection))


@router.delete("/api/automation/shops/session", status_code=202)
def close_shop_session(request: Request, connection: sqlite3.Connection = Depends(get_db)):
    return create_job(request, connection, "shop_close_session", {})


@router.post("/api/automation/shops/inspect-form", status_code=202)
def inspect_shop_form(request: Request, payload: ShopTask = ShopTask(), connection: sqlite3.Connection = Depends(get_db)):
    return create_job(request, connection, "shop_inspect_form", checked_shop_task(payload, connection))


@router.post("/api/listing/drafts/{draft_id}/fill-shop", status_code=202)
def fill_shop_draft(draft_id: str, request: Request, payload: ShopTask = ShopTask(), connection: sqlite3.Connection = Depends(get_db)):
    draft = connection.execute("SELECT * FROM listing_drafts WHERE id=?", (draft_id,)).fetchone()
    if draft is None:
        raise HTTPException(404, "未找到上架草稿")
    if draft["status"] != "draft":
        raise HTTPException(409, "已发布商品不能再次填写草稿")
    return create_job(request, connection, "shop_fill_draft", {**checked_shop_task(payload, connection), "draft_id": draft_id})


@router.post("/api/automation/shops/read-orders", status_code=202)
def read_shop_orders(request: Request, payload: ShopTask = ShopTask(), connection: sqlite3.Connection = Depends(get_db)):
    return create_job(request, connection, "shop_read_orders", checked_shop_task(payload, connection))


@router.get("/api/automation/shop-order-imports")
def shop_imports(connection: sqlite3.Connection = Depends(get_db)):
    return [{**dict(row), "raw_data": json.loads(row["raw_data"])} for row in connection.execute("SELECT * FROM shop_order_imports ORDER BY created_at DESC LIMIT 200")]


@router.post("/api/automation/shop-order-imports/{import_id}/confirm")
def confirm_shop_import(import_id: str, payload: ShopOrderMapping, connection: sqlite3.Connection = Depends(get_db)):
    connection.execute("BEGIN IMMEDIATE")
    row = connection.execute("SELECT * FROM shop_order_imports WHERE id=?", (import_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "未找到待确认店铺订单")
    if row["local_order_id"]:
        connection.rollback()
        return {"id": row["local_order_id"], "already_imported": True}
    quantity = payload.quantity if payload.quantity is not None else row["quantity"]
    amount = payload.amount_jpy if payload.amount_jpy is not None else row["amount_jpy"]
    if not quantity or not amount:
        raise HTTPException(422, "页面无法确定数量或成交金额，请核对后补填")
    existing = connection.execute("SELECT * FROM sales_orders WHERE mercari_order_id=? AND item_id=?", (row["external_order_id"], payload.item_id)).fetchone()
    if existing:
        if existing["quantity"] != quantity or existing["sold_price_jpy"] != amount:
            raise HTTPException(409, "本地已有不同数量或金额的同号订单，请人工核对")
        order = dict(existing)
    else:
        order = save_sales_order(SalesOrderCreate(item_id=payload.item_id, mercari_order_id=row["external_order_id"], quantity=quantity, sold_price_jpy=amount), connection, commit=False)
    connection.execute("UPDATE shop_order_imports SET status='imported',local_order_id=? WHERE id=?", (order["id"], import_id))
    connection.commit()
    return order
