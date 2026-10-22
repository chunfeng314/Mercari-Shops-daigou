JAPAN_SITES = [
    {"id": "mercari", "name": "Mercari", "url": "https://jp.mercari.com/", "phase": "首批", "kind": "个人二手平台"},
    {"id": "yahoo_auctions", "name": "Yahoo!オークション", "url": "https://auctions.yahoo.co.jp/", "phase": "首批", "kind": "拍卖与二手交易"},
    {"id": "rakuma", "name": "ラクマ（Rakuma）", "url": "https://fril.jp/", "phase": "首批", "kind": "个人二手平台"},
    {"id": "yahoo_flea", "name": "Yahoo!フリマ", "url": "https://paypayfleamarket.yahoo.co.jp/", "phase": "扩展", "kind": "个人二手平台"},
    {"id": "second_street", "name": "2nd STREET", "url": "https://www.2ndstreet.jp/", "phase": "扩展", "kind": "综合二手零售"},
]

CHINA_SITES = [
    {"id": "xianyu", "name": "闲鱼", "mode": "本机 Chrome/Edge 搜索；人工核验"},
    {"id": "xiaohongshu", "name": "小红书", "mode": "代购账号/人工核验"},
    {"id": "dewu", "name": "得物", "mode": "代购账号/人工核验"},
]

JAPAN_SITE_IDS = {site["id"] for site in JAPAN_SITES}
CHINA_SITE_IDS = {site["id"] for site in CHINA_SITES}
