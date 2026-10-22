import re
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import test_workflow
from app import db
from app.automation.service import AutomationService, JobCancelled
from app.browser.existing_browser import ExistingBrowserSession, _debug_endpoint
from app.browser.shop_connection import ExistingShopBrowser, _shop_debug_endpoint, belongs_to_shop, shop_root


class ExistingBrowserEndpointTests(unittest.TestCase):
    def test_uses_chromium_instance_websocket_path_from_active_port_file(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "Google" / "Chrome" / "User Data"
            profile.mkdir(parents=True)
            (profile / "DevToolsActivePort").write_text("9222\n/devtools/browser/test-session-1234\n", encoding="utf-8")
            with patch.dict(os.environ, {"LOCALAPPDATA": directory}):
                self.assertEqual(_debug_endpoint("chrome"), "ws://localhost:9222/devtools/browser/test-session-1234")
                self.assertIsNone(_debug_endpoint("msedge"))

            driver = MagicMock()
            context = MagicMock()
            browser = MagicMock()
            browser.contexts = [context]
            driver.chromium.connect_over_cdp.return_value = browser
            session = ExistingBrowserSession()
            with patch.dict(os.environ, {"LOCALAPPDATA": directory}):
                session.connect(driver, "chrome", 5000)
            driver.chromium.connect_over_cdp.assert_called_once_with(
                "ws://localhost:9222/devtools/browser/test-session-1234", timeout=5000, no_defaults=True,
            )
            session.disconnect()

    def test_rejects_malformed_devtools_active_port_file(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "Google" / "Chrome" / "User Data"
            profile.mkdir(parents=True)
            (profile / "DevToolsActivePort").write_text("9222\n/json/list\n", encoding="utf-8")
            with patch.dict(os.environ, {"LOCALAPPDATA": directory}):
                self.assertIsNone(_debug_endpoint("chrome"))


class PreparationTests(unittest.TestCase):
    send = test_workflow.WorkspaceTests.send
    prepared_item = test_workflow.WorkspaceTests.prepared_item

    def setUp(self):
        self.start_patch = patch("app.main.AutomationService.start")
        self.stop_patch = patch("app.main.AutomationService.stop")
        self.start_patch.start()
        self.stop_patch.start()
        test_workflow.WorkspaceTests.setUp(self)

    def tearDown(self):
        test_workflow.WorkspaceTests.tearDown(self)
        self.start_patch.stop()
        self.stop_patch.stop()

    def test_prepare_defaults_and_factory_defect_without_invented_condition(self):
        item, source, image, payload = self.prepared_item()
        self.send(f"/api/items/{item['id']}", {"japan_title": "サンリオ SR クリアカード 9枚セット"}, method="PATCH")
        self.send(f"/api/china/sources/{source['id']}", {"account_note": "整套91张11.9元，默认厂瑕"}, method="PATCH")
        result = self.client.get(f"/api/listing/items/{item['id']}/preparation").json()
        values = result["values"]
        self.assertEqual(values["shipping_method"], "らくらくメルカリ便")
        self.assertEqual(values["condition"], "")
        self.assertEqual(values["image_asset_ids"], [])
        self.assertEqual(values["price_jpy"], 4000)
        self.assertIn("カード9枚", values["description_ja"])
        self.assertIn("初期不良", values["description_ja"])
        self.assertTrue(values["category"].endswith("カード・フォト・ブロマイド"))
        self.assertIn("商品状态", result["missing"])
        self.assertNotIn("exchange_rate_cny_per_jpy", [f["field"] for f in result["fields"]])
        self.assertFalse(result["photo_collection"]["target_met"])

    def test_confirmation_generates_snapshot_and_scheduled_refresh_is_idempotent(self):
        item, source, image, _ = self.prepared_item()
        detail = self.client.get(f"/api/items/{item['id']}").json()
        self.assertEqual(detail["listing_preparation"]["automation"]["status"], "stale")
        watch = self.send("/api/automation/watches", {
            "name": "定时整理上架资料", "kind": "listing_prepare", "interval_minutes": 60, "result_limit": 10,
        }, 201)
        service = AutomationService()
        job = service._claim()
        self.assertEqual(job["watch_id"], watch["id"])
        control = MagicMock()
        result = service._execute(job, control)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["refreshed"], 1)
        self.assertIn("商品状态", result["prepared"][0]["missing"])
        service._finish(job, "succeeded", result)
        detail = self.client.get(f"/api/items/{item['id']}").json()
        generated_at = detail["listing_preparation"]["automation"]["generated_at"]
        self.assertIsNotNone(generated_at)
        self.assertFalse(detail["listing_preparation"]["automation"]["status"] == "stale")

        repeat = self.send(f"/api/automation/watches/{watch['id']}/run", {}, 202)
        result = service._execute(repeat, control)
        self.assertEqual(result["refreshed"], 0)
        self.assertEqual(result["unchanged"], 1)
        service._finish(repeat, "succeeded", result)
        latest = self.client.get(f"/api/items/{item['id']}").json()
        self.assertEqual(latest["listing_preparation"]["automation"]["generated_at"], generated_at)

    def test_preparation_stays_current_when_item_moves_into_local_draft(self):
        item, source, image, payload = self.prepared_item()
        connection = db.connect_db()
        try:
            connection.execute(
                "UPDATE china_sources SET availability_status='unknown' WHERE id=?",
                (source["id"],),
            )
            connection.commit()
        finally:
            connection.close()

        preparation = self.send(
            f"/api/listing/items/{item['id']}/preparation?source_id={source['id']}",
            {},
        )
        self.assertTrue(any("库存尚未核实" in note for note in preparation["notes"]))
        payload["inventory_quantity"] = 1
        draft = self.send(f"/api/listing/items/{item['id']}/drafts", payload, 201)

        refreshed = self.send(f"/api/listing/items/{item['id']}/preparation", {})
        self.assertTrue(refreshed["ready_for_review"])
        self.assertEqual(refreshed["automation"]["status"], "ready_for_review")
        self.assertTrue(any("库存尚未核实" in note for note in refreshed["notes"]))

        detail = self.client.get(f"/api/items/{item['id']}").json()
        current = detail["listing_preparation"]["automation"]
        self.assertEqual(current["status"], "ready_for_review")
        self.assertEqual(current["generated_at"], refreshed["automation"]["generated_at"])
        self.assertEqual(draft["inventory_quantity"], 1)

    def test_costs_can_be_pending_and_later_recalculated(self):
        item, source, image, payload = self.prepared_item()
        costs = ("exchange_rate_cny_per_jpy", "estimated_china_to_japan_shipping_cny", "shipping_jpy", "other_costs_jpy")
        original = dict(payload)
        for name in costs:
            payload.pop(name, None)
        draft = self.send(f"/api/listing/items/{item['id']}/drafts", payload, 201)
        self.assertIsNone(draft["estimated_profit_cny"])
        self.assertIsNone(draft["estimated_margin_pct"])
        self.assertIsNone(draft["shipping_jpy"])
        updated = self.send(f"/api/listing/drafts/{draft['id']}", original, method="PUT")
        self.assertEqual(updated["estimated_profit_cny"], 60)
        original["shipping_jpy"] = None
        pending = self.send(f"/api/listing/drafts/{draft['id']}", original, method="PUT")
        self.assertIsNone(pending["estimated_profit_cny"])

    def test_old_database_migration_keeps_estimates_and_order_foreign_key(self):
        connection = db.connect_db()
        try:
            sql = connection.execute("SELECT sql FROM sqlite_master WHERE name='listing_drafts'").fetchone()[0]
            fields = ("exchange_rate_cny_per_jpy", "estimated_china_to_japan_shipping_cny", "shipping_jpy", "other_costs_jpy", "estimated_profit_cny", "estimated_margin_pct")
            for name in fields:
                sql = re.sub(rf"(\b{name}\s+(?:REAL|INTEGER))", r"\1 NOT NULL", sql)
            sql = re.sub(r"\n\s*category_attributes TEXT NOT NULL DEFAULT '\{\}',", "", sql)
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute("DROP TABLE listing_drafts")
            connection.execute(sql)
            connection.commit()
        finally:
            connection.close()
        db.init_db()
        item, source, image, payload = self.prepared_item()
        draft = self.send(f"/api/listing/items/{item['id']}/drafts", payload, 201)
        self.send(f"/api/listing/drafts/{draft['id']}/publish-confirmation", {"listing_url": "https://mercari-shops.com/products/example"})
        order = self.send("/api/orders", {"item_id": item["id"], "mercari_order_id": "migration-test", "sold_price_jpy": 4000}, 201)
        db.init_db()
        connection = db.connect_db()
        try:
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("SELECT listing_draft_id FROM sales_orders WHERE id=?", (order["id"],)).fetchone()[0], draft["id"])
            self.assertEqual(connection.execute("SELECT estimated_profit_cny FROM listing_drafts WHERE id=?", (draft["id"],)).fetchone()[0], 60)
            self.assertFalse(next(r for r in connection.execute("PRAGMA table_info(listing_drafts)") if r["name"] == "shipping_jpy")["notnull"])
            self.assertEqual(draft["category_attributes"], {})
        finally:
            connection.close()

    def test_existing_browser_settings_scope_and_fill_before_edit_confirmation(self):
        root = "https://mercari-shops.com/seller/shops/test-shop"
        saved = self.send("/api/automation/shops/settings", {"browser_mode": "existing_chrome", "browser_channel": "chrome", "url": root}, method="PUT")
        self.assertEqual(saved["url"], root)
        self.send("/api/automation/shops/settings", {"browser_mode": "existing_chrome", "url": "https://mercari-shops.com/signin/seller"}, 422, "PUT")
        item, source, image, payload = self.prepared_item()
        draft = self.send(f"/api/listing/items/{item['id']}/drafts", payload, 201)
        job = self.send(f"/api/listing/drafts/{draft['id']}/fill-shop", {}, 202)
        self.assertEqual(job["payload"]["browser_mode"], "existing_chrome")
        service = AutomationService()
        page = MagicMock()
        page.url = root + "/products/create"
        control = MagicMock()
        control.wait_for_user.side_effect = JobCancelled("stop before editing")
        with patch.object(service, "_shop", return_value=page), patch("app.automation.service.ShopsBrowserAdapter") as adapter:
            adapter.return_value.inspect.return_value = {"missing_controls": [], "fields": [{"field": "title_ja", "label": "商品名"}]}
            with self.assertRaises(JobCancelled):
                service._execute(job, control)
            adapter.return_value.fill.assert_not_called()
            adapter.return_value.save_reviewed_draft.assert_not_called()
            self.assertEqual(control.wait_for_user.call_args.args[2]["stage"], "before_fill")


