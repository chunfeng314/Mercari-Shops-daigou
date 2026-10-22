import json
import unittest
from io import BytesIO
from unittest.mock import patch

from PIL import Image

import test_workflow
from app import db
from app.automation.service import AutomationService, JobCancelled, JobControl
from app.automation.store import enqueue, save_watch_observations
from app.modules.japan_selection.mercari import (
    MercariCollector, canonical_url, filter_minimum_price, has_eligible_jpy_price, search_url, validate_mercari_url,
)
from app.modules.china_sourcing.xianyu import (
    DETAIL_IMAGE_EXTRACTOR, XianyuCollector, parse_display_price, search_url as xianyu_search_url,
    validate_image_url, validate_item_url as validate_xianyu_item_url,
)
from app.modules.china_sourcing.keywords import plan_search_queries
from app.source_image_collection import save_collected_image, reconcile_collected_images


class ManagementTests(unittest.TestCase):
    send = test_workflow.WorkspaceTests.send
    prepared_item = test_workflow.WorkspaceTests.prepared_item

    def test_fractional_card_price_and_japanese_derived_fallback_query(self):
        self.assertEqual(parse_display_price("商品 ¥ 189 .99 原价¥289"), 189.99)
        self.assertEqual(parse_display_price("CNY 1,299 . 50 包邮"), 1299.50)
        self.assertEqual(parse_display_price("商品 11.90 元"), 11.9)
        self.assertIsNone(parse_display_price("暂无价格"))
        queries = plan_search_queries("STARBUCKS ハロウィン2026 黒猫 ステンレスストロータンブラー 430ml オレンジ 猫チャーム付き")
        self.assertIn("430ml", queries[-1])
        self.assertIn("吸管杯", queries[-1])
        self.assertNotIn("黑猫", queries[-1])

    def test_japan_price_floor_excludes_9999_and_unknown_prices(self):
        self.assertFalse(has_eligible_jpy_price(9999))
        self.assertTrue(has_eligible_jpy_price(10000))
        self.assertFalse(has_eligible_jpy_price(None))
        eligible, stats = filter_minimum_price([
            {"price":9999}, {"price":10000}, {"price":None}, {"price":"unknown"},
        ])
        self.assertEqual([row["price"] for row in eligible], [10000])
        self.assertEqual(stats["scanned_count"], 4)
        self.assertEqual(stats["excluded_below_price_count"], 1)
        self.assertEqual(stats["excluded_unknown_price_count"], 2)

    def test_japanese_hello_kitty_camera_generates_chinese_xianyu_queries(self):
        queries = plan_search_queries(
            "【美品】ハローキティ サンリオ　フェイス型 デジタルカメラ 限定品　デジカメ",
            "■ブランド・モデル\nハローキティデジタルカメラ\n\n■動作\n撮影などの基本動作は確認済み",
        )
        self.assertTrue(queries)
        self.assertIn("数码相机", queries[0])
        self.assertIn("凯蒂猫", queries[0])
        self.assertNotRegex(" ".join(queries), r"[\u3040-\u30ff]")

    def test_blue_archive_and_arknights_candidates_generate_chinese_queries(self):
        blue_archive = plan_search_queries(
            "【中国限定】ブルーアーカイブ 假日漫步【ヒナ】グッズセット",
            "GoodSmile Moment_假日漫步 日本未発売 アクリルスタンド 缶バッジ 色紙 アクリルキーホルダー",
        )
        self.assertIn("蔚蓝档案", blue_archive[0])
        self.assertIn("空崎日奈", blue_archive[0])
        self.assertTrue(any("日奈" in query for query in blue_archive))
        self.assertIn("假日漫步", blue_archive[0])
        self.assertTrue(any("周边" in query for query in blue_archive))
        self.assertNotRegex(" ".join(blue_archive), r"[\u3040-\u30ff]")

        shirt_queries = plan_search_queries(
            "Tシャツ 天童アリス 盛夏派対シリーズ Tシャツ XLサイズ 中国限定",
        )
        self.assertTrue(any("天童爱丽丝" in query and "短袖" in query for query in shirt_queries))
        self.assertTrue(any("盛夏派对系列" in query for query in shirt_queries))

        seia = plan_search_queries(
            "【中国限定】ブルーアーカイブ 啾啾指揮家【セイア】パペットぬいぐるみ",
        )
        self.assertTrue(any("圣娅" in query and "手偶" in query for query in seia))

        arknights = plan_search_queries(
            "【中国限定】アークナイツ 7周年記念 猫山山【ケルシー】特大ぬいぐるみ",
            "#NYANHOUSEアークナイツ 高さ約65cm",
        )
        self.assertIn("明日方舟", arknights[0])
        self.assertIn("凯尔希", arknights[0])
        self.assertTrue(any("大号毛绒玩偶" in query for query in arknights))
        self.assertNotRegex(" ".join(arknights), r"[\u3040-\u30ff]")

    def test_mercari_collector_keeps_scrolling_until_it_finds_eligible_prices(self):
        pages = [
            [{"url":"https://jp.mercari.com/item/low", "title":"低价商品", "price":9999}],
            [
                {"url":"https://jp.mercari.com/item/low", "title":"低价商品", "price":9999},
                {"url":"https://jp.mercari.com/item/eligible", "title":"符合价格商品", "price":10000},
            ],
        ]

        class FakeLocator:
            def __init__(self, page):
                self.page = page
                self.first = self

            def wait_for(self, **kwargs):
                return None

            def evaluate_all(self, extractor):
                return pages[min(self.page.page_index, len(pages) - 1)]

        class FakeMouse:
            def __init__(self, page):
                self.page = page

            def wheel(self, x, y):
                self.page.page_index += 1

        class FakePage:
            def __init__(self):
                self.page_index = 0
                self.mouse = FakeMouse(self)

            def locator(self, selector):
                return FakeLocator(self)

            def wait_for_function(self, *args, **kwargs):
                return None

            def wait_for_timeout(self, timeout):
                return None

        collector = MercariCollector(FakePage())
        found = collector.collect_cards(1)
        self.assertEqual([row["price"] for row in found], [10000])
        self.assertEqual(collector.last_price_filter_stats["scanned_count"], 2)
        self.assertEqual(collector.last_price_filter_stats["excluded_below_price_count"], 1)

    def test_mercari_item_extracts_seller_profile_as_shop_expansion_seed(self):
        class Response:
            status = 200

        class FakeLocator:
            def __init__(self, selector):
                self.selector = selector

            def all_text_contents(self):
                return [json.dumps({"@type":"Product", "name":"中国限定商品", "image":[],
                                    "offers":{"price":"12000", "priceCurrency":"JPY",
                                               "availability":"https://schema.org/InStock"}})]

            def evaluate_all(self, _script):
                return [{"url":"/user/profile/402337444", "name":"中文商品卖家"}]

        class FakePage:
            url = "about:blank"

            def goto(self, url, **_kwargs):
                self.url = url
                return Response()

            def wait_for_function(self, *_args, **_kwargs):
                return None

            def locator(self, selector):
                return FakeLocator(selector)

        item = MercariCollector(FakePage()).item("https://jp.mercari.com/item/m123")[0]
        self.assertEqual(item["seller_url"], "https://jp.mercari.com/user/profile/402337444")
        self.assertEqual(item["seller_id"], "402337444")
        self.assertEqual(item["seller_name"], "中文商品卖家")

    def test_excluded_images_are_reversible_and_cannot_enter_listing_drafts(self):
        item, source, image, payload = self.prepared_item()
        self.send(f"/api/china/source-images/{image['id']}", {"excluded":True}, 422, "PATCH")
        excluded = self.send(f"/api/china/source-images/{image['id']}", {
            "excluded":True, "exclusion_reason":"图片来源待核实",
        }, method="PATCH")
        self.assertTrue(excluded["excluded_at"])
        detail = self.client.get(f"/api/items/{item['id']}").json()
        self.assertEqual(detail["listing_preparation"]["photo_collection"]["unique_count"], 0)
        self.assertEqual(detail["listing_preparation"]["photo_collection"]["real_photo_count"], 0)
        self.send(f"/api/listing/items/{item['id']}/drafts", payload, 422)
        self.assertEqual(self.client.get(image["source_file_url"]).status_code, 200)
        restored = self.send(f"/api/china/source-images/{image['id']}", {"excluded":False}, method="PATCH")
        self.assertIsNone(restored["excluded_at"])
        self.assertEqual(restored["image_role"], "other")
        self.send(f"/api/listing/items/{item['id']}/drafts", payload, 201)

    def test_rescan_quarantines_legacy_extras_and_deduplicates_cdn_resizes(self):
        item, source, manual, _payload = self.prepared_item()
        connection = db.connect_db()
        try:
            def capture(name, colour):
                buffer = BytesIO()
                Image.new("RGB", (150,150), colour).save(buffer, format="PNG")
                return save_collected_image(connection, source["id"], "https://www.goofish.com/item?id=123",
                    f"https://img.alicdn.com/item/{name}.jpg_450x10000Q90.jpg_.webp", "闲鱼商品详情页图片候选", buffer.getvalue())
            main = capture("main", "red")
            extra = capture("extra", "blue")
            legacy = capture("legacy", "green")
            duplicate = save_collected_image(connection, source["id"], "https://www.goofish.com/item?id=123",
                "https://img.alicdn.com/item/main.jpg_790x10000Q90.jpg_.webp", "闲鱼商品详情页图片候选", b"not downloaded again")
            self.assertTrue(duplicate["duplicate"])
            self.assertEqual(duplicate["id"], main["id"])
            detail = {"images":[{"url":"https://img.alicdn.com/item/main.jpg_Q90.jpg_.webp"}],
                      "single_image_gallery":True,
                      "excluded_images":[{"url":"https://img.alicdn.com/item/extra.jpg_790x10000Q90.jpg_.webp"}]}
            excluded = reconcile_collected_images(connection, source["id"], item["id"], detail)
            self.assertEqual(set(excluded), {extra["id"], legacy["id"]})
            self.assertIsNone(connection.execute("SELECT excluded_at FROM source_images WHERE id=?", (manual["id"],)).fetchone()[0])
            self.assertIsNone(connection.execute("SELECT excluded_at FROM source_images WHERE id=?", (main["id"],)).fetchone()[0])
            self.assertEqual(reconcile_collected_images(connection, source["id"], item["id"], detail), [])
            connection.commit()
        finally:
            connection.close()

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

    def listed(self):
        item, source, image, payload = self.prepared_item()
        draft = self.send(f"/api/listing/items/{item['id']}/drafts", payload, 201)
        self.send(f"/api/listing/drafts/{draft['id']}/publish-confirmation", {"listing_url":"https://mercari-shops.com/products/test-product"})
        return item, source, draft

    def order(self, item, number="test-order", quantity=1):
        return self.send("/api/orders", {"item_id":item["id"],"mercari_order_id":number,"quantity":quantity,"sold_price_jpy":5000}, 201)

    def test_edit_archive_restore_and_source_integrity(self):
        item, source, image, payload = self.prepared_item()
        updated = self.send(f"/api/items/{item['id']}", {"japan_title":"修正商品名", "japan_price_jpy":None}, method="PATCH")
        self.assertEqual(updated["japan_title"], "修正商品名")
        self.assertIsNone(updated["japan_price_jpy"])
        self.send(f"/api/items/{item['id']}", {"japan_title":" "}, 422, "PATCH")
        self.send(f"/api/items/{item['id']}/archive", {})
        self.assertEqual(self.client.get("/api/items").json(), [])
        self.assertEqual(len(self.client.get("/api/items?include_archived=true").json()), 1)
        self.send(f"/api/china/items/{item['id']}/sources", {"china_site":"xianyu","source_url":"https://example.com/other"}, 409)
        self.send(f"/api/items/{item['id']}/restore", {})
        self.send(f"/api/china/sources/{source['id']}/archive", {})
        self.assertEqual(self.client.get(f"/api/items/{item['id']}").json()["item"]["status"], "sourcing")
        self.send(f"/api/china/sources/{source['id']}/restore", {})
        self.send(f"/api/listing/items/{item['id']}/drafts", payload, 201)
        self.send(f"/api/items/{item['id']}", {"japan_url":"https://jp.mercari.com/item/m999999"}, 409, "PATCH")
        self.send(f"/api/china/sources/{source['id']}", {"source_url":"https://example.com/different"}, 409, "PATCH")
        self.send(f"/api/china/sources/{source['id']}", {"price_cny":"Infinity"}, 422, "PATCH")
        self.send(f"/api/china/sources/{source['id']}", {"price_cny":90,"account_note":"新报价"}, method="PATCH")
        detail = self.client.get(f"/api/items/{item['id']}").json()
        self.assertEqual(detail["listing_draft"]["estimated_source_price_cny"],80)
        self.assertTrue(detail["events"])

    def test_changing_candidate_identity_requires_reconfirmation(self):
        item, source, image, payload = self.prepared_item()
        changed = self.send(f"/api/items/{item['id']}", {"japan_url":"https://jp.mercari.com/item/m999999"}, method="PATCH")
        self.assertEqual(changed["status"], "sourcing")
        detail = self.client.get(f"/api/items/{item['id']}").json()
        self.assertEqual(detail["china_sources"][0]["match_status"], "pending")
        self.send(f"/api/listing/items/{item['id']}/drafts", payload, 409)

    def test_repeated_shop_fill_reuses_pending_job(self):
        item, source, image, payload = self.prepared_item()
        draft = self.send(f"/api/listing/items/{item['id']}/drafts", payload, 201)
        path = f"/api/listing/drafts/{draft['id']}/fill-shop"
        first = self.send(path, {}, 202)
        second = self.send(path, {}, 202)
        self.assertEqual(first["id"], second["id"])
        self.send(f"/api/automation/jobs/{first['id']}/cancel", {})
        next_job = self.send(path, {}, 202)
        self.assertNotEqual(first["id"], next_job["id"])

    def test_alternative_source_after_listing_and_cancel_inventory(self):
        item, source, draft = self.listed()
        self.send(f"/api/items/{item['id']}/archive", {}, 409)
        replacement = self.send(f"/api/china/items/{item['id']}/sources", {"china_site":"xiaohongshu","source_url":"https://example.com/replacement","price_cny":76}, 201)
        self.send(f"/api/china/sources/{replacement['id']}/confirm", {"match_note":"已核对规格一致","availability_status":"available"})
        order = self.order(item, quantity=3)
        cancelled = self.send(f"/api/orders/{order['id']}/cancellation", {"reason":"买家取消","release_inventory":True})
        self.assertEqual(cancelled["order_status"], "cancelled")
        self.send(f"/api/orders/{order['id']}/purchase-confirmation", {"china_source_id":source["id"],"actual_price_cny":80},409)
        replacement_order = self.order(item,"replacement-order",quantity=3)
        self.send(f"/api/orders/{replacement_order['id']}/purchase-confirmation", {"china_source_id":replacement["id"],"actual_price_cny":228})
        self.assertEqual(self.client.get(f"/api/items/{item['id']}").json()["item"]["status"],"listed")

    def test_returns_refunds_and_stock_withdrawal(self):
        item, source, draft = self.listed()
        order = self.order(item)
        base=f"/api/orders/{order['id']}"
        self.send(base+"/purchase-confirmation",{"china_source_id":source["id"],"actual_price_cny":80})
        self.send(base+"/china-shipment",{"carrier":"顺丰","tracking_number":"CN1"})
        self.send(base+"/japan-receipt",{"inspection_result":"passed"})
        self.send(base+"/domestic-shipment",{"carrier":"ヤマト","tracking_number":"JP1"})
        self.send(base+"/cancellation",{"reason":"退款退货","release_inventory":True},409)
        self.send(base+"/return-receipt",{"note":"已收到并检查退回商品"})
        self.send(base+"/cancellation",{"reason":"退款退货","release_inventory":True})
        refund={"refund_reference":"refund-001","amount_jpy":3000,"reason":"部分退款"}
        first=self.send(base+"/refund-confirmation",refund)
        second=self.send(base+"/refund-confirmation",refund)
        self.assertEqual(first["refunded_amount_jpy"],second["refunded_amount_jpy"])
        self.send(base+"/refund-confirmation",{**refund,"refund_reference":"refund-002","amount_jpy":2500},422)
        self.send(base+"/refund-confirmation",{**refund,"refund_reference":"refund-002","amount_jpy":2000})
        self.assertEqual(self.client.get(base).json()["refunded_amount_jpy"],5000)
        self.send(f"/api/listing/drafts/{draft['id']}/inventory-confirmation",{"remaining_quantity":0,"note":"店铺已无库存"})
        self.send("/api/orders",{"item_id":item["id"],"mercari_order_id":"no-stock","sold_price_jpy":4000},409)
        self.send(f"/api/listing/drafts/{draft['id']}/withdrawal-confirmation",{"reason":"已在店铺下架"})
        self.send(f"/api/items/{item['id']}/archive",{})

    def test_jobs_import_deduplication_and_cancel(self):
        job=self.send("/api/japan/search",{"query":"中国限定","limit":3},202)
        connection=db.connect_db()
        try:
            result={"items":[
                {"url":"https://jp.mercari.com/shops/product/product1","title":"真实样例","price":13000,"image_url":None},
                {"url":"https://jp.mercari.com/item/cheap1","title":"低价样例","price":9999,"image_url":None},
            ],"collected_at":"2026-10-17"}
            connection.execute("UPDATE automation_jobs SET status='succeeded',result=? WHERE id=?",(json.dumps(result),job["id"]))
            connection.commit()
        finally: connection.close()
        imported=self.send(f"/api/automation/jobs/{job['id']}/import",{"indexes":[0]})
        self.assertEqual(len(imported["imported"]),1)
        again=self.send(f"/api/automation/jobs/{job['id']}/import",{"indexes":[0]})
        self.assertEqual(len(again["skipped"]),1)
        low_price=self.send(f"/api/automation/jobs/{job['id']}/import",{"indexes":[1]})
        self.assertEqual(low_price["imported"],[])
        self.assertEqual(low_price["skipped"][0]["reason"],"price_below_minimum")
        self.send(f"/api/automation/jobs/{job['id']}/import",{"indexes":[-1]},422)
        self.send("/api/japan/collect/item",{"url":"http://127.0.0.1/private"},422)
        queued=self.send("/api/japan/search",{"query":"新品"},202)
        cancelled=self.send(f"/api/automation/jobs/{queued['id']}/cancel",{})
        self.assertEqual(cancelled["status"],"cancelled")
        self.send(f"/api/automation/jobs/{job['id']}/resume",{},409)

    def test_xianyu_search_uses_local_browser_job_and_imports_pending_sources(self):
        item = self.send("/api/japan/candidates", {
            "japan_site":"mercari", "japan_url":"https://jp.mercari.com/item/m123",
            "japan_title":"ポケモンカード SR", "japan_price_jpy":1200,
        }, 201)
        queued = self.send("/api/china/search", {"item_id":item["id"], "browser_channel":"msedge", "limit":4}, 202)
        self.assertEqual(queued["kind"], "china_search")
        self.assertEqual(queued["payload"]["browser_mode"], "managed")
        self.assertIn("宝可梦", queued["payload"]["queries"][0])
        self.assertIn("卡牌", queued["payload"]["queries"][0])
        self.assertEqual(plan_search_queries("サンリオ ハンギョドン SR クリアカード" )[0], "三丽鸥 汉顿 Hangyodon SR 透明卡")
        starbucks_terms = plan_search_queries("STARBUCKS スターバックス ハロウィン2026 黒猫 ステンレスストロータンブラー")
        self.assertIn("星巴克", starbucks_terms[0])
        self.assertIn("万圣节", starbucks_terms[0])
        self.assertIn("不锈钢吸管杯", starbucks_terms[0])
        cleaned_terms = plan_search_queries(
            "【新品】STARBUCKS スターバックス ハロウィン2026 黒猫 ステンレスストロータンブラー 430ml オレンジ 猫チャーム付き",
            "Mercari 页面采集：2026-10-19T06:55:24+00:00",
        )
        self.assertTrue(cleaned_terms)
        self.assertTrue(all("页面采集" not in term and "付き" not in term for term in cleaned_terms))
        self.assertIn("https://www.goofish.com/search?", xianyu_search_url("宝可梦卡牌"))
        alice_queries = plan_search_queries(
            "Tシャツ 天童アリス 盛夏派対シリーズ Tシャツ XLサイズ 中国限定",
            "Mercari 页面采集：2026-10-21\n#ブルーアーカイブ\n#ブルアカ",
        )
        self.assertTrue(any("短袖" in query for query in alice_queries))
        self.assertIn("天童爱丽丝", alice_queries[0])
        self.assertTrue(any("盛夏派对系列" in query for query in alice_queries))
        self.assertTrue(any("蔚蓝档案" in query for query in alice_queries))
        self.assertEqual(alice_queries[0], "天童爱丽丝 蔚蓝档案 短袖")
        self.assertTrue(any("天童爱丽丝" in query and "中国限定" not in query and "XL码" not in query
                            for query in alice_queries))
        self.assertEqual(validate_xianyu_item_url("https://www.goofish.com/item?spm=x&id=989310008858&categoryId=1"),
                         "https://www.goofish.com/item?id=989310008858")
        connection = db.connect_db()
        try:
            result = {"item_id":item["id"], "items":[
                {"url":"https://www.goofish.com/item?spm=x&id=989310008858", "title":"宝可梦卡牌 SR 套装", "price":11.9, "currency":"CNY"}
            ]}
            connection.execute("UPDATE automation_jobs SET status='succeeded',result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), queued["id"]))
            connection.commit()
        finally:
            connection.close()
        imported = self.send(f"/api/automation/jobs/{queued['id']}/import-china-sources", {"indexes":[0]})
        self.assertEqual(len(imported["imported"]), 1)
        self.assertEqual(imported["image_job"]["kind"], "china_source_images")
        self.assertEqual(imported["image_job"]["payload"]["browser_mode"], "managed")
        self.assertEqual(imported["image_job"]["payload"]["source_ids"], [imported["imported"][0]["id"]])
        source_id = imported["imported"][0]["id"]
        source = self.client.get(f"/api/china/items/{item['id']}/sources")
        self.assertEqual(source.status_code, 200, source.text)
        self.assertEqual(source.json()[0]["match_status"], "pending")
        self.assertEqual(source.json()[0]["price_cny"], 11.9)
        self.assertEqual(self.client.get(f"/api/items/{item['id']}").json()["item"]["status"], "sourcing")
        repeated = self.send(f"/api/automation/jobs/{queued['id']}/import-china-sources", {"indexes":[0]})
        self.assertEqual(repeated["skipped"][0]["id"], source_id)
        self.assertIsNone(repeated["image_job"], "pending photo collection must not be queued twice")
        with self.assertRaises(ValueError):
            validate_xianyu_item_url("https://example.com/item?id=123")

    def test_xianyu_detail_collection_keeps_review_photo_context_and_validates_cdn(self):
        class Response:
            status = 200

        class FakePage:
            url = "about:blank"

            def goto(self, url, **_kwargs):
                self.url = url
                return Response()

            def evaluate(self, script, *_args):
                if script == DETAIL_IMAGE_EXTRACTOR:
                    return {
                        "title": "闲鱼商品详情",
                        "text": "商品描述 评论区",
                        "images": [
                            {"url":"https://img.alicdn.com/item/photo.jpg", "alt":"买家晒单", "context":"评论区 实拍" ,"width":800,"height":800},
                            {"url":"https://img.alicdn.com/item/recommended.jpg", "alt":"", "context":"为你推荐 足球直播", "region":"item-feeds-list-container--abc123", "width":800,"height":800},
                            {"url":"http://127.0.0.1/private.jpg", "alt":"", "context":"", "width":800,"height":800},
                        ],
                    }
                return None

            def wait_for_timeout(self, _ms):
                pass

        collector = XianyuCollector(FakePage())
        detail = collector.collect_detail_images("https://www.goofish.com/item?id=123")
        self.assertEqual(detail["title"], "闲鱼商品详情")
        self.assertEqual(len(detail["images"]), 1)
        self.assertEqual(len(detail["excluded_images"]), 1)
        self.assertIn("item-feeds-list", detail["excluded_images"][0]["region"])
        self.assertIn("评论", detail["images"][0]["collection_note"])
        self.assertEqual(validate_image_url("https://img.alicdn.com/item/photo.jpg?x=1"),
                         "https://img.alicdn.com/item/photo.jpg?x=1")
        with self.assertRaises(ValueError):
            validate_image_url("https://alicdn.com.attacker.example/image.jpg")

    def test_xianyu_search_stops_scrolling_when_results_do_not_grow(self):
        class Response:
            status = 200

        class FakeLocator:
            first = None

            def __init__(self):
                self.first = self

            def wait_for(self, **_kwargs):
                pass

            def evaluate_all(self, _script):
                return [{
                    "url": "https://www.goofish.com/item?id=123",
                    "title": "星巴克黑猫吸管杯",
                    "price": 189,
                    "image_url": "https://img.alicdn.com/item/photo.jpg",
                    "text": "商品描述",
                }]

        class FakePage:
            url = "about:blank"

            def __init__(self):
                self.scrolls = 0
                self.locator_instance = FakeLocator()

            def goto(self, url, **_kwargs):
                self.url = url
                return Response()

            def locator(self, _selector):
                return self.locator_instance

            def evaluate(self, _script):
                self.scrolls += 1

            def wait_for_timeout(self, _ms):
                pass

        page = FakePage()
        items = XianyuCollector(page).search("星巴克黑猫吸管杯", limit=10)
        self.assertEqual(len(items), 1)
        self.assertEqual(page.scrolls, 1)

    def test_automatically_collected_images_need_human_real_photo_confirmation(self):
        item, source, _image, _payload = self.prepared_item()
        buffer = BytesIO()
        Image.new("RGB", (120, 120), "red").save(buffer, format="PNG")
        connection = db.connect_db()
        try:
            saved = save_collected_image(
                connection, source["id"], "https://www.goofish.com/item?id=source-1",
                "https://img.alicdn.com/source/photo.png", "详情页评论/晒单区域候选", buffer.getvalue(),
            )
            connection.commit()
        finally:
            connection.close()
        image = self.client.get(f"/api/items/{item['id']}").json()["china_sources"][0]["images"][0]
        self.assertEqual(image["image_role"], "other")
        self.assertEqual(image["collection_note"], "详情页评论/晒单区域候选")
        updated = self.send(f"/api/china/source-images/{saved['id']}", {"image_role":"real_photo"}, method="PATCH")
        self.assertEqual(updated["image_role"], "real_photo")

    def test_china_image_job_persists_detail_candidates_as_unverified(self):
        item, source, _image, _payload = self.prepared_item()
        connection = db.connect_db()
        try:
            connection.execute(
                "UPDATE china_sources SET source_url=? WHERE id=?",
                ("https://www.goofish.com/item?id=source-1", source["id"]),
            )
            connection.commit()
        finally:
            connection.close()

        class Response:
            status = 200

        class FakeLocator:
            def __init__(self, page):
                self.page = page
                self.first = self

            def wait_for(self, **_kwargs):
                pass

            def evaluate(self, _script):
                return {"width": 300, "height": 300}

            def screenshot(self, **_kwargs):
                suffix = self.page.url.rsplit("photo", 1)[-1].split(".", 1)[0]
                colors = [(200, 10, 20), (10, 200, 20), (20, 10, 200), (180, 180, 10), (10, 180, 180)]
                stream = BytesIO()
                Image.new("RGB", (150, 150), colors[int(suffix)]).save(stream, format="PNG")
                return stream.getvalue()

        class FakePage:
            url = "about:blank"

            def goto(self, url, **_kwargs):
                self.url = url
                return Response()

            def evaluate(self, script, *_args):
                if script == DETAIL_IMAGE_EXTRACTOR:
                    return {
                        "title": "闲鱼商品详情",
                        "text": "商品描述 评论区晒单",
                        "images": [
                            {"url":f"https://img.alicdn.com/item/photo{i}.png", "alt":"晒单图" if i == 0 else "商品图",
                             "context":"评论区晒单" if i == 0 else "商品详情", "width":300,"height":300}
                            for i in range(5)
                        ],
                    }
                return None

            def wait_for_timeout(self, _ms):
                pass

            def locator(self, _selector):
                return FakeLocator(self)

            def route(self, *_args):
                pass

            def unroute(self, *_args):
                pass

        class Control:
            def check(self):
                pass

            def progress(self, _message):
                pass

        page = FakePage()
        service = AutomationService()
        job = {"kind":"china_source_images", "payload":{
            "item_id":item["id"], "source_ids":[source["id"]], "browser_channel":"chrome",
            "browser_mode":"existing_chrome",
        }}
        with patch.object(service, "_driver"), \
             patch.object(service.existing_browser, "connect", return_value=page), \
             patch.object(service.existing_browser, "disconnect"):
            result = service._execute(job, Control())
        self.assertEqual(result["count"], 5)
        self.assertEqual(result["sources"][0]["total_images"], 6)
        self.assertTrue(any("评论" in image["collection_note"] for image in self.client.get(
            f"/api/china/sources/{source['id']}/images").json()))
        self.assertEqual(sum(image["image_role"] == "other" for image in self.client.get(
            f"/api/china/sources/{source['id']}/images").json()), 5)

    def test_watch_delta_and_pausing(self):
        watch=self.send("/api/automation/watches",{"name":"关键词监控","kind":"japan_search","query":"中国限定","interval_minutes":60},201)
        connection=db.connect_db()
        try:
            job=enqueue(connection,"japan_search",{},watch["id"])
            item={"url":"https://jp.mercari.com/item/m123","title":"中国限定","price":3000}
            first=save_watch_observations(connection,watch["id"],job["id"],[item])
            second=save_watch_observations(connection,watch["id"],job["id"],[item])
            third=save_watch_observations(connection,watch["id"],job["id"],[{**item,"price":2500}])
            connection.commit()
            self.assertEqual(first,{"new":1,"price_changed":0})
            self.assertEqual(second,{"new":0,"price_changed":0})
            self.assertEqual(third,{"new":0,"price_changed":1})
        finally: connection.close()
        self.send(f"/api/automation/watches/{watch['id']}",{"enabled":False},method="PATCH")
        self.assertEqual(len(self.client.get(f"/api/automation/watches/{watch['id']}/changes").json()),2)
        self.send(f"/api/automation/watches/{watch['id']}",{},method="DELETE")
        self.assertEqual(self.client.get('/api/automation/watches').json(),[])
        self.send(f"/api/automation/watches/{watch['id']}/restore", {})
        restored = self.client.get('/api/automation/watches').json()[0]
        self.assertFalse(restored['enabled'])

    def test_shop_order_mapping_is_atomic_and_idempotent(self):
        item,source,draft=self.listed()
        connection=db.connect_db()
        try:
            connection.execute("INSERT INTO shop_order_imports(id,external_order_id,external_product_url,title,quantity,amount_jpy,created_at) VALUES('import1','shop-order','https://mercari-shops.com/products/test-product','商品',0,NULL,'2026-10-17')")
            connection.commit()
        finally: connection.close()
        path='/api/automation/shop-order-imports/import1/confirm'
        self.send(path,{"item_id":item["id"]},422)
        first=self.send(path,{"item_id":item["id"],"quantity":1,"amount_jpy":4000})
        second=self.send(path,{"item_id":item["id"],"quantity":1,"amount_jpy":4000})
        self.assertEqual(first["id"],second["id"])
        self.assertEqual(len(self.client.get('/api/orders').json()),1)

    def test_mercari_urls_and_persistent_cancellation(self):
        self.assertIn('keyword=',search_url('中国限定'))
        self.assertEqual(canonical_url('https://jp.mercari.com/shops/product/abc?x=1'),'https://mercari-shops.com/products/abc')
        for url in ('https://jp.mercari.com.evil.test/item/m1','https://jp.mercari.com@evil.test/item/m1','file:///etc/passwd'):
            with self.assertRaises(ValueError): validate_mercari_url(url,'item')
        job=self.send('/api/japan/search',{'query':'中国限定'},202)
        connection=db.connect_db()
        try:
            connection.execute('UPDATE automation_jobs SET cancel_requested=1 WHERE id=?',(job['id'],));connection.commit()
        finally: connection.close()
        with self.assertRaises(JobCancelled): JobControl(AutomationService(),job['id']).check()
