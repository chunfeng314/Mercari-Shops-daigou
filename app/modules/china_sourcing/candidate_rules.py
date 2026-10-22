"""Screen public source descriptions against attributes of the Japanese item.

These rules can reject conflicting attributes; matching text is never treated
as proof of authenticity, stock, condition, or an exact visual match.
"""
import re
import unicodedata


BRANDS = (
    (r"STARBUCKS|スターバックス|星巴克", r"STARBUCKS|スターバックス|星巴克", "星巴克"),
    (r"サンリオ|Sanrio|三丽鸥", r"サンリオ|Sanrio|三丽鸥", "三丽鸥"),
    (r"ポケモン|ポケットモンスター|Pok[eé]mon|宝可梦", r"ポケモン|Pok[eé]mon|宝可梦|口袋妖怪", "宝可梦"),
)


def _capacities(text: str) -> set[int]:
    text = unicodedata.normalize("NFKC", text)
    return {int(value) for value in re.findall(r"(?<![\d\-~〜])(\d{2,4})\s*(?:ml|ミリリットル)(?![A-Za-z0-9])", text, re.I)}


def assess_source(japan_title: str, source_title: str) -> dict:
    title = unicodedata.normalize("NFKC", japan_title)
    candidate = unicodedata.normalize("NFKC", source_title)
    rejected, review, evidence = [], [], []
    for target_pattern, source_pattern, label in BRANDS:
        if re.search(target_pattern, title, re.I):
            if re.search(source_pattern, candidate, re.I):
                evidence.append(f"品牌词匹配：{label}")
            else:
                rejected.append(f"候选描述未匹配日本商品的品牌词：{label}")
    target_capacity, source_capacity = _capacities(title), _capacities(candidate)
    if target_capacity:
        if source_capacity and target_capacity.isdisjoint(source_capacity):
            rejected.append(f"容量冲突：日本 {sorted(target_capacity)}ml，中国候选 {sorted(source_capacity)}ml")
        elif source_capacity:
            evidence.append("容量词匹配：" + "/".join(str(x) for x in sorted(target_capacity & source_capacity)) + "ml")
        else:
            review.append("中国候选未明确标出目标容量")
    if re.search(r"猫チャーム.*付|猫挂件|猫吊饰", title, re.I):
        if re.search(r"(?:不含|不带|没有|不包含|无)\s*(?:猫)?(?:挂件|吊饰|吊坠)", candidate):
            rejected.append("日本商品包含猫挂件，候选明确不含挂件")
        elif re.search(r"挂件|吊饰|吊坠|チャーム", candidate):
            evidence.append("描述包含挂件")
        else:
            review.append("挂件是否包含尚未核实")
    quoted_prices = re.findall(r"\b\d+(?:\.\d+)?\s*[rR](?=\s|$|[，,。])", candidate)
    if len(quoted_prices) > 1 or re.search(r"图\s*\d.*图\s*\d", candidate):
        review.append("同页展示多个商品，标价可能是起价，需核对目标款价格")
    status = "excluded" if rejected else "needs_review" if review or not evidence else "attribute_match"
    return {"status": status, "evidence": evidence, "reasons": rejected + review,
            "note": "文字属性匹配仍需核实同款图片、成色、库存与供货情况。"}


def screen_sources(japan_title: str, items: list[dict]) -> tuple[list[dict], list[dict]]:
    kept, excluded = [], []
    for item in items:
        candidate = {**item, "assessment": assess_source(japan_title, item.get("title", ""))}
        (excluded if candidate["assessment"]["status"] == "excluded" else kept).append(candidate)
    kept.sort(key=lambda item: item["assessment"]["status"] != "attribute_match")
    return kept, excluded
