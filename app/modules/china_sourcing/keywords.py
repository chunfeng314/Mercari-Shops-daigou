"""Deterministic search-term planning from Japanese-market item data (no AI)."""
import re
import unicodedata


TRANSLATIONS = {
    "STARBUCKS": "星巴克 Starbucks", "スターバックス": "星巴克", "KABAO": "卡宝 KABAO",
    "ハロウィン": "万圣节", "黒猫": "黑猫", "ステンレスストロータンブラー": "不锈钢吸管杯",
    "ステンレス": "不锈钢", "ストロー": "吸管", "猫チャーム": "猫挂件", "オレンジ": "橙色",
    "デミタスカップ": "浓缩咖啡杯", "Korea": "韩国", "Taiwan": "台湾",
    "ポケットモンスター": "宝可梦", "ポケモン": "宝可梦",
    "サンリオ": "三丽鸥", "ハンギョドン": "汉顿 Hangyodon",
    "クロミ": "酷洛米", "マイメロディ": "美乐蒂", "マイメロ": "美乐蒂",
    "ポムポムプリン": "布丁狗", "タキシードサム": "Tuxedosam",
    "ポチャッコ": "帕恰狗", "シナモロール": "玉桂狗",
    "ハローキティ": "Hello Kitty 凯蒂猫 ", "キティ": "凯蒂猫",
    "フェイス型": "脸型造型", "デジタルカメラ": "数码相机", "デジカメ": "数码相机",
    "カメラ": "相机", "限定品": "限量款",
    "星のカービィ": "星之卡比", "ちいかわ": "吉伊卡哇",
    "初音ミク": "初音未来", "遊戯王": "游戏王", "ワンピース": "海贼王",
    "ドラゴンボール": "龙珠", "クリアカード": "透明卡", "コレクションカード": "收藏卡",
    "トレーディングカード": "卡牌", "トレカ": "卡牌", "カード": "卡牌",
    "ぬいぐるみ": "毛绒玩偶", "マスコット": "挂件", "アクリルスタンド": "亚克力立牌",
    "アクスタ": "亚克力立牌", "キーホルダー": "钥匙扣", "缶バッジ": "徽章",
    "タンブラー": "随行杯", "マグカップ": "马克杯", "ボトル": "水杯",
    "ステッカー": "贴纸", "シール": "贴纸", "限定": "限定", "中国限定": "中国限定",
    "ブルーアーカイブ": "蔚蓝档案 Blue Archive", "ブルアカ": "蔚蓝档案",
    "アークナイツ": "明日方舟 Arknights", "アクナイ": "明日方舟",
    "ヒナ": "空崎日奈 日奈", "ユウカ": "早濑优香 优香", "カズサ": "杏山和纱 和纱",
    "ミカ": "圣园未花 未花", "セイア": "百合园圣娅 圣娅",
    "アリス": "天童爱丽丝 爱丽丝", "ケルシー": "凯尔希",
    "啾啾指揮家": "啾啾指挥家", "指揮家": "指挥家",
    "天童アリス": "天童爱丽丝", "盛夏派対シリーズ": "盛夏派对系列", "盛夏派対": "盛夏派对",
    "GoodSmile Moment": "良笑塑美", "假日漫步": "假日漫步", "グッズセット": "周边套装",
    "パペットぬいぐるみ": "手偶毛绒玩偶", "特大ぬいぐるみ": "大号毛绒玩偶",
    "ぬいぐるみ": "毛绒玩偶", "特大": "大号", "周年記念": "周年纪念",
    # Include a full Chinese garment term because the tokenizer intentionally
    # drops one-character Latin/CJK fragments such as the ``T`` in ``T恤``.
    "Tシャツ": "短袖T恤", "tシャツ": "短袖T恤", "XLサイズ": "XL码", "サイズ": "尺码",
    "パーカー": "连帽衫", "シャツ": "衬衫",
    "セット": "套装", "未開封": "未拆封", "未使用": "未使用",
}
NOISE = {
    "新品", "未使用", "未開封", "美品", "即購入", "送料無料", "送料込み",
    "匿名配送", "まとめ売り", "プロフ必読", "即日発送", "即発送", "購入前コメント不要",
    "Mercari", "ページ", "商品", "説明", "写真", "画像", "出品", "即購入可",
    "ブランド", "モデル", "状態", "カラー", "付属品", "基本", "動作", "撮影", "確認済み",
}
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-/]*|[\u3040-\u30ff\u3400-\u9fff]+")


