"""Collect public Mercari DOM and JSON-LD. No private API or saved login state."""
import json
import re
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout


class CollectionError(ValueError):
    pass


# The business rule is a strict floor: 9,999 JPY is excluded, 10,000 JPY is included.
MINIMUM_PRICE_JPY = 10_000


def has_eligible_jpy_price(price) -> bool:
    if isinstance(price, bool):
        return False
    try:
        amount = float(str(price).replace(",", ""))
    except (TypeError, ValueError, OverflowError):
        return False
    return amount == amount and amount != float("inf") and amount != float("-inf") and amount > MINIMUM_PRICE_JPY - 1


def filter_minimum_price(items: list[dict]) -> tuple[list[dict], dict]:
    eligible = [item for item in items if has_eligible_jpy_price(item.get("price"))]
    unknown = sum(1 for item in items if _numeric_jpy_price(item.get("price")) is None)
    below = len(items) - len(eligible) - unknown
    return eligible, {
        "scanned_count": len(items),
        "excluded_below_price_count": below,
        "excluded_unknown_price_count": unknown,
        "minimum_price_jpy": MINIMUM_PRICE_JPY,
        "price_rule": "price > 9999 JPY",
    }


def _numeric_jpy_price(price):
    if isinstance(price, bool):
        return None
    try:
        amount = float(str(price).replace(",", ""))
    except (TypeError, ValueError, OverflowError):
        return None
    if amount != amount or amount == float("inf") or amount == float("-inf"):
        return None
    return amount


def validate_mercari_url(url: str, kind: str = "any") -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise CollectionError("请使用 Mercari 的完整 https 链接")
    allowed = parsed.hostname in ("jp.mercari.com", "mercari-shops.com")
    if not allowed:
        raise CollectionError("仅接受 jp.mercari.com 或 mercari-shops.com 的链接")
    path = parsed.path.rstrip("/")
    if kind == "item" and not re.fullmatch(r"/(?:item|shops/product|products)/[A-Za-z0-9_-]+", path):
        raise CollectionError("请填写具体商品链接")
    if kind == "shop" and not re.fullmatch(r"/(?:user/profile|shops)/[A-Za-z0-9_-]+", path):
        raise CollectionError("请填写 Mercari 卖家主页或 Shops 店铺主页链接")
    return urlunparse(("https", parsed.hostname, path or "/", "", parsed.query, ""))


def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname == "jp.mercari.com" and parsed.path.startswith("/shops/product/"):
        return "https://mercari-shops.com/products/" + parsed.path.rstrip("/").split("/")[-1]
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def search_url(query: str, available_only: bool = True, sort: str = "newest") -> str:
    params = {"keyword": query}
    if available_only:
        params["status"] = "on_sale"
    sorting = {"newest": ("created_time", "desc"), "price_low": ("price", "asc"), "price_high": ("price", "desc")}
    if sort in sorting:
        params.update(sort=sorting[sort][0], order=sorting[sort][1])
    return "https://jp.mercari.com/search?" + urlencode(params)


CARD_EXTRACTOR = r"""anchors => anchors.map(a => {
  const card = a.closest('li') || a;
  const image = a.querySelector('img');
  const name = a.querySelector('[data-testid="thumbnail-item-name"], [data-testid="item-name"]');
  const price = a.querySelector('[data-testid="item-tile-price"], [data-testid="price"]');
  const text = price?.textContent || a.textContent || '';
  const amount = text.match(/[¥￥]\s*([\d,]+)/);
  return {url:a.href, title:(name?.textContent || image?.alt?.replace(/のサムネイル$/, '') || '').trim(),
    price:amount ? Number(amount[1].replaceAll(',', '')) : null,
    image_url:image?.currentSrc || image?.src || null,
    sold:/SOLD|売り切れ/i.test(card.textContent || '')};
})"""


