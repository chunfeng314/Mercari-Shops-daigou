"""One worker owns Playwright; external Chrome sessions are attached, never owned."""
from datetime import datetime, timezone
from contextlib import contextmanager
import base64
import json
import logging
import sqlite3
import threading
import time
import uuid
from urllib.parse import urlparse, urlunparse

from playwright.sync_api import sync_playwright

from app import db
from app.audit import now_iso
from app.automation.store import WAITING, enqueue, job_record, save_watch_observations, schedule_next
from app.config import settings
from app.modules.japan_selection.mercari import MercariCollector, filter_minimum_price
from app.modules.china_sourcing.xianyu import XianyuCollector, XianyuCollectionError, validate_image_url
from app.modules.china_sourcing.candidate_rules import screen_sources
from app.modules.china_sourcing.image_review import review_source_images
from app.modules.mercari_listing.browser_adapter import SHOPS_SIGNIN, ShopsBrowserAdapter, is_signed_in
from app.records import listing_draft_record
from app.browser.shop_connection import ExistingShopBrowser, shop_root
from app.browser.existing_browser import ExistingBrowserSession
from app.browser.managed_browser import ManagedBrowserSessions, navigate_managed
from app.image_assets import resolve_image_path
from app.source_image_collection import save_collected_image, reconcile_collected_images
from app.listing_preparation import prepare_confirmed_batch


class JobCancelled(Exception):
    pass


