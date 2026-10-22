"""HTTP integration checks using an isolated database and isolated image files.

Run: .venv-win\Scripts\python.exe -m unittest discover -s tests -v
"""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import app


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        settings = Settings(database_path=Path(self.directory.name) / "test.sqlite3")
        self.db_patch = patch("app.db.settings", settings)
        self.image_patch = patch("app.image_assets.settings", settings)
        self.db_patch.start()
        self.image_patch.start()
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.image_patch.stop()
        self.db_patch.stop()
        self.directory.cleanup()

    def send(self, path, payload, expected=200, method="POST"):
        response = self.client.request(method, path, json=payload)
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def prepared_item(self):
        item = self.send("/api/japan/candidates", {
            "japan_site": "mercari", "japan_url": "https://example.com/japan",
            "japan_title": "测试商品 <script>alert(1)</script>", "japan_price_jpy": 4000,
        }, 201)
        source = self.send(f"/api/china/items/{item['id']}/sources", {
            "china_site": "xianyu", "source_url": "https://example.com/china",
            "source_title": "中国货源", "price_cny": 80,
        }, 201)
        self.send(f"/api/china/sources/{source['id']}/confirm", {
            "match_note": "颜色、尺寸、版本与成色一致", "availability_status": "available", "price_cny": 80,
        })
        image_data = BytesIO()
        Image.new("RGBA", (30, 20), (10, 100, 80, 100)).save(image_data, format="PNG")
        upload = self.client.post(f"/api/china/sources/{source['id']}/images", data={
            "source_page_url": source["source_url"], "image_role": "real_photo",
        }, files={"file": ("test.png", image_data.getvalue(), "image/png")})
        self.assertEqual(upload.status_code, 201, upload.text)
        image = upload.json()
        self.assertEqual(image["vision_review"], {})
        self.assertEqual(self.client.get(image["listing_file_url"]).headers["content-type"], "image/jpeg")
        payload = {
            "china_source_id": source["id"], "title_ja": "日本語の商品名",
            "image_asset_ids": [image["id"]], "category": "雑貨", "condition": "新品、未使用",
            "inventory_quantity": 3, "shipping_method": "宅急便", "shipping_payer": "送料込み",
            "shipping_origin": "東京都", "handling_days": "2〜3日", "price_jpy": 4000,
            "exchange_rate_cny_per_jpy": .05, "mercari_fee_rate": .1,
            "shipping_jpy": 500, "estimated_china_to_japan_shipping_cny": 15, "other_costs_jpy": 0,
        }
        return item, source, image, payload

    def test_pages_and_empty_state(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("煤炉", page.text)
        self.assertEqual(self.client.get("/static/app.js").status_code, 200)
        self.assertEqual(self.client.get("/static/style.css").status_code, 200)
        self.assertEqual(self.client.get("/api/items").json(), [])
        self.assertEqual(self.client.get("/api/orders").json(), [])
        automation_status = self.client.get("/api/automation/status").json()
        self.assertFalse(automation_status["image_review_enabled"])
        self.assertFalse(automation_status["image_review_configured"])

    def test_complete_workflow_and_edit_guards(self):
        item, source, image, payload = self.prepared_item()
        payload["category_attributes"] = {"material": {"value": "PVC", "source": "货源详情", "evidence": "材质：PVC"}}
        draft = self.send(f"/api/listing/items/{item['id']}/drafts", payload, 201)
        self.assertEqual(draft["estimated_profit_cny"], 60)
        self.assertEqual(draft["category_attributes"]["material"]["value"], "PVC")
        created_at = draft["created_at"]
        payload.update(price_jpy=5000, description_ja="変更した説明")
        updated = self.send(f"/api/listing/drafts/{draft['id']}", payload, method="PUT")
        self.assertEqual(updated["id"], draft["id"])
        self.assertEqual(updated["created_at"], created_at)
        self.assertEqual(updated["estimated_profit_cny"], 105)
        self.assertEqual(updated["description_ja"], "変更した説明")
        invalid = dict(payload, image_asset_ids=["another-source-image"])
        self.send(f"/api/listing/drafts/{draft['id']}", invalid, 422, "PUT")
        self.send(f"/api/listing/drafts/{draft['id']}/publish-confirmation", {"listing_url": "https://example.com/listed"})
        self.send(f"/api/listing/drafts/{draft['id']}", payload, 409, "PUT")
        self.send("/api/orders", {"item_id":item["id"], "mercari_order_id":"too-many", "quantity":4, "sold_price_jpy":20000}, 409)
        order = self.send("/api/orders", {"item_id":item["id"], "mercari_order_id":"order-1", "quantity":1, "sold_price_jpy":5000}, 201)
        base = f"/api/orders/{order['id']}"
        self.send(base + "/domestic-shipment", {"carrier":"ヤマト", "tracking_number":"JP001"}, 409)
        self.send(base + "/purchase-confirmation", {"china_source_id":source["id"], "actual_price_cny":78, "actual_china_to_japan_shipping_cny":14})
        self.send(base + "/china-shipment", {"carrier":"顺丰", "tracking_number":"CN001"})
        self.send(base + "/japan-receipt", {"inspection_result":"issue", "inspection_note":"包装需处理"})
        self.send(base + "/domestic-shipment", {"carrier":"ヤマト", "tracking_number":"JP001"}, 409)
        self.send(base + "/japan-receipt", {"inspection_result":"passed", "inspection_note":"处理后验收通过"})
        self.send(base + "/domestic-shipment", {"carrier":"ヤマト", "tracking_number":"JP001"})
        delivered = self.send(base + "/delivery-confirmation", {})
        self.assertEqual(delivered["domestic_status"], "delivered")
        self.assertEqual(delivered["actual_purchase_price_cny"], 78)
        listing = self.client.get("/api/items").json()[0]
        self.assertEqual(listing["source_count"], 1)
        self.assertEqual(listing["thumbnail_image_id"], image["id"])
        self.assertEqual(listing["status"], "listed")


if __name__ == "__main__":
    unittest.main()
