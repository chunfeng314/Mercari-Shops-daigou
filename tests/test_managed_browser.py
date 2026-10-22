"""Browser ownership, profile isolation, and legacy settings migration checks."""
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.browser.managed_browser import ManagedBrowserSessions, navigate_managed
from app.schemas_automation import BrowserSessionTask
from app.automation.service import AutomationService
from app.db import _allow_managed_browser


class FakePage:
    url = "about:blank"

    def is_closed(self):
        return False


class FakeContext:
    def __init__(self):
        self.browser = SimpleNamespace(is_connected=lambda: True, new_browser_cdp_session=Mock(return_value=Mock()))
        self.pages = [FakePage()]
        self.closed_callback = None

    def on(self, _event, callback):
        self.closed_callback = callback

    def set_default_timeout(self, _timeout):
        pass

    def set_default_navigation_timeout(self, _timeout):
        pass

    def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page

    def close(self):
        if self.closed_callback:
            self.closed_callback()


class ManagedBrowserTests(unittest.TestCase):
    def test_browser_session_accepts_taobao_and_dewu_for_china_profile(self):
        task = BrowserSessionTask(scope="china", urls=[
            "https://www.taobao.com/", "https://www.dewu.com/",
        ])
        self.assertEqual(len(task.urls), 2)

    def test_browser_session_rejects_other_scope_sites(self):
        with self.assertRaisesRegex(ValueError, "不允许"):
            BrowserSessionTask(scope="china", urls=["https://jp.mercari.com/"])

    def test_browser_session_opens_multiple_sites_in_separate_persistent_tabs(self):
        service = AutomationService()
        pages = [
            SimpleNamespace(url="about:blank", bring_to_front=Mock()),
            SimpleNamespace(url="about:blank", bring_to_front=Mock()),
        ]
        control = Mock()
        payload = {"scope": "china", "browser_channel": "chrome", "urls": [
            "https://www.taobao.com/", "https://www.dewu.com/",
        ]}
        with patch.object(service, "_driver"), \
             patch.object(service.managed_browser, "page", side_effect=pages) as get_page, \
             patch("app.automation.service.navigate_managed") as navigate:
            result = service._execute({"kind": "browser_session", "payload": payload}, control)
        self.assertEqual(get_page.call_count, 2)
        self.assertEqual([call.args[1] for call in navigate.call_args_list], payload["urls"])
        self.assertEqual(result["tabs_opened"], 2)
        pages[1].bring_to_front.assert_called_once()

    def test_japan_collection_browser_uses_japan_proxy(self):
        service = AutomationService()
        launch = Mock()
        service.playwright = SimpleNamespace(chromium=SimpleNamespace(launch=launch))
        service._driver = Mock()
        settings = SimpleNamespace(
            browser_headless=False,
            browser_channel="chrome",
            japan_browser_proxy="socks5://127.0.0.1:10090",
            browser_proxy="",
        )
        with patch("app.automation.service.settings", settings):
            service._launch()
        self.assertEqual(launch.call_args.kwargs["proxy"], {"server": "socks5://127.0.0.1:10090"})

    def test_closed_browser_with_undelivered_event_reopens_in_the_same_task(self):
        with TemporaryDirectory() as directory:
            manager = ManagedBrowserSessions(Path(directory))
            contexts = [FakeContext(), FakeContext()]
            launch = Mock(side_effect=contexts)
            driver = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
            first = manager.page(driver, "china")
            contexts[0].browser.new_browser_cdp_session.side_effect = RuntimeError(
                "Browser.new_browser_cdp_session: Target page, context or browser has been closed")
            second = manager.page(driver, "china")
            self.assertIsNot(first, second)
            self.assertEqual(launch.call_count, 2)
            self.assertEqual(launch.call_args_list[0].args[0], launch.call_args_list[1].args[0])
            self.assertEqual(len(manager.status()), 1)
            manager.close()

    def test_closed_window_is_not_reported_as_a_vpn_failure(self):
        page = Mock()
        page.goto.side_effect = RuntimeError("Target page, context or browser has been closed")
        with self.assertRaisesRegex(ValueError, "窗口已关闭"):
            navigate_managed(page, "https://www.goofish.com/")

    def test_reuses_transport_and_profile_without_attaching_to_daily_chrome(self):
        with TemporaryDirectory() as directory:
            manager = ManagedBrowserSessions(Path(directory))
            launch = Mock(side_effect=lambda *_args, **_kwargs: FakeContext())
            driver = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
            first = manager.page(driver, "china")
            self.assertIs(manager.page(driver, "china"), first)
            self.assertEqual(launch.call_count, 1)
            self.assertEqual(Path(launch.call_args.args[0]), Path(directory) / "china" / "chrome")
            manager.page(driver, "japan")
            self.assertEqual(launch.call_count, 2)
            self.assertNotEqual(launch.call_args_list[0].args[0], launch.call_args_list[1].args[0])
            manager.close("china")
            self.assertEqual(manager.status()[0]["scope"], "japan")
            manager.page(driver, "china")
            self.assertEqual(launch.call_count, 3)
            self.assertEqual(launch.call_args_list[0].args[0], launch.call_args_list[2].args[0])
            manager.close()

    def test_managed_shop_reuses_logged_in_session_without_user_confirmation(self):
        service = AutomationService()
        root = "https://mercari-shops.com/seller/shops/test-shop"
        page = SimpleNamespace(url=root)
        control = Mock()
        with patch.object(service, "_driver"), \
             patch.object(service.managed_browser, "context"), \
             patch.object(service.managed_browser, "page", return_value=page), \
             patch.object(service.existing_shop, "connect") as external, \
             patch("app.automation.service.is_signed_in", return_value=True):
            self.assertIs(service._shop(control, url=root), page)
            self.assertIs(service._shop(control, url=root), page)
        control.wait_for_user.assert_not_called()
        external.assert_not_called()

    def test_migration_preserves_saved_shop_and_allows_managed_mode(self):
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("""CREATE TABLE shop_browser_settings (
                id INTEGER PRIMARY KEY CHECK(id=1),
                browser_mode TEXT NOT NULL CHECK(browser_mode IN ('temporary','existing_chrome')),
                browser_channel TEXT NOT NULL CHECK(browser_channel IN ('chrome','msedge')),
                url TEXT NOT NULL DEFAULT '')""")
            url = "https://mercari-shops.com/seller/shops/test-shop"
            connection.execute("INSERT INTO shop_browser_settings VALUES(1,'existing_chrome','chrome',?)", (url,))
            _allow_managed_browser(connection)
            _allow_managed_browser(connection)
            connection.execute("UPDATE shop_browser_settings SET browser_mode='managed'")
            self.assertEqual(connection.execute("SELECT browser_mode,url FROM shop_browser_settings").fetchone(), ("managed", url))
        finally:
            connection.close()
