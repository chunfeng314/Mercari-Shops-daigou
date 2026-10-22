"""Attach a narrowly scoped task tab to an already-open local browser.

The user's browser remains the owner of its process, profile, VPN route, and
cookies. This module only creates a new page in the existing default context;
it never exports cookies or closes the user's browser.
"""
import os
from pathlib import Path
import re


def _debug_endpoint(channel: str) -> str | None:
    """Resolve Chromium's per-instance WebSocket path without reading profile data."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    if channel == "chrome":
        profile = Path(local_app_data) / "Google" / "Chrome" / "User Data"
    elif channel == "msedge":
        profile = Path(local_app_data) / "Microsoft" / "Edge" / "User Data"
    else:
        return None
    try:
        lines = (profile / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()
        port = int(lines[0])
        path = lines[1]
    except (OSError, ValueError, IndexError):
        return None
    if not 1 <= port <= 65535 or not re.fullmatch(r"/devtools/browser/[A-Za-z0-9_-]+", path):
        return None
    return f"ws://localhost:{port}{path}"


class ExistingBrowserSession:
    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None
        self.channel = ""

    def connect(self, playwright, channel: str, timeout: int):
        if channel not in ("chrome", "msedge"):
            raise ValueError("仅支持连接本机 Chrome 或 Edge")
        if self.browser and self.browser.is_connected() and self.channel == channel:
            if self.page and not self.page.is_closed():
                return self.page
        self.disconnect()
        try:
            endpoint = _debug_endpoint(channel)
            self.browser = playwright.chromium.connect_over_cdp(
                endpoint or channel, timeout=timeout, no_defaults=True
            )
            contexts = self.browser.contexts
            if not contexts:
                raise ValueError("本机浏览器没有可用的用户会话")
            self.context = contexts[0]
            # Use a dedicated tab. Do not inspect, navigate, or close the user's
            # existing pages; this tab inherits the browser's normal VPN route.
            self.page = self.context.new_page()
            self.page.set_default_timeout(8000)
            self.page.set_default_navigation_timeout(timeout)
            self.channel = channel
            return self.page
        except ValueError:
            self.disconnect()
            raise
        except Exception as error:
            self.disconnect()
            message = str(error).lower()
            if any(token in message for token in ("connect", "debug", "refused", "closed", "timeout", "timed out")):
                name = "Chrome" if channel == "chrome" else "Edge"
                raise ValueError(
                    f"无法连接本机 {name} 调试会话。请在 chrome://inspect/#remote-debugging 或 edge://inspect/#remote-debugging "
                    "开启远程调试并允许本次连接；确认前不会访问平台页面。"
                ) from error
            raise ValueError("连接本机浏览器失败，请确认浏览器仍在运行后重试") from error

    def disconnect(self):
        if self.browser:
            try:
                # On a CDP attachment this disconnects Playwright's transport;
                # it does not close the user's browser or the task tab.
                self.browser.close()
            finally:
                self.browser = self.context = self.page = None
                self.channel = ""
