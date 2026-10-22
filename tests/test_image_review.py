import json
import sqlite3
from io import BytesIO
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from PIL import Image

from app.modules.china_sourcing.image_review import (
    ImageCandidate,
    ImageReviewAgent,
    QwenVisionClient,
    _reference_image_data_uri,
    parse_review_json,
    review_source_images,
)


class ImageReviewTests(unittest.TestCase):
    def test_disabled_agent_never_calls_model(self):
        agent = ImageReviewAgent(False, "", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3-vl-plus")
        with patch("app.modules.china_sourcing.image_review.urlopen") as open_url:
            result = agent.review("title", "source", [])
        self.assertEqual(result["status"], "disabled")
        open_url.assert_not_called()

    def test_not_configured_agent_never_calls_model(self):
        agent = ImageReviewAgent(True, "", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3-vl-plus")
        with patch("app.modules.china_sourcing.image_review.urlopen") as open_url:
            result = agent.review("title", "source", [ImageCandidate("img", "img.jpg")])
        self.assertEqual(result["status"], "not_configured")
        open_url.assert_not_called()

    def test_parser_sanitizes_fields_and_fills_missing_candidates(self):
        result = parse_review_json('''```json
        {"reviews":[{"image_id":"a","product_match":"wrong","image_kind":"real_photo",
        "real_photo_likelihood":"likely","relevance_score":140,"quality_score":-2,
        "duplicate_of":"a","confidence":3,"decision":"exclude","reason":" noisy  image "}]}
        ```''', ["a", "b"])
        self.assertEqual(result[0]["product_match"], "uncertain")
        self.assertEqual(result[0]["relevance_score"], 100)
        self.assertEqual(result[0]["quality_score"], 0)
        self.assertIsNone(result[0]["duplicate_of"])
        self.assertEqual(result[0]["confidence"], 1.0)
        self.assertEqual(result[0]["decision"], "exclude")
        self.assertEqual(result[1]["decision"], "keep")
        self.assertEqual(result[1]["image_id"], "b")

    def test_qwen_request_sends_compressed_candidate_and_valid_reference(self):
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "candidate.png"
            Image.new("RGB", (1200, 800), (50, 100, 150)).save(image_path)
            output = {"choices": [{"message": {"content": json.dumps({"reviews": [{
                "image_id": "img-1", "product_match": "same_product", "image_kind": "catalog",
                "real_photo_likelihood": "unlikely", "relevance_score": 90, "quality_score": 80,
                "duplicate_of": None, "confidence": 0.9, "suggested_action": "keep", "reason": "商品一致",
            }]}, ensure_ascii=False)}}]}
            request_capture = {}

            def fake_urlopen(request, timeout):
                request_capture["request"] = request
                request_capture["timeout"] = timeout
                return BytesIO(json.dumps(output, ensure_ascii=False).encode("utf-8"))

            candidate = ImageCandidate("img-1", "source/img-1.jpg", "other", "闲鱼详情图", 1200, 800)
            client = QwenVisionClient("test-key", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3-vl-plus")
            with patch("app.modules.china_sourcing.image_review.resolve_image_path", return_value=image_path), \
                    patch("app.modules.china_sourcing.image_review.urlopen", side_effect=fake_urlopen), \
                    patch("app.modules.china_sourcing.image_review._reference_image_data_uri",
                          return_value="data:image/jpeg;base64,reference"):
                reviews = client.review("日文标题", "货源标题", [candidate], "mercari",
                                         "https://static.mercdn.net/item/detail/orig/photos/item.jpg")

            request = request_capture["request"]
            body = json.loads(request.data.decode("utf-8"))
            content = body["messages"][0]["content"]
            self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
            self.assertEqual(body["model"], "qwen3-vl-plus")
            self.assertEqual(request_capture["timeout"], 45)
            image_urls = [part.get("image_url", {}).get("url", "") for part in content]
            self.assertEqual(sum(url.startswith("data:image/jpeg;base64,") for url in image_urls), 2)
            self.assertFalse(any(url.startswith("https://") for url in image_urls))
            self.assertTrue(client.reference_image_included)
            self.assertEqual(reviews[0]["image_id"], "img-1")
            self.assertEqual(reviews[0]["product_match"], "same_product")

    def test_reference_image_is_downloaded_through_configured_proxy(self):
        with BytesIO() as buffer:
            Image.new("RGB", (80, 50), (180, 80, 20)).save(buffer, format="JPEG")
            image_payload = buffer.getvalue()

        class FakeResponse(BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

            def geturl(self):
                return "https://static.mercdn.net/reference.jpg"

        captured = {}

        class FakeOpener:
            def open(self, request, timeout):
                captured["request"] = request
                captured["timeout"] = timeout
                return FakeResponse(image_payload)

        with patch("app.modules.china_sourcing.image_review.build_opener", return_value=FakeOpener()) as build:
            data_uri = _reference_image_data_uri(
                "https://static.mercdn.net/reference.jpg", "mercari", "http://127.0.0.1:10090", 120
            )

        self.assertTrue(data_uri.startswith("data:image/jpeg;base64,"))
        self.assertEqual(captured["request"].full_url, "https://static.mercdn.net/reference.jpg")
        self.assertEqual(captured["timeout"], 30)
        self.assertEqual(build.call_args.args[0].proxies["https"], "http://127.0.0.1:10090")

    def test_reference_image_rejects_non_allowlisted_hosts_without_network_access(self):
        with patch("app.modules.china_sourcing.image_review.build_opener") as build:
            result = _reference_image_data_uri(
                "https://attacker.example/image.jpg", "mercari", "http://127.0.0.1:10090", 45
            )
        self.assertIsNone(result)
        build.assert_not_called()

    def test_qwen_request_uses_configured_http_proxy(self):
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "candidate.png"
            Image.new("RGB", (64, 64), "white").save(image_path)
            output = {"choices": [{"message": {"content": '{"reviews":[{"image_id":"img-1"}]}'}}]}
            opener = type("FakeOpener", (), {"open": lambda self, request, timeout: BytesIO(
                json.dumps(output).encode("utf-8"))})()
            candidate = ImageCandidate("img-1", "source/img-1.jpg")
            client = QwenVisionClient(
                "test-key", "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "qwen3.7-plus", proxy="http://127.0.0.1:10090")
            with patch("app.modules.china_sourcing.image_review.resolve_image_path", return_value=image_path), \
                    patch("app.modules.china_sourcing.image_review.build_opener", return_value=opener) as build:
                reviews = client.review("title", "source", [candidate])
            proxy_handler = build.call_args.args[0]
            self.assertEqual(proxy_handler.proxies, {
                "http": "http://127.0.0.1:10090", "https": "http://127.0.0.1:10090"})
            self.assertEqual(reviews[0]["image_id"], "img-1")

    def test_qwen_http_errors_include_safe_detail_without_api_key(self):
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "candidate.png"
            Image.new("RGB", (32, 32), "white").save(image_path)
            client = QwenVisionClient("secret-key", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.7-plus")
            error_body = BytesIO(b'{"error":{"message":"invalid request secret-key"}}')
            api_error = HTTPError("https://dashscope.aliyuncs.com", 400, "Bad Request", {}, error_body)
            with patch("app.modules.china_sourcing.image_review.resolve_image_path", return_value=image_path), \
                    patch("app.modules.china_sourcing.image_review.urlopen", side_effect=api_error):
                with self.assertRaisesRegex(RuntimeError, "invalid request \\[redacted\\]") as raised:
                    client.review("title", "source", [ImageCandidate("img-1", "image.jpg")])
            self.assertNotIn("secret-key", str(raised.exception))

    def test_qwen_network_errors_include_safe_detail_without_api_key(self):
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "candidate.png"
            Image.new("RGB", (32, 32), "white").save(image_path)
            client = QwenVisionClient("secret-key", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.7-plus")
            with patch("app.modules.china_sourcing.image_review.resolve_image_path", return_value=image_path), \
                    patch("app.modules.china_sourcing.image_review.urlopen", side_effect=URLError("secret-key unreachable")):
                with self.assertRaisesRegex(RuntimeError, r"\[redacted\] unreachable") as raised:
                    client.review("title", "source", [ImageCandidate("img-1", "image.jpg")])
            self.assertIn("[redacted]", str(raised.exception))
            self.assertNotIn("secret-key", str(raised.exception))

    def test_reference_url_allowlist_fails_closed(self):
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "candidate.jpg"
            Image.new("RGB", (20, 20), "white").save(image_path)
            output = {"choices": [{"message": {"content": '{"reviews":[{"image_id":"img-1"}]}'}}]}
            request_capture = {}

            def fake_urlopen(request, timeout):
                request_capture["body"] = json.loads(request.data.decode("utf-8"))
                return BytesIO(json.dumps(output).encode("utf-8"))

            client = QwenVisionClient("test-key", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3-vl-plus")
            with patch("app.modules.china_sourcing.image_review.resolve_image_path", return_value=image_path), \
                    patch("app.modules.china_sourcing.image_review.urlopen", side_effect=fake_urlopen):
                client.review("title", "source", [ImageCandidate("img-1", "image.jpg")], "mercari",
                              "https://attacker.example/image.jpg")
            self.assertFalse(any(part.get("image_url", {}).get("url") == "https://attacker.example/image.jpg"
                                 for part in request_capture["body"]["messages"][0]["content"]))

    def test_model_decisions_update_image_role_and_exclusion_automatically(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE items(id TEXT PRIMARY KEY,japan_title TEXT,japan_site TEXT,japan_image_url TEXT);
            CREATE TABLE china_sources(id TEXT PRIMARY KEY,item_id TEXT,source_title TEXT);
            CREATE TABLE source_images(id TEXT PRIMARY KEY,listing_path TEXT,image_role TEXT,collection_note TEXT,
                width INTEGER,height INTEGER,source_id TEXT,excluded_at TEXT,exclusion_reason TEXT,
                vision_review_json TEXT,
                vision_review_at TEXT,vision_review_model TEXT,created_at TEXT);
            CREATE TABLE audit_events(id TEXT PRIMARY KEY,entity_type TEXT,entity_id TEXT,action TEXT,details TEXT,created_at TEXT);
            INSERT INTO items VALUES('item','日本商品','mercari','https://static.mercdn.net/image.jpg');
            INSERT INTO china_sources VALUES('source','item','中国货源');
            INSERT INTO source_images VALUES('img','image.jpg','other','采集候选',400,300,'source',NULL,'','{}',NULL,'','2026-01-01');
            INSERT INTO source_images VALUES('img-photo','photo.jpg','other','实物图片候选',400,300,'source',NULL,'','{}',NULL,'','2026-01-02');
        """)

        class FakeAgent:
            def review(self, item_title, source_title, candidates, japan_site, reference_image_url):
                return {"status": "succeeded", "model": "qwen-test", "reviews": [
                    {"image_id": "img", "decision": "exclude", "image_kind": "recommendation",
                     "reason": "与目标无关", "real_photo_likelihood": "unlikely", "product_match": "unrelated",
                     "relevance_score": 2, "quality_score": 70, "duplicate_of": None, "confidence": 0.88},
                    {"image_id": "img-photo", "decision": "keep", "image_kind": "real_photo",
                     "reason": "拍摄实物", "real_photo_likelihood": "likely", "product_match": "same_product",
                     "relevance_score": 92, "quality_score": 80, "duplicate_of": None, "confidence": 0.91},
                ]}

        result = review_source_images(connection, "source", "item", FakeAgent())
        saved = connection.execute("SELECT * FROM source_images WHERE id='img'").fetchone()
        saved_photo = connection.execute("SELECT * FROM source_images WHERE id='img-photo'").fetchone()
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(json.loads(saved["vision_review_json"])["decision"], "exclude")
        self.assertIsNotNone(saved["excluded_at"])
        self.assertIn("千问自动排除", saved["exclusion_reason"])
        self.assertEqual(saved["image_role"], "other")
        self.assertEqual(saved["vision_review_model"], "qwen-test")
        self.assertEqual(saved_photo["image_role"], "real_photo")
        self.assertIsNone(saved_photo["excluded_at"])
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 2)
        connection.close()


if __name__ == "__main__":
    unittest.main()
