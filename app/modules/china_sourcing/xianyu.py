"""Read public Xianyu search results from a user-owned local browser tab."""
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from playwright.sync_api import TimeoutError as PlaywrightTimeout


class XianyuCollectionError(ValueError):
    pass


def parse_display_price(text: str) -> float | None:
    """Xianyu renders the fractional part in a separate DOM span."""
    match = re.search(r"(?:¥|￥|\bCNY\s*)\s*([\d,]+)(?:\s*\.\s*(\d{1,2})(?!\d))?", text, re.I)
    if match:
        return float(match[1].replace(",", "") + ("." + match[2] if match[2] else ""))
    match = re.search(r"([\d,]+(?:\.\d{1,2})?)\s*元", text)
    return float(match[1].replace(",", "")) if match else None


def search_url(query: str) -> str:
    query = query.strip()
    if not query:
        raise XianyuCollectionError("闲鱼搜索关键词不能为空")
    return "https://www.goofish.com/search?" + urlencode({"q": query})


def validate_item_url(url: str) -> str:
    parsed = urlparse(urljoin("https://www.goofish.com/", url.strip()))
    if (parsed.scheme != "https" or parsed.hostname not in ("www.goofish.com", "goofish.com")
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise XianyuCollectionError("闲鱼商品链接必须来自 goofish.com")
    if not (parsed.path == "/item" or parsed.path.startswith("/item/")):
        raise XianyuCollectionError("仅接受闲鱼商品详情链接")
    params = parse_qs(parsed.query)
    item_id = next((value for value in params.get("id", []) if re.fullmatch(r"[A-Za-z0-9_-]+", value)), None)
    if item_id:
        return "https://www.goofish.com/item?" + urlencode({"id": item_id})
    if re.fullmatch(r"/item/[A-Za-z0-9_-]+", parsed.path):
        return "https://www.goofish.com" + parsed.path
    raise XianyuCollectionError("闲鱼商品链接缺少商品 ID")


CARD_EXTRACTOR = r"""anchors => anchors.map(a => {
  const ancestors = [];
  let node = a;
  for (let i = 0; node && i < 6; i++, node = node.parentElement) ancestors.push(node);
  const card = ancestors.filter(n => (n.innerText || '').length >= 8)
    .sort((x, y) => (x.innerText || '').length - (y.innerText || '').length)
    .find(n => n.querySelector('img')) || ancestors[1] || a;
  const text = (card.innerText || a.innerText || '').replace(/\s+/g, ' ').trim();
  const image = card.querySelector('img') || a.querySelector('img');
  const amount = text.match(/(?:¥|￥|\bCNY\s*)\s*([\d,]+(?:\.\d{1,2})?)|([\d,.]+)\s*元/);
  let title = (a.getAttribute('title') || image?.getAttribute('alt') || a.innerText || '').replace(/\s+/g, ' ').trim();
  title = title.replace(/(?:¥|￥)\s*[\d,.]+|[\d,.]+\s*元/g, '').trim();
  return {url: a.href, title, price: amount ? Number((amount[1] || amount[2]).replaceAll(',', '')) : null,
    image_url: image?.currentSrc || image?.src || null, text};
})"""

DETAIL_IMAGE_EXTRACTOR = r"""() => {
  const images = Array.from(document.images).map(img => {
    const rect = img.getBoundingClientRect();
    if (img.naturalWidth < 80 || img.naturalHeight < 80) return null;
    let node = img, context = '';
    const ancestors = [];
    for (let i = 0; node && i < 8; i++, node = node.parentElement) {
      const marker = [node.id || '', typeof node.className === 'string' ? node.className : '',
        node.getAttribute?.('data-spm') || ''].join(' ');
      if (marker.trim()) ancestors.push(marker.trim());
      const text = (node.innerText || '').replace(/\s+/g, ' ').trim();
      if (text.length > context.length && text.length <= 500) context = text;
    }
    const region = ancestors.join(' > ');
    const excluded = /(?:header|logo|footer|survey|announcement|item-feeds-list-container|recommend(?:ed|ation)?-(?:list|card|container)|similar-(?:items|goods|products)|related-(?:items|goods|products))/i.test(region);
    return {url: img.currentSrc || img.src, alt: img.alt || '', context, region, excluded_region: excluded,
      width: img.naturalWidth, height: img.naturalHeight,
      rendered_width: Math.round(rect.width), rendered_height: Math.round(rect.height)};
  }).filter(Boolean);
  return {title: document.title || '', text: (document.body?.innerText || '').slice(0, 8000),
    images: images.filter(img => img.rendered_width >= 100 && img.rendered_height >= 100 && img.width >= 100 && img.height >= 100),
    image_diagnostics: images.slice(0, 100),
    single_image_gallery: Boolean(document.querySelector('[class*="item-main-window-carousel"][class*="only--"]')),
    gallery_asset_urls: images.filter(img => /item-main-window-(?:list|carousel)/i.test(img.region)).map(img => img.url)};
}"""

IMAGE_HOST_SUFFIXES = ("goofish.com", "alicdn.com", "taobaocdn.com", "tbcdn.cn", "taobao.com")


def validate_image_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if (parsed.scheme != "https" or not host or parsed.username or parsed.password
            or parsed.port not in (None, 443)
            or not any(host == suffix or host.endswith("." + suffix) for suffix in IMAGE_HOST_SUFFIXES)):
        raise XianyuCollectionError("图片地址不属于闲鱼或其常见图片 CDN")
    return urlunparse(("https", parsed.netloc, parsed.path, "", parsed.query, ""))


class XianyuCollector:
    site_id = "xianyu"

    def __init__(self, page, checkpoint=lambda: None, progress=lambda message: None):
        self.page = page
        self.checkpoint = checkpoint
        self.progress = progress

    def search(self, query: str, limit: int = 20) -> list[dict]:
        self.checkpoint()
        url = search_url(query)
        try:
            response = self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as error:
            message = str(error).lower()
            if "err_network_access_denied" in message:
                raise XianyuCollectionError("工作台浏览器受当前进程的网络隔离限制，请从 Windows 正常环境运行 start.ps1 后重试；无需反复授权日常 Chrome") from error
            if any(term in message for term in ("tunnel", "proxy", "net::err", "timed out", "timeout")):
                raise XianyuCollectionError(
                    "本机浏览器访问闲鱼失败。请确认 VPN 当前对所选 Chrome/Edge 生效，再重试；"
                    "若该浏览器可手动打开闲鱼，请检查是否出现网络验证页。"
                ) from error
            raise XianyuCollectionError("闲鱼页面打开失败，请检查本机浏览器网络或稍后重试") from error
        self.checkpoint()
        if response and response.status >= 400:
            raise XianyuCollectionError(f"闲鱼搜索页返回 HTTP {response.status}，请稍后重试")
        if urlparse(self.page.url).hostname not in ("www.goofish.com", "goofish.com"):
            raise XianyuCollectionError("页面跳转到了闲鱼以外的站点，请人工检查浏览器")
        selector = 'a[href*="/item?"][href*="id="],a[href*="/item/"]'
        try:
            self.page.locator(selector).first.wait_for(state="attached", timeout=18000)
        except PlaywrightTimeout:
            body = self.page.locator("body").inner_text(timeout=5000)
            if any(text in body for text in ("没有找到你想要的宝贝", "没有找到相关宝贝", "暂无相关商品")):
                return []
            if any(text in body.lower() for text in ("captcha", "验证", "滑动", "安全校验")):
                raise XianyuCollectionError("闲鱼要求完成安全验证；请在本机浏览器手动完成后重新创建搜索任务")
            raise XianyuCollectionError("未找到闲鱼商品卡片。可能需要登录、验证，或页面结构已变化；请检查采集专用浏览器标签")

        found = {}
        for page_round in range(4):
            self.checkpoint()
            previous_count = len(found)
            for card in self.page.locator(selector).evaluate_all(CARD_EXTRACTOR):
                try:
                    item_url = validate_item_url(card["url"])
                except ValueError:
                    continue
                title = card.get("title", "").strip() or card.get("text", "").strip()
                if not title:
                    continue
                # Goofish can return broad recommendation cards alongside a
                # sparse search result set. For identity-focused queries keep
                # only cards that contain at least one non-generic query term.
                tokens = [term.casefold() for term in query.split()
                          if len(term) > 1 and term.casefold() not in {
                              "xl", "xxl", "xs", "短袖", "t恤", "衬衫", "连帽衫", "卫衣", "长袖",
                              "限定", "中国限定", "新品", "未拆封", "未使用", "尺码",
                          }]
                if tokens and not any(term in title.casefold() for term in tokens):
                    continue
                if any(term in {"短袖", "t恤", "衬衫", "连帽衫", "卫衣", "长袖"} for term in query.casefold().split()):
                    apparel_words = ("短袖", "t恤", "恤", "衣服", "上衣", "服装", "服饰", "衬衫", "卫衣", "连帽衫")
                    if not any(term in title.casefold() for term in apparel_words):
                        continue
                found[item_url] = {
                    "site_id": self.site_id, "url": item_url, "title": title[:500],
                    "price": parse_display_price(card.get("text", "")) or card.get("price"), "image_url": card.get("image_url"), "currency": "CNY",
                    "search_query": query,
                }
                if len(found) >= limit:
                    return list(found.values())[:limit]
            # Infinite-scroll pages may repeatedly return the same first card,
            # or block Chromium while synthesizing wheel input. Scroll only
            # while the previous round added results and stop after the first
            # no-growth round so a search cannot monopolize the single worker.
            if page_round >= 3 or (page_round > 0 and len(found) == previous_count):
                break
            self.progress(f"已读取 {len(found)} 件闲鱼商品，正在加载更多")
            try:
                self.page.evaluate("window.scrollBy(0, Math.max(600, window.innerHeight * 0.8))")
                self.page.wait_for_timeout(600)
            except Exception:
                break
        return list(found.values())[:limit]

    def search_many(self, queries: list[str], limit: int = 20) -> list[dict]:
        queries = list(dict.fromkeys(query.strip() for query in queries if query and query.strip()))[:5]
        if not queries:
            raise XianyuCollectionError("没有可用的搜索词；请先采集日本商品标题或说明")
        found = {}
        per_query = max(1, (limit + len(queries) - 1) // len(queries))
        for index, query in enumerate(queries, start=1):
            self.checkpoint()
            self.progress(f"根据日本商品资料执行闲鱼搜索 {index}/{len(queries)}")
            for item in self.search(query, min(per_query, limit - len(found))):
                if item["url"] not in found:
                    found[item["url"]] = item
                else:
                    found[item["url"]].setdefault("matched_queries", []).append(query)
            if len(found) >= limit:
                break
        return list(found.values())[:limit]

    def collect_detail_images(self, url: str, limit: int = 10) -> dict:
        """Read image candidates from the selected public listing and visible review areas."""
        item_url = validate_item_url(url)
        self.checkpoint()
        try:
            response = self.page.goto(item_url, wait_until="domcontentloaded", timeout=45000)
        except Exception as error:
            if "err_network_access_denied" in str(error).lower():
                raise XianyuCollectionError("工作台浏览器受当前进程的网络隔离限制，请从 Windows 正常环境运行 start.ps1 后重试") from error
            raise XianyuCollectionError("闲鱼商品详情页暂时无法打开") from error
        if response and response.status >= 400:
            raise XianyuCollectionError(f"闲鱼商品详情页返回 HTTP {response.status}")
        if urlparse(self.page.url).hostname not in ("www.goofish.com", "goofish.com"):
            raise XianyuCollectionError("闲鱼商品详情页跳转到了其他站点")

        found = {}
        excluded_images = {}
        image_diagnostics = {}
        for step in range(6):
            self.checkpoint()
            snapshot = self.page.evaluate(DETAIL_IMAGE_EXTRACTOR)
            for image in snapshot.get("image_diagnostics", []):
                if image.get("url") and len(image_diagnostics) < 100:
                    image_diagnostics[image["url"]] = image
            for image in snapshot.get("images", []):
                region = re.sub(r"\s+", " ", str(image.get("region", ""))).strip()
                excluded = bool(image.get("excluded_region")) or bool(re.search(
                    r"(?:header|logo|footer|survey|announcement|item-feeds-list-container|recommend(?:ed|ation)?-(?:list|card|container)|similar-(?:items|goods|products)|related-(?:items|goods|products))",
                    region, re.I,
                ))
                if excluded:
                    try:
                        excluded_url = validate_image_url(image.get("url", ""))
                    except (ValueError, TypeError):
                        excluded_url = ""
                    if excluded_url:
                        excluded_images.setdefault(excluded_url, {
                            "url": excluded_url,
                            "region": region[:500],
                            "alt": re.sub(r"\s+", " ", str(image.get("alt", ""))).strip()[:120],
                        })
                    continue
                try:
                    image_url = validate_image_url(image.get("url", ""))
                except (ValueError, TypeError):
                    continue
                if image_url not in found:
                    context = re.sub(r"\s+", " ", image.get("context", "")).strip()[:240]
                    alt = re.sub(r"\s+", " ", image.get("alt", "")).strip()[:120]
                    review_hint = bool(re.search(r"评论|评价|买家秀|晒单|实拍|到货|追评", context + " " + alt))
                    found[image_url] = {
                        "url": image_url,
                        "width": image.get("width"), "height": image.get("height"),
                        "alt": alt, "context": context,
                        "region": region[:500],
                        "collection_note": "详情页评论/晒单区域候选" if review_hint else "闲鱼商品详情页图片候选",
                    }
                if len(found) >= limit:
                    break
            if len(found) >= limit or step == 5:
                break
            self.page.evaluate("fraction => window.scrollTo(0, document.body.scrollHeight * fraction)", (step + 1) / 6)
            self.page.wait_for_timeout(500)
        return {"url": item_url, "title": snapshot.get("title", ""),
                "text": re.sub(r"\s+", " ", snapshot.get("text", "")).strip()[:8000],
                "images": list(found.values())[:limit],
                "image_diagnostics": list(image_diagnostics.values()),
                "single_image_gallery": snapshot.get("single_image_gallery", False),
                "gallery_asset_urls": snapshot.get("gallery_asset_urls", []),
                "excluded_images": list(excluded_images.values())[:100]}
