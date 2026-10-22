"""A CDP attachment never owns the user's browser or its default context."""
import re
from pathlib import Path
from urllib.parse import urlparse

from app.config import settings
from app.browser.existing_browser import _debug_endpoint
from app.modules.mercari_listing.browser_adapter import validate_shop_management_url


def shop_root(url: str) -> str:
    validate_shop_management_url(url)
    match = re.match(r"^/seller/shops/([A-Za-z0-9_-]+)(?:/|$)", urlparse(url).path)
    if not match:
        raise ValueError("连接真实浏览器需要具体的店铺管理地址 /seller/shops/店铺ID")
    return f"https://mercari-shops.com/seller/shops/{match[1]}"


def belongs_to_shop(url: str, root: str) -> bool:
    parsed, target = urlparse(url), urlparse(root)
    return (parsed.scheme == "https" and parsed.hostname == "mercari-shops.com"
            and not parsed.username and not parsed.password and parsed.port in (None, 443)
            and (parsed.path == target.path or parsed.path.startswith(target.path + "/")))


def _shop_debug_endpoint(channel: str, profile_root: Path | str | None = None) -> str | None:
    """Find the CDP endpoint for the isolated, manually logged-in Shops profile."""
    if channel == "chrome":
        profile = Path(profile_root or settings.browser_profile_root).resolve() / "japan" / "shop-login"
        try:
            lines = (profile / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()
            port = int(lines[0])
            path = lines[1]
        except (OSError, ValueError, IndexError):
            pass
        else:
            if 1 <= port <= 65535 and re.fullmatch(r"/devtools/browser/[A-Za-z0-9_-]+", path):
                return f"ws://127.0.0.1:{port}{path}"
    return _debug_endpoint(channel)


class ExistingShopBrowser:
    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None
        self.channel = ""
        self.root = ""

    def connect(self, playwright, channel: str, url: str, timeout: int):
        if channel not in ("chrome", "msedge"):
            raise ValueError("仅支持连接本机 Chrome 或 Edge")
        root = shop_root(url)
        if self.browser and self.browser.is_connected() and self.channel == channel and self.root == root:
            if self.page and not self.page.is_closed() and belongs_to_shop(self.page.url, root):
                return self.page
        self.disconnect()
        try:
            self.browser = playwright.chromium.connect_over_cdp(
                _shop_debug_endpoint(channel) or channel, timeout=timeout, no_defaults=True
            )
            contexts = self.browser.contexts
            if not contexts:
                raise ValueError("浏览器没有可用的现有用户会话")
            self.context = contexts[0]
            pages = [page for page in self.context.pages if belongs_to_shop(page.url, root)]
            if not pages:
                raise ValueError("请在真实浏览器打开这个店铺的管理页面，再重新连接；不会选择其他店铺或登录标签。")
            self.page = pages[0]
            self.channel, self.root = channel, root
            return self.page
        except Exception as error:
            self.disconnect()
            message = str(error).lower()
            if any(token in message for token in ("connect", "debug", "refused", "closed", "timeout", "timed out")):
                name = "Chrome" if channel == "chrome" else "Edge"
                raise ValueError(
                    f"无法连接本机 {name} 调试会话。请在浏览器的 remote debugging 页面开启远程调试，"
                    "并允许本次连接；系统不会读取或复制登录凭据。"
                ) from error
            raise

    def page_for(self, purpose: str):
        """Use a separate tab for application tasks, preserving the user's existing page."""
        suffix = {"fill": "/products/create", "inspect": "/products/create", "orders": "/orders"}.get(purpose)
        if suffix is None:
            return self.page
        target = self.root + suffix
        if purpose != "fill":
            for page in self.context.pages:
                if not page.is_closed() and belongs_to_shop(page.url, self.root) and urlparse(page.url).path == urlparse(target).path:
                    self.page = page
                    return page
        self.page = self.context.new_page()
        self.page.set_default_timeout(8000)
        self.page.goto(target, wait_until="domcontentloaded")
        return self.page

    def disconnect(self):
        if self.browser:
            # Browser.close() on a CDP attachment disconnects its transport.
            # Never close the user's default context or individual pages.
            try:
                self.browser.close()
            finally:
                self.browser = self.context = self.page = None
                self.channel = self.root = ""