class ConnectionTests(unittest.TestCase):
    def test_shop_browser_uses_isolated_login_profile_cdp_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "japan" / "shop-login"
            profile.mkdir(parents=True)
            (profile / "DevToolsActivePort").write_text(
                "9321\n/devtools/browser/shop-session-42\n", encoding="utf-8",
            )
            self.assertEqual(
                _shop_debug_endpoint("chrome", Path(directory)),
                "ws://127.0.0.1:9321/devtools/browser/shop-session-42",
            )

    def test_disconnect_preserves_external_tabs_and_context(self):
        root = "https://mercari-shops.com/seller/shops/target"
        chrome = MagicMock()
        context = MagicMock()
        other, target = MagicMock(), MagicMock()
        other.url = "https://mercari-shops.com/seller/shops/other"
        target.url = root + "/products"
        context.pages = [other, target]
        chrome.contexts = [context]
        driver = MagicMock()
        driver.chromium.connect_over_cdp.return_value = chrome
        connection = ExistingShopBrowser()
        self.assertIs(connection.connect(driver, "chrome", root, 5000), target)
        connection.disconnect()
        chrome.close.assert_called_once()
        context.close.assert_not_called()
        target.close.assert_not_called()
        other.close.assert_not_called()
        self.assertFalse(belongs_to_shop(root + "-other", root))
        self.assertFalse(belongs_to_shop("http://mercari-shops.com/seller/shops/target", root))
        self.assertFalse(belongs_to_shop("https://mercari-shops.com:444/seller/shops/target", root))
        self.assertEqual(shop_root(root + "/products"), root)

    def test_missing_target_disconnects_without_using_another_shop(self):
        driver = MagicMock()
        context = MagicMock()
        page = MagicMock()
        page.url = "https://mercari-shops.com/seller/shops/other"
        context.pages = [page]
        driver.chromium.connect_over_cdp.return_value.contexts = [context]
        connection = ExistingShopBrowser()
        with self.assertRaises(ValueError):
            connection.connect(driver, "chrome", "https://mercari-shops.com/seller/shops/target", 5000)
        context.close.assert_not_called()
        page.goto.assert_not_called()
