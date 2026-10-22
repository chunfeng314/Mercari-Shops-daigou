"""Workbench-owned Chrome profiles, controlled over Playwright's local pipe.

Profiles belong only to this app. The user's daily Chrome profile is never read
or copied, and task completion keeps the owned context alive for the next task.
"""
from pathlib import Path

from app.config import settings


def browser_was_closed(error: Exception) -> bool:
    message = str(error).lower()
    return any(text in message for text in (
        "target page, context or browser has been closed", "browser has been closed",
        "page has been closed", "target closed", "session closed", "connection closed",
    ))


class ManagedBrowserSessions:
    def __init__(self, profile_root: Path | None = None):
        self.profile_root = (profile_root or settings.browser_profile_root).resolve()
        self.contexts = {}
        self.pages = {}

    def context(self, playwright, scope: str, channel: str = "chrome", timeout: int = 45000):
        if scope not in ("china", "japan") or channel not in ("chrome", "msedge"):
            raise ValueError("未知的工作台浏览器配置")
        key = (scope, channel)
        context = self.contexts.get(key)
        if context is not None:
            browser = context.browser
            if browser is not None and browser.is_connected():
                try:
                    # The synchronous driver does not dispatch close events
                    # while the worker is idle. A browser-level round trip
                    # flushes those events before we trust cached page state.
                    probe = browser.new_browser_cdp_session()
                    probe.detach()
                    return context
                except Exception as error:
                    if not browser_was_closed(error):
                        raise ValueError("工作台专用浏览器控制通道异常，请关闭专用窗口后重试") from error
            self._forget(key, context)
        profile = self.profile_root / scope / channel
        profile.mkdir(parents=True, exist_ok=True)
        options = {
            "channel": channel, "headless": False, "timeout": timeout,
            "locale": "zh-CN" if scope == "china" else "ja-JP",
            "timezone_id": "Asia/Shanghai" if scope == "china" else "Asia/Tokyo",
            "viewport": {"width": 1440, "height": 1000},
            "accept_downloads": False,
        }
        proxy = (settings.china_browser_proxy if scope == "china" else settings.japan_browser_proxy) or settings.browser_proxy
        if proxy:
            options["proxy"] = {"server": proxy}
        try:
            context = playwright.chromium.launch_persistent_context(str(profile), **options)
        except Exception as error:
            message = str(error).lower()
            if any(term in message for term in ("processsingleton", "already in use", "singletonlock")):
                raise ValueError("专用浏览器配置正在被另一个工作台进程使用，请关闭重复启动的工作台后重试") from error
            raise ValueError("工作台专用浏览器启动失败，请确认已安装所选浏览器，并从 Windows 正常环境运行 start.ps1") from error
        context.set_default_timeout(8000)
        context.set_default_navigation_timeout(timeout)
        self.contexts[key] = context
        context.on("close", lambda *_: self._forget(key, context))
        return context

    def page(self, playwright, scope: str, channel: str = "chrome", purpose: str = "collection", timeout: int = 45000):
        context = self.context(playwright, scope, channel, timeout)
        key = (scope, channel, purpose)
        page = self.pages.get(key)
        if page is None or page.is_closed():
            # The initial blank page is app-owned too; reuse it when possible.
            blank = next((p for p in context.pages if p.url == "about:blank" and not p.is_closed()), None)
            page = blank or context.new_page()
            self.pages[key] = page
        return page

    def _forget(self, key, context):
        if self.contexts.get(key) is context:
            self.contexts.pop(key, None)
            self.pages = {k: page for k, page in self.pages.items() if k[:2] != key}

    def status(self):
        # Only cached Python state: status routes do not call Playwright from
        # FastAPI's request threads.
        return [{"scope": scope, "channel": channel, "login_state_persisted": True}
                for scope, channel in list(self.contexts)]

    def close(self, scope: str | None = None):
        for key, context in list(self.contexts.items()):
            if scope is None or key[0] == scope:
                try:
                    context.close()
                except Exception as error:
                    if not browser_was_closed(error):
                        raise
                finally:
                    self._forget(key, context)


def navigate_managed(page, url: str, timeout: int = 45000):
    try:
        return page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    except Exception as error:
        if browser_was_closed(error):
            raise ValueError("工作台专用浏览器窗口已关闭；下次任务会自动重开并复用本机登录状态") from error
        if "err_network_access_denied" in str(error).lower():
            raise ValueError("浏览器被当前进程的网络隔离限制，请从 Windows 正常环境运行 start.ps1；无需重复允许接管 Chrome") from error
        raise ValueError("专用浏览器暂时无法访问平台，请检查电脑的 VPN/代理连接后重试") from error
