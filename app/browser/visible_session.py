from contextlib import contextmanager
from collections.abc import Iterator

from playwright.sync_api import BrowserContext, Page, sync_playwright


@contextmanager
def visible_page() -> Iterator[Page]:
    """Open a visible temporary browser; do not persist login state or credentials."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context: BrowserContext = browser.new_context()
        try:
            yield context.new_page()
        finally:
            context.close()
            browser.close()