def _mapped(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "")
    for source in sorted(TRANSLATIONS, key=len, reverse=True):
        if source.isascii() and source.isalpha():
            value = re.sub(re.escape(source), TRANSLATIONS[source], value, flags=re.IGNORECASE)
        else:
            value = value.replace(source, TRANSLATIONS[source])
    value = re.sub(r"第\s*(\d+)\s*弾", lambda m: f"第{m.group(1)}弹", value)
    value = value.replace("付き", " ")
    value = re.sub(r"[#＃【】\[\]()（）「」『』,，。・:：;；|｜]+", " ", value)
    value = re.sub(r"https?://\S+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(text: str) -> list[str]:
    result, seen = [], set()
    for token in TOKEN_RE.findall(_mapped(text)):
        token = token.strip("-_./")
        # Xianyu is a Chinese marketplace; untranslated kana causes noisy or
        # empty searches, so keep only terms the local dictionary translated.
        if len(token) < 2 or re.search(r"[\u3040-\u30ff]", token) or token in NOISE or token.casefold() in seen:
            continue
        seen.add(token.casefold())
        result.append(token)
    return result


def plan_search_queries(japan_title: str, japan_note: str = "", maximum: int = 4) -> list[str]:
    """Build several focused Chinese/brand/model queries using only collected listing text."""
    title = _tokens(japan_title)
    note = re.sub(r"(?im)^Mercari\s*(?:ページ|页面)\s*采集\s*[:：].*(?:\r?\n|$)", "", japan_note or "")
    details = _tokens(note[:8000])
    if not title:
        title = details[:8]
    if not title:
        return []

    title = list(dict.fromkeys(title))
    title_keys = {term.casefold() for term in title}
    detail_unique = [term for term in details if term.casefold() not in title_keys]
    focused = title[:6]
    if detail_unique:
        focused = (focused + detail_unique[:4])[:10]
    candidates = [" ".join(title[:9]), " ".join(focused)]
    # A broader product-family query retains model/capacity from the Japanese
    # item, while dropping optional colour/accessory words and a duplicated
    # Latin brand alias. Seller wording often omits those optional qualifiers.
    broad = [term for term in title if term not in {"黑猫", "橙色", "猫挂件"}
             and not (term.casefold() == "starbucks" and "星巴克" in title)]
    broad = [term.replace("不锈钢吸管杯", "吸管杯") for term in broad]
    candidates.append(" ".join(broad[:9]))
    # Clothing size and limited-edition qualifiers can overconstrain supply
    # searches. Keep the exact query above, then add a clean product-family query.
    apparel_broad = [term for term in broad if term not in {"XL码", "尺码", "中国限定", "限定"}]
    if apparel_broad != broad and apparel_broad:
        candidates.append(" ".join(apparel_broad[:9]))
    apparel_terms = {"短袖", "T恤", "连帽衫", "衬衫", "卫衣", "长袖"}
    if apparel_terms.intersection(title):
        generic = apparel_terms | {"XL", "XS", "S", "M", "L", "XXL", "尺码", "中国限定", "限定",
                                   "新品", "未拆封", "未使用", "系列商品"}
        identities = [term for term in title + details
                      if term not in generic and term not in {"Blue", "Archive"}]
        # Search the character/work identity first. Long marketplace queries
        # behave like loose OR searches, which can flood sourcing with unrelated
        # inventory when size and release qualifiers are included.
        identity_queries = []
        character = next((term for term in identities if term not in {"蔚蓝档案", "Blue Archive"}), None)
        franchise = next((term for term in identities if term == "蔚蓝档案"), None)
        series = next((term for term in identities if term not in {character, franchise}), None)
        if character and franchise:
            identity_queries.append(f"{character} {franchise} 短袖")
        if character and series:
            identity_queries.append(f"{character} {series} 短袖")
        if identity_queries:
            candidates = identity_queries + candidates
    # Japanese listings often put the series name before the character. Avoid
    # treating that series name (or the product line) as the character in
    # focused searches. Short queries also perform better on Xianyu's loose
    # multi-term matching than one long title-like string.
    known_characters = {
        "空崎日奈", "日奈", "早濑优香", "优香", "杏山和纱", "和纱",
        "圣园未花", "未花", "百合园圣娅", "圣娅", "爱丽丝", "天童爱丽丝", "凯尔希",
    }
    character = next((term for term in title if term in known_characters), None)
    short_character = {
        "空崎日奈": "日奈", "早濑优香": "优香", "杏山和纱": "和纱",
        "圣园未花": "未花", "百合园圣娅": "圣娅", "天童爱丽丝": "爱丽丝",
    }.get(character, character)
    product_line = next((term for term in title if term in {"假日漫步", "盛夏派对系列", "盛夏派对"}), "")
    if "蔚蓝档案" in title and character:
        if any(term in title for term in ("短袖T恤", "衬衫", "短袖")):
            candidates = [
                f"蔚蓝档案 {character} {product_line} 短袖".strip(),
                f"{short_character} {product_line} 短袖".strip(),
                f"蔚蓝档案 {character} 中国限定 T恤",
            ] + candidates
        elif "周边套装" in title:
            code = next((term for term in details if re.fullmatch(r"26\d{8}", term)), "")
            candidates = [
                f"蔚蓝档案 {character} {product_line} 周边".strip(),
                f"{short_character} {product_line} 周边".strip(),
                f"{character} {product_line} {code}".strip(),
            ] + candidates
        elif "手偶毛绒玩偶" in title:
            line = next((term for term in title if term in {"群星", "啾啾指挥家"}), "")
            candidates = [
                f"蔚蓝档案 {character} {line} 手偶".strip(),
                f"{short_character} {line} 毛绒玩偶".strip(),
                f"蔚蓝档案 {character} 手偶 毛绒玩偶",
            ] + candidates
    if "明日方舟" in title and "凯尔希" in title:
        candidates = [
            "明日方舟 猫山山 凯尔希 7周年 毛绒",
            "猫山山 凯尔希 大号毛绒玩偶",
            "明日方舟 凯尔希 65cm 玩偶",
        ] + candidates
    if any(re.fullmatch(r"\d+(?:\.\d+)?ml", term, re.I) for term in broad):
        model_focused = [term for term in broad if term != "万圣节" and not re.fullmatch(r"20\d{2}", term)]
        candidates.append(" ".join(model_focused[:9]))
    queries, seen = [], set()
    for query in candidates:
        query = query[:72].strip()
        key = query.casefold()
        if query and key not in seen:
            queries.append(query)
            seen.add(key)
        if len(queries) >= maximum:
            break
    return queries
