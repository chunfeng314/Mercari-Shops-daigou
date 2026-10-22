import unittest

from app.modules.china_sourcing.candidate_rules import assess_source, screen_sources


class CandidateRulesTests(unittest.TestCase):
    title = "STARBUCKS 黒猫 ステンレスストロータンブラー 430ml 猫チャーム付き"

    def test_separates_attribute_matches_from_conflicts_and_multi_item_prices(self):
        kept, excluded = screen_sources(self.title, [
            {"title":"星巴克 黑色吸管杯 430ml 带猫挂件", "price":189.99},
            {"title":"星巴克 澳门保温杯473ml 带挂件", "price":290},
            {"title":"星巴克 吸管杯430ml 不含挂件", "price":131},
            {"title":"NONOO 吸管杯 430ml", "price":19.99},
            {"title":"星巴克 图1杯子180r 图2挂件95r", "price":55},
        ])
        self.assertEqual(len(kept), 2)
        self.assertEqual(len(excluded), 3)
        self.assertEqual(kept[0]["assessment"]["status"], "attribute_match")
        self.assertEqual(kept[1]["assessment"]["status"], "needs_review")
        self.assertTrue(any("起价" in reason for reason in kept[1]["assessment"]["reasons"]))
        self.assertTrue(any("不含挂件" in reason for item in excluded for reason in item["assessment"]["reasons"]))

    def test_platform_capacity_range_does_not_conflict_with_exact_capacity(self):
        result = assess_source(self.title, "星巴克 430ml 250-499mL 带猫挂件")
        self.assertEqual(result["status"], "attribute_match")
        self.assertEqual(assess_source("ポケモンカード SR", "宝可梦卡牌 SR")["status"], "attribute_match")