class JobControl:
    def __init__(self, service, job_id):
        self.service = service
        self.job_id = job_id
        self.resume = threading.Event()
        self.cancel = threading.Event()

    def check(self):
        if self.cancel.is_set() or self.service.stopping.is_set():
            raise JobCancelled("任务已取消；浏览器中已填写的内容请人工核对")
        connection = db.connect_db()
        try:
            row = connection.execute("SELECT cancel_requested FROM automation_jobs WHERE id=?", (self.job_id,)).fetchone()
            if row and row["cancel_requested"]:
                raise JobCancelled("任务已取消；浏览器中已填写的内容请人工核对")
        finally:
            connection.close()

    def progress(self, message, status="running", result=None):
        self.check()
        connection = db.connect_db()
        try:
            connection.execute("UPDATE automation_jobs SET status=?,progress=? WHERE id=?", (status, message, self.job_id))
            if result is not None:
                connection.execute("UPDATE automation_jobs SET result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), self.job_id))
            connection.commit()
        finally:
            connection.close()

    def wait_for_user(self, message, status="waiting_login", result=None):
        self.resume.clear()
        self.progress(message, status, result)
        deadline = time.monotonic() + 900
        while not self.resume.wait(.5):
            self.check()
            if time.monotonic() >= deadline:
                raise ValueError("等待人工操作超过 15 分钟。会话仍可在服务运行期间使用，请重新创建任务。")
        self.check()
        self.progress("正在继续执行")


class AutomationService:
    def __init__(self):
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.controls = {}
        self.lock = threading.Lock()
        self.thread = None
        self.browser = None
        self.playwright = None
        self.shop_context = None
        self.shop_page = None
        self.shop_mode = "managed"
        self.existing_shop = ExistingShopBrowser()
        self.existing_browser = ExistingBrowserSession()
        self.managed_browser = ManagedBrowserSessions()

    def start(self):
        connection = db.connect_db()
        try:
            connection.execute("UPDATE automation_jobs SET status='failed',error='服务已重启，请核对平台操作后重新执行',finished_at=? WHERE status IN ('running','waiting_login','waiting_review')", (now_iso(),))
            connection.commit()
        finally:
            connection.close()
        self.thread = threading.Thread(target=self._loop, name="mercari-browser-worker", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=settings.browser_timeout_ms / 1000 + 10)

    def resume(self, job_id):
        with self.lock:
            control = self.controls.get(job_id)
            if control is None:
                raise ValueError("该任务没有可继续的浏览器会话")
            control.resume.set()

    def cancel(self, job_id):
        with self.lock:
            if job_id in self.controls:
                self.controls[job_id].cancel.set()
        self.wake.set()

    def _claim(self):
        connection = db.connect_db()
        try:
            connection.execute("BEGIN IMMEDIATE")
            now = now_iso()
            for watch in connection.execute("SELECT * FROM watches WHERE enabled=1 AND next_run_at<=? ORDER BY next_run_at LIMIT 5", (now,)).fetchall():
                pending = connection.execute("SELECT 1 FROM automation_jobs WHERE watch_id=? AND status IN ('queued','running','waiting_login','waiting_review')", (watch["id"],)).fetchone()
                if not pending:
                    payload = {"site_id": watch["site_id"], "query": watch["query"], "url": watch["url"], "limit": watch["result_limit"], "available_only": True, "sort": "newest"}
                    job = enqueue(connection, watch["kind"], payload, watch["id"])
                    connection.execute("UPDATE watches SET last_job_id=?,next_run_at=?,last_run_at=? WHERE id=?", (job["id"], schedule_next(watch["interval_minutes"]), now, watch["id"]))
                else:
                    connection.execute("UPDATE watches SET next_run_at=? WHERE id=?", (schedule_next(watch["interval_minutes"]), watch["id"]))
            row = connection.execute("SELECT * FROM automation_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row:
                connection.execute("UPDATE automation_jobs SET status='running',started_at=?,progress='准备执行' WHERE id=?", (now, row["id"]))
            connection.commit()
            return job_record(row)
        finally:
            connection.close()

    def _launch(self):
        if self.browser and self.browser.is_connected():
            return
        self._driver()
        options = {"headless": settings.browser_headless}
        if settings.browser_channel:
            options["channel"] = settings.browser_channel
        proxy = settings.japan_browser_proxy or settings.browser_proxy
        if proxy:
            options["proxy"] = {"server": proxy}
        self.browser = self.playwright.chromium.launch(**options)

    def _driver(self):
        if self.playwright is None:
            self.playwright = sync_playwright().start()

    def _close_shop(self):
        if self.shop_mode == "existing_chrome":
            self.existing_shop.disconnect()
        elif self.shop_mode == "managed":
            self.managed_browser.close("japan")
        elif self.shop_context:
            self.shop_context.close()
        self.shop_context = self.shop_page = None

    def _context(self):
        self._launch()
        context = self.browser.new_context(locale="ja-JP", timezone_id="Asia/Tokyo", viewport={"width": 1440, "height": 1000})
        context.set_default_timeout(8000)
        context.set_default_navigation_timeout(settings.browser_timeout_ms)
        return context

    def _managed_shop(self, control, url, channel, purpose):
        self._driver()
        control.progress("正在复用工作台专用店铺浏览器；登录状态保存在本机，无需允许接管日常 Chrome")
        self.shop_context = self.managed_browser.context(self.playwright, "japan", channel, settings.browser_timeout_ms)
        self.shop_page = self.managed_browser.page(self.playwright, "japan", channel, "shop", settings.browser_timeout_ms)
        target = shop_root(url) if url else ""
        from app.browser.shop_connection import belongs_to_shop
        if self.shop_page.url == "about:blank" or (target and not belongs_to_shop(self.shop_page.url, target)):
            navigate_managed(self.shop_page, target or SHOPS_SIGNIN, settings.browser_timeout_ms)
        if not is_signed_in(self.shop_page):
            control.wait_for_user("请在工作台专用 Chrome 首次登录店铺，然后点击继续。登录状态会保存在本机，后续任务自动复用。")
            if target:
                navigate_managed(self.shop_page, target, settings.browser_timeout_ms)
        if not is_signed_in(self.shop_page):
            raise ValueError("专用浏览器尚未进入已登录的店铺管理页面，请完成登录后重试")
        root = target or shop_root(self.shop_page.url)
        if not belongs_to_shop(self.shop_page.url, root):
            raise ValueError("当前页面不属于指定店铺，已停止店铺操作")
        if purpose in ("fill", "inspect", "orders"):
            task_url = root + ("/orders" if purpose == "orders" else "/products/create")
            if purpose == "fill":
                self.shop_page = self.shop_context.new_page()
            else:
                self.shop_page = self.managed_browser.page(self.playwright, "japan", channel, purpose, settings.browser_timeout_ms)
            navigate_managed(self.shop_page, task_url, settings.browser_timeout_ms)
        return self.shop_page

    @contextmanager
    def _china_browser(self, payload):
        self._driver()
        channel = payload.get("browser_channel", "chrome")
        if payload.get("browser_mode", "managed") == "managed":
            page = self.managed_browser.page(self.playwright, "china", channel, "collection", settings.browser_timeout_ms)
        else:
            page = self.existing_browser.connect(self.playwright, channel, settings.browser_timeout_ms)
        # Keep both managed and explicitly selected external transports alive
        # between tasks; connecting for every job triggers repeated consent.
        yield page

    def _shop(self, control, url="", instructions="请在浏览器中登录店铺后点击继续", browser_mode="managed", browser_channel="chrome", purpose="session"):
        if browser_mode != self.shop_mode:
            self._close_shop()
            self.shop_mode = browser_mode
        if browser_mode == "managed":
            return self._managed_shop(control, url, browser_channel, purpose)
        if browser_mode == "existing_chrome":
            self._driver()
            control.progress("正在连接独立登录浏览器，复用该浏览器配置中的店铺会话")
            self.existing_shop.connect(self.playwright, browser_channel, url, settings.browser_timeout_ms)
            self.shop_context = self.existing_shop.context
            self.shop_page = self.existing_shop.page_for(purpose)
            if not is_signed_in(self.shop_page):
                raise ValueError("指定店铺尚未登录；请在真实浏览器完成登录后重新连接")
            return self.shop_page
        if self.shop_page is None or self.shop_page.is_closed():
            self.shop_context = self._context()
            self.shop_page = self.shop_context.new_page()
            self.shop_page.goto(url or SHOPS_SIGNIN, wait_until="domcontentloaded")
            # New sessions always wait for the operator; login credentials are never filled by code.
            control.wait_for_user(instructions)
        elif url and self.shop_page.url != url:
            self.shop_page.goto(url, wait_until="domcontentloaded")
        if not is_signed_in(self.shop_page):
            control.wait_for_user(instructions)
        if not is_signed_in(self.shop_page):
            raise ValueError("尚未进入已登录的店铺管理页面，请完成登录并选择店铺后重试")
        if purpose in ("fill", "inspect", "orders"):
            root = shop_root(self.shop_page.url)
            target = root + ("/orders" if purpose == "orders" else "/products/create")
            if urlparse(self.shop_page.url).path != urlparse(target).path or (purpose == "fill" and urlparse(self.shop_page.url).query):
                self.shop_page = self.shop_context.new_page()
                self.shop_page.goto(target, wait_until="domcontentloaded")
        return self.shop_page

    def _draft(self, draft_id):
        connection = db.connect_db()
        try:
            draft = listing_draft_record(connection.execute("SELECT * FROM listing_drafts WHERE id=?", (draft_id,)).fetchone())
            if not draft or draft["status"] != "draft":
                raise ValueError("仅能填写尚未发布的本地草稿")
            if connection.execute("SELECT archived_at FROM items WHERE id=?", (draft["item_id"],)).fetchone()["archived_at"]:
                raise ValueError("请先恢复已归档商品")
            images = []
            for image_id in draft["image_asset_ids"]:
                row = connection.execute("SELECT * FROM source_images WHERE id=? AND source_id=? AND excluded_at IS NULL", (image_id, draft["china_source_id"])).fetchone()
                if row:
                    images.append(dict(row))
            if len(images) != len(draft["image_asset_ids"]) or any(not resolve_image_path(image["listing_path"]) for image in images):
                raise ValueError("草稿图片或文件缺失，请先在本地资料中重新选择图片")
            return draft, images
        finally:
            connection.close()

    def _execute(self, job, control):
        kind, payload = job["kind"], job["payload"]
        if kind == "browser_close":
            control.progress("正在关闭专用浏览器并保存本机登录状态")
            self.managed_browser.close(payload["scope"])
            if payload["scope"] == "japan" and self.shop_mode == "managed":
                self.shop_context = self.shop_page = None
            return {"scope": payload["scope"], "closed": True, "login_state_persisted": True}
        if kind == "browser_session":
            self._driver()
            scope, channel = payload["scope"], payload.get("browser_channel", "chrome")
            previous_context = self.managed_browser.contexts.get((scope, channel))
            control.progress("正在打开工作台专用浏览器，后续任务会保留并复用登录状态")
            urls = payload.get("urls") or (["https://www.goofish.com/"] if scope == "china" else ["https://jp.mercari.com/"])
            pages = []
            for index, url in enumerate(urls):
                purpose = "collection" if index == 0 else f"browser_login_{index}"
                page = self.managed_browser.page(self.playwright, scope, channel, purpose, settings.browser_timeout_ms)
                navigate_managed(page, url, settings.browser_timeout_ms)
                pages.append(page)
            reused = previous_context is not None and self.managed_browser.contexts.get((scope, channel)) is previous_context
            pages[-1].bring_to_front()
            return {"scope": scope, "browser_mode": "managed", "url": pages[-1].url,
                    "urls": [page.url for page in pages], "tabs_opened": len(pages),
                    "session_reused": reused,
                    "login_state_persisted": True, "control_prompt_required": False,
                    "note": "首次使用请在专用窗口登录；此任务完成后窗口继续保留，平台要求重新登录时才需人工处理。"}
        if kind == "listing_prepare":
            control.progress("正在整理已核验商品的上架资料")
            connection = db.connect_db()
            try:
                return prepare_confirmed_batch(connection, min(max(int(payload.get("limit", 20)), 1), 100), control.check)
            finally:
                connection.close()
        if kind == "china_image_review":
            control.check()
            control.progress("正在用千问视觉模型自动判断货源图片用途和排除状态")
            connection = db.connect_db()
            try:
                result = review_source_images(connection, payload["source_id"], payload["item_id"])
                if result.get("status") == "failed":
                    raise RuntimeError(result.get("message", "千问图片复核失败"))
                return result
            finally:
                connection.close()
        if kind.startswith("japan_"):
            control.progress("正在打开 Mercari 页面")
            context = self._context()
            try:
                collector = MercariCollector(context.new_page(), control.check, control.progress)
                if kind == "japan_search":
                    items = collector.search(payload["query"], payload.get("limit", 20), payload.get("available_only", True), payload.get("sort", "newest"))
                elif kind == "japan_shop":
                    items = collector.shop(payload["url"], payload.get("limit", 20))
                elif kind == "japan_item":
                    items, price_stats = filter_minimum_price(collector.item(payload["url"]))
                    collector.last_price_filter_stats = price_stats
                else:
                    raise ValueError("未知的采集任务")
                price_filter = collector.last_price_filter_stats
            finally:
                context.close()
            return {"items": items, "count": len(items), "collected_at": now_iso(), "price_filter": price_filter}
        if kind == "china_search":
            channel = payload.get("browser_channel", "chrome")
            browser_name = "Chrome" if channel == "chrome" else "Edge"
            control.progress(f"正在使用{ '工作台专用' if payload.get('browser_mode', 'managed') == 'managed' else '已登录的本机'} {browser_name} 搜索闲鱼")
            with self._china_browser(payload) as page:
                collector = XianyuCollector(page, control.check, control.progress)
                queries = payload.get("queries") or [payload.get("item_title", "")]
                items = collector.search_many(queries, min(max(int(payload.get("limit", 20)), 1), 50))
            raw_count = len(items)
            items, excluded_items = screen_sources(payload.get("item_title", ""), items)
            return {"site_id": "xianyu", "item_id": payload["item_id"], "search_queries": queries,
                    "items": items, "count": len(items), "collected_at": now_iso(),
                    "read_count": raw_count, "excluded_items": excluded_items, "excluded_count": len(excluded_items),
                    "browser_channel": channel, "browser_mode": payload.get("browser_mode", "managed")}
        if kind == "china_source_images":
            channel = payload.get("browser_channel", "chrome")
            browser_name = "Chrome" if channel == "chrome" else "Edge"
            source_ids = list(dict.fromkeys(payload.get("source_ids", [])))[:10]
            if not source_ids:
                raise ValueError("没有待采集图片的闲鱼货源")
            control.progress(f"正在使用 {browser_name} 的保留会话，读取所选闲鱼货源的详情图片")
            with self._china_browser(payload) as page:
                collector = XianyuCollector(page, control.check, control.progress)
                summaries = []
                all_previews = []
                connection = db.connect_db()
                try:
                    for index, source_id in enumerate(source_ids, start=1):
                        control.check()
                        source = connection.execute(
                            "SELECT * FROM china_sources WHERE id=? AND item_id=? AND china_site='xianyu' AND archived_at IS NULL",
                            (source_id, payload.get("item_id")),
                        ).fetchone()
                        if source is None:
                            summaries.append({"source_id": source_id, "collected": 0, "error": "货源不存在或已归档"})
                            continue
                        try:
                            detail = collector.collect_detail_images(source["source_url"], limit=10)
                        except (XianyuCollectionError, ValueError) as error:
                            summaries.append({"source_id": source_id, "title": source["source_title"], "collected": 0, "error": str(error)})
                            continue
                        excluded_saved = reconcile_collected_images(connection, source_id, payload["item_id"], detail)
                        existing_count = connection.execute(
                            "SELECT COUNT(*) FROM source_images WHERE source_id=? AND excluded_at IS NULL", (source_id,)
                        ).fetchone()[0]
                        collected, duplicates, errors = 0, 0, []
                        remaining = max(0, 10 - existing_count)
                        image_candidates = list(detail["images"])
                        fallback_url = (payload.get("thumbnail_urls") or {}).get(source_id)
                        if fallback_url:
                            try:
                                safe_fallback = validate_image_url(fallback_url)
                                if all(candidate["url"] != safe_fallback for candidate in image_candidates):
                                    image_candidates.append({
                                        "url": safe_fallback, "collection_note": "闲鱼搜索结果缩略图候选",
                                    })
                            except ValueError:
                                pass

                        def guard_image_request(route):
                            try:
                                validate_image_url(route.request.url)
                            except ValueError:
                                route.abort()
                            else:
                                route.continue_()

                        for image in image_candidates[:remaining]:
                            control.check()
                            try:
                                asset_url = validate_image_url(image["url"])
                                page.route("**/*", guard_image_request)
                                try:
                                    response = page.goto(asset_url, wait_until="domcontentloaded", timeout=18000)
                                finally:
                                    page.unroute("**/*", guard_image_request)
                                if response and response.status >= 400:
                                    raise ValueError(f"图片返回 HTTP {response.status}")
                                asset_url = validate_image_url(page.url)
                                picture = page.locator("img").first
                                picture.wait_for(state="visible", timeout=5000)
                                dimensions = picture.evaluate("img => ({width:img.naturalWidth,height:img.naturalHeight})")
                                if (dimensions["width"] < 100 or dimensions["height"] < 100
                                        or dimensions["width"] * dimensions["height"] > 12_000_000):
                                    raise ValueError("图片尺寸不适合安全采集")
                                raw_asset = page.evaluate("""async () => {
                                  try {
                                    const response = await fetch(location.href, {cache: 'no-store'});
                                    if (!response.ok) return null;
                                    const blob = await response.blob();
                                    if (!blob.type.startsWith('image/') || blob.size > 12 * 1024 * 1024) return null;
                                    const bytes = new Uint8Array(await blob.arrayBuffer());
                                    let binary = '';
                                    for (let offset = 0; offset < bytes.length; offset += 0x8000) {
                                      binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
                                    }
                                    return {content_type: blob.type, data: btoa(binary)};
                                  } catch (_) { return null; }
                                }""")
                                payload_bytes = (base64.b64decode(raw_asset["data"]) if raw_asset and raw_asset.get("data")
                                                 else picture.screenshot(timeout=8000, animations="disabled"))
                                saved = save_collected_image(
                                    connection, source_id, detail["url"], asset_url,
                                    image.get("collection_note", "闲鱼详情页图片候选"), payload_bytes,
                                )
                                if saved["duplicate"]:
                                    duplicates += 1
                                else:
                                    collected += 1
                                    all_previews.append({
                                        "id": saved["id"], "source_id": source_id,
                                        "url": f"/api/china/source-images/{saved['id']}/file?variant=listing",
                                        "note": image.get("collection_note", "闲鱼详情页图片候选"),
                                    })
                            except Exception as error:
                                try:
                                    page.unroute("**/*", guard_image_request)
                                except Exception:
                                    pass
                                errors.append(str(error)[:160])
                        connection.commit()
                        try:
                            vision_review = review_source_images(connection, source_id, payload["item_id"])
                        except Exception as error:
                            vision_review = {"status": "failed", "message": f"图片建议生成失败：{str(error)[:180]}"}
                        summaries.append({
                            "source_id": source_id, "title": source["source_title"],
                            "detail_title": detail.get("title", ""), "found": len(detail["images"]),
                            "filtered_count": len(detail.get("excluded_images", [])),
                            "excluded_saved_images": excluded_saved,
                            "retained_regions": list(dict.fromkeys(
                                image.get("region", "") for image in detail["images"] if image.get("region")
                            ))[:8],
                            "filtered_regions": list(dict.fromkeys(
                                image.get("region", "") for image in detail.get("excluded_images", []) if image.get("region")
                            ))[:8],
                            **({"candidate_images": detail["images"],
                                "image_diagnostics": detail.get("image_diagnostics", []),
                                "excluded_images": detail.get("excluded_images", [])}
                               if payload.get("diagnostics") else {}),
                            "collected": collected, "duplicates": duplicates,
                            "total_images": existing_count + collected,
                            "vision_review": vision_review,
                            "errors": errors[:5],
                            "note": "自动收集的图片均为待核对候选；程序不会擅自标记为实物图。",
                        })
                        control.progress(f"闲鱼图片采集 {index}/{len(source_ids)}：新增 {collected} 张候选图")
                finally:
                    connection.close()
            return {"item_id": payload.get("item_id"), "sources": summaries,
                    "image_preview": all_previews, "count": sum(row.get("collected", 0) for row in summaries),
                    "max_images_per_source": 10, "collected_at": now_iso()}
        if kind == "shop_close_session":
            self._close_shop()
            return {"session_active": False}
        if kind == "shop_session":
            page = self._shop(control, **payload)
            url = urlparse(page.url)
            return {"session_active": True, "browser_mode": self.shop_mode, "url": urlunparse((url.scheme, url.netloc, url.path, "", "", ""))}
        if kind == "shop_inspect_form":
            page = self._shop(control, purpose="inspect", **payload)
            return ShopsBrowserAdapter(page, control.check, shop_root(page.url)).inspect()
        if kind == "shop_fill_draft":
            draft, images = self._draft(payload["draft_id"])
            if draft["reservation_sale"] or draft["multi_variant"]:
                raise ValueError("目前自动填写支持普通销售、单规格商品；预约和多规格需在店铺人工设置")
            page = self._shop(control, **{k: v for k, v in payload.items() if k != "draft_id"}, purpose="fill")
            adapter = ShopsBrowserAdapter(page, control.check, shop_root(page.url))
            inspection = adapter.inspect()
            if inspection["missing_controls"]:
                raise ValueError("表单控件有变化，请先检查：" + "、".join(inspection["missing_controls"]))
            preview = {"stage": "before_fill", "autosaves_on_edit": True,
                       "preview": [{"label": f["label"], "value": len(images) if f["field"] == "image_asset_ids" else draft.get(f["field"])} for f in inspection["fields"]],
                       "description_ja": draft["description_ja"],
                       "image_preview": [{"id": image["id"], "url": f"/api/china/source-images/{image['id']}/file?variant=listing"} for image in images],
                       "url": page.url}
            control.wait_for_user("请核对待填写资料；开始编辑后平台会自动保存为草稿。确认后开始填写。", "waiting_review", preview)
            latest, latest_images = self._draft(payload["draft_id"])
            if latest != draft or latest_images != images:
                raise ValueError("本地草稿或图片在核对期间发生变更，请重新执行")
            report = adapter.fill(draft, images)
            control.wait_for_user("请核对店铺页面、补全报告中的字段；确认后点击“保存店铺草稿”", "waiting_review", report)
            latest, _ = self._draft(payload["draft_id"])
            if latest != draft:
                raise ValueError("本地草稿在核对期间发生了变更，请重新填写店铺草稿")
            report.update(adapter.save_reviewed_draft())
            return report
        if kind == "shop_read_orders":
            page = self._shop(control, **payload, purpose="orders")
            page.get_by_role("heading", name="注文一覧", exact=True).wait_for(timeout=15000)
            orders = ShopsBrowserAdapter(page, control.check, shop_root(page.url)).read_orders()
            connection = db.connect_db()
            try:
                for order in orders:
                    connection.execute("INSERT INTO shop_order_imports (id,external_order_id,external_product_url,title,quantity,amount_jpy,raw_data,created_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(external_order_id,external_product_url) DO UPDATE SET title=excluded.title,quantity=excluded.quantity,amount_jpy=excluded.amount_jpy,raw_data=excluded.raw_data WHERE shop_order_imports.local_order_id IS NULL",
                                       (uuid.uuid4().hex, order["external_order_id"], order["external_product_url"], order["title"], order["quantity"], order["amount_jpy"], json.dumps(order, ensure_ascii=False), now_iso()))
                connection.commit()
            finally:
                connection.close()
            return {"orders": orders, "count": len(orders), "requires_mapping": True, "scope": "当前店铺列表及其筛选条件"}
        raise ValueError("不支持的任务类型")

    def _finish(self, job, status, result=None, error=None):
        connection = db.connect_db()
        try:
            if status == "succeeded" and job.get("watch_id") and job["kind"].startswith("japan_"):
                result["changes"] = save_watch_observations(connection, job["watch_id"], job["id"], result.get("items", []))
            connection.execute("UPDATE automation_jobs SET status=?,result=COALESCE(?,result),error=?,finished_at=?,progress=? WHERE id=?", (status, json.dumps(result, ensure_ascii=False) if result is not None else None, error, now_iso(), "已完成" if status == "succeeded" else error or status, job["id"]))
            connection.commit()
        finally:
            connection.close()

    def _loop(self):
        try:
            while not self.stopping.is_set():
                try:
                    job = self._claim()
                except sqlite3.OperationalError:
                    logging.getLogger(__name__).exception("无法读取采集任务，将稍后重试")
                    self.stopping.wait(2)
                    continue
                if not job:
                    self.wake.wait(1)
                    self.wake.clear()
                    continue
                control = JobControl(self, job["id"])
                with self.lock:
                    self.controls[job["id"]] = control
                try:
                    result = self._execute(job, control)
                    self._finish(job, "succeeded", result)
                except JobCancelled as error:
                    self._finish(job, "cancelled", error=str(error))
                except Exception as error:
                    # Browser errors may contain selectors but never credentials or page HTML.
                    self._finish(job, "failed", error=str(error)[:1800])
                finally:
                    with self.lock:
                        self.controls.pop(job["id"], None)
        finally:
            self._close_shop()
            self.existing_browser.disconnect()
            self.managed_browser.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
