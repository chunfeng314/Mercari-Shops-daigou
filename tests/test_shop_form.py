"""Opt in: BROWSER_FORM_TESTS=1; uses a separate headless browser and intercepted fixture."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from app.modules.mercari_listing.browser_adapter import ShopsBrowserAdapter


@unittest.skipUnless(os.getenv("BROWSER_FORM_TESTS") == "1", "set BROWSER_FORM_TESTS=1 for isolated form checks")
class ShopFormTests(unittest.TestCase):
    def test_empty_orders_ignore_bulk_upload_navigation(self):
        root = "https://mercari-shops.com/seller/shops/fixture"
        with sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page()
                html = f'<meta charset="utf-8"><h2>注文一覧</h2><a href="{root}/orders/upload">一括発送通知</a><table><tbody></tbody></table><p>注文はありません</p>'
                page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
                page.goto(root + "/orders")
                self.assertEqual(ShopsBrowserAdapter(page, expected_shop=root).read_orders(), [])
            finally:
                browser.close()

    def test_actual_form_names_popups_disabled_payer_and_formatted_price(self):
        root = "https://mercari-shops.com/seller/shops/fixture"
        with TemporaryDirectory() as directory, sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page()
                html = (Path(__file__).parent / "fixtures/shop_product_form.html").read_text(encoding="utf-8")
                page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
                page.goto(root + "/products/create")
                image_path = Path(directory) / "image.jpg"
                image_path.write_bytes(b"fixture image")
                draft = dict(title_ja="テスト9枚", description_ja="検証用", inventory_quantity=1, price_jpy=1099,
                             category="ゲーム・おもちゃ・グッズ > キャラクターグッズ > カード・フォト・ブロマイド", condition="やや傷や汚れあり",
                             category_attributes={"attributes.material": {"value": "PVC", "source": "货源详情", "evidence": "材质：PVC"}},
                             brand="サンリオ", shipping_method="らくらくメルカリ便", shipping_payer="送料込み（出品者負担）", shipping_origin="東京都", handling_days="4〜7日で発送")
                adapter = ShopsBrowserAdapter(page, expected_shop=root)
                page.evaluate("""()=>{const selects=[...document.querySelectorAll('select')];const html=selects.map(e=>e.outerHTML).join('');selects.forEach(e=>e.remove());setTimeout(()=>document.body.insertAdjacentHTML('beforeend',html),150)}""")
                self.assertFalse(adapter.inspect()["missing_controls"])
                with patch("app.modules.mercari_listing.browser_adapter.resolve_image_path", return_value=image_path):
                    report = adapter.fill(draft, [{"listing_path": "fixture"}])
                self.assertEqual(page.locator('input[name="price"]').input_value(), "¥1099")
                self.assertEqual(page.locator('select[name="shippingFromState.id"]').input_value(), "jp13")
                self.assertEqual(page.get_by_test_id("condition-select-box").inner_text(), "やや傷や汚れあり")
                self.assertTrue(page.get_by_test_id("categories").inner_text().endswith("カード・フォト・ブロマイド"))
                self.assertEqual(page.locator('select[name="attributes.material"]').input_value(), "pvc")
                self.assertEqual(report["category_fields"][0]["status"], "filled")
                self.assertEqual(report["category_fields"][0]["evidence"]["source"], "货源详情")
                self.assertEqual(report["needs_manual"], [])
                self.assertEqual([f["field"] for f in report["skipped_optional"]], ["brand"])
                self.assertIn("商品图片（1 张）", report["filled"])
                self.assertTrue(adapter.save_reviewed_draft()["saved"])
                self.assertFalse(page.evaluate("Boolean(window.published)"))
                with patch("app.modules.mercari_listing.browser_adapter.resolve_image_path", return_value=image_path):
                    resumed = adapter.fill(draft, [{"listing_path": "fixture"}])
                self.assertIn("商品图片（1 张）", resumed["filled"])
                self.assertFalse(page.evaluate("Boolean(window.published)"))
            finally:
                browser.close()

    def test_missing_required_category_attribute_is_reported(self):
        root = "https://mercari-shops.com/seller/shops/fixture"
        with TemporaryDirectory() as directory, sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page()
                html = (Path(__file__).parent / "fixtures/shop_product_form.html").read_text(encoding="utf-8")
                page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
                page.goto(root + "/products/create")
                image_path = Path(directory) / "image.jpg"
                image_path.write_bytes(b"fixture image")
                draft = dict(title_ja="テスト商品", inventory_quantity=1, price_jpy=1099,
                             category="ゲーム・おもちゃ・グッズ > キャラクターグッズ > カード・フォト・ブロマイド",
                             condition="やや傷や汚れあり")
                adapter = ShopsBrowserAdapter(page, expected_shop=root)
                with patch("app.modules.mercari_listing.browser_adapter.resolve_image_path", return_value=image_path):
                    report = adapter.fill(draft, [{"listing_path": "fixture"}])
                self.assertEqual(page.locator('select[name="attributes.material"]').input_value(), "")
                missing = next(row for row in report["needs_manual"] if row["field"] == "attributes.material")
                self.assertTrue(missing["required"])
                self.assertEqual([option["label"] for option in missing["options"]], ["PVC", "紙"])
                self.assertEqual(report["category_fields"][0]["status"], "missing_required")
            finally:
                browser.close()

    def test_category_attribute_without_evidence_is_not_autofilled(self):
        root = "https://mercari-shops.com/seller/shops/fixture"
        with TemporaryDirectory() as directory, sync_playwright() as driver:
            browser = driver.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page()
                html = (Path(__file__).parent / "fixtures/shop_product_form.html").read_text(encoding="utf-8")
                page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
                page.goto(root + "/products/create")
                image_path = Path(directory) / "image.jpg"
                image_path.write_bytes(b"fixture image")
                draft = dict(title_ja="テスト商品", inventory_quantity=1, price_jpy=1099,
                             category="ゲーム・おもちゃ・グッズ > キャラクターグッズ > カード・フォト・ブロマイド",
                             category_attributes={"attributes.material": "PVC"}, condition="やや傷や汚れあり")
                adapter = ShopsBrowserAdapter(page, expected_shop=root)
                with patch("app.modules.mercari_listing.browser_adapter.resolve_image_path", return_value=image_path):
                    report = adapter.fill(draft, [{"listing_path": "fixture"}])
                self.assertEqual(page.locator('select[name="attributes.material"]').input_value(), "")
                issue = next(row for row in report["needs_manual"] if row["field"] == "attributes.material")
                self.assertIn("来源原文或来源链接", issue["reason"])
            finally:
                browser.close()