class MercariCollector:
    site_id = "mercari"

    def __init__(self, page: Page, checkpoint=lambda: None, progress=lambda message: None):
        self.page = page
        self.checkpoint = checkpoint
        self.progress = progress
        self.last_price_filter_stats = {
            "scanned_count": 0,
            "excluded_below_price_count": 0,
            "excluded_unknown_price_count": 0,
            "minimum_price_jpy": MINIMUM_PRICE_JPY,
            "price_rule": "price > 9999 JPY",
        }

    def open(self, url: str):
        self.checkpoint()
        response = self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        self.checkpoint()
        if response and response.status >= 400:
            raise CollectionError(f"Mercari 页面返回 HTTP {response.status}，请稍后重试")
        if urlparse(self.page.url).hostname not in ("jp.mercari.com", "mercari-shops.com"):
            raise CollectionError("页面跳转到了其他地区或登录服务，请人工检查浏览器")

    def collect_cards(self, limit: int) -> list[dict]:
        selector = 'a[href*="/item/"],a[href*="/shops/product/"],a[href*="mercari-shops.com/products/"],a[href^="/products/"]'
        try:
            self.page.locator(selector).first.wait_for(state="attached", timeout=25000)
        except PlaywrightTimeout:
            body = self.page.locator("body").inner_text(timeout=5000)
            if any(text in body for text in ("該当する商品が見つかりません", "検索結果がありません", "出品された商品がありません")):
                return []
            raise CollectionError("未找到可读取的商品卡片。页面可能需要登录、验证或已改版，请人工检查。")
        try:
            self.page.wait_for_function("() => [...document.querySelectorAll('a[data-testid=\"thumbnail-link\"]')].some(a => a.querySelector('img')?.getAttribute('src'))", timeout=3500)
        except PlaywrightTimeout:
            # A missing image does not invalidate a readable title and price.
            pass
        scanned = {}
        found = {}
        stagnant = 0
        for _ in range(30):
            self.checkpoint()
            before = len(scanned)
            for card in self.page.locator(selector).evaluate_all(CARD_EXTRACTOR):
                try:
                    validate_mercari_url(card["url"], "item")
                except ValueError:
                    continue
                if not card["title"]:
                    continue
                url = canonical_url(card["url"])
                if url in scanned:
                    continue
                result = {"site_id": self.site_id, **card, "url": url, "currency": "JPY"}
                scanned[url] = result
                if has_eligible_jpy_price(result.get("price")):
                    found[url] = result
                if len(found) >= limit:
                    _, self.last_price_filter_stats = filter_minimum_price(list(scanned.values()))
                    return list(found.values())[:limit]
            stagnant = stagnant + 1 if len(scanned) == before else 0
            if stagnant >= 2:
                break
            self.progress(f"已读取 {len(scanned)} 件，符合价格条件 {len(found)} 件，正在加载更多")
            # Lazy-loaded cards render as the viewport approaches them.
            self.page.mouse.wheel(0, 700)
            self.page.wait_for_timeout(650)
        _, self.last_price_filter_stats = filter_minimum_price(list(scanned.values()))
        return list(found.values())[:limit]

    def search(self, query: str, limit: int = 20, available_only=True, sort="newest") -> list[dict]:
        self.open(search_url(query, available_only, sort))
        return self.collect_cards(limit)

    def shop(self, url: str, limit: int = 20) -> list[dict]:
        self.open(validate_mercari_url(url, "shop"))
        return self.collect_cards(limit)

    def item(self, url: str) -> list[dict]:
        self.open(validate_mercari_url(url, "item"))
        try:
            self.page.wait_for_function("() => document.querySelector('script[type=\"application/ld+json\"]') || document.querySelector('h1')", timeout=25000)
        except PlaywrightTimeout as error:
            raise CollectionError("商品详情尚未加载完成，请稍后重试") from error
        try:
            # The server-rendered product JSON can arrive before the seller
            # profile link is hydrated into the interactive page.
            self.page.wait_for_function(
                "() => document.querySelector('a[href*=\"/user/profile/\"], a[href*=\"/shops/\"]')",
                timeout=6000,
            )
        except PlaywrightTimeout:
            pass
        documents = self.page.locator('script[type="application/ld+json"]').all_text_contents()
        nodes = []

        def visit(value):
            if isinstance(value, list):
                for entry in value:
                    visit(entry)
            elif isinstance(value, dict):
                nodes.append(value)
                if "@graph" in value:
                    visit(value["@graph"])

        for document in documents:
            try:
                visit(json.loads(document))
            except (ValueError, TypeError):
                continue
        product = next((node for node in nodes if node.get("@type") == "Product" or "Product" in node.get("@type", [])), None)
        if not product or not product.get("name"):
            raise CollectionError("详情页未提供可验证的商品资料，请人工录入")
        seller = {"seller_url": None, "seller_id": None, "seller_name": None}
        try:
            links = self.page.locator('a[href*="/user/profile/"], a[href*="/shops/"]').evaluate_all(
                "anchors => anchors.map(a => ({url:a.href || a.getAttribute('href'), name:(a.innerText || '').trim()}))"
            )
        except Exception:
            links = []
        for link in links:
            try:
                profile_url = validate_mercari_url(urljoin(self.page.url, link.get("url", "")), "shop")
            except (CollectionError, AttributeError):
                continue
            profile_path = urlparse(profile_url).path
            match = re.fullmatch(r"/(?:user/profile|shops)/([A-Za-z0-9_-]+)", profile_path)
            if match:
                seller = {"seller_url": profile_url, "seller_id": match.group(1),
                          "seller_name": (link.get("name") or "").strip() or None}
                break
        offer = product.get("offers", {})
        if isinstance(offer, list):
            offer = offer[0] if offer else {}
        images = product.get("image", [])
        if isinstance(images, str):
            images = [images]
        try:
            price = float(str(offer.get("price", "")).replace(",", ""))
            price = int(price) if price > 0 else None
        except (ValueError, TypeError, OverflowError):
            price = None
        return [{"site_id": self.site_id, "url": canonical_url(self.page.url), "title": product["name"], **seller,
                 "price": price, "currency": offer.get("priceCurrency", "JPY"),
                 "image_url": images[0] if images else None, "images": images,
                 "description": product.get("description", ""),
                 "availability": offer.get("availability"),
                 "sold": "OutOfStock" in str(offer.get("availability", "")) or "SoldOut" in str(offer.get("availability", ""))}]
