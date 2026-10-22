"""Authentication-state checks for the persistent Mercari Shops browser."""
import unittest
from unittest.mock import Mock

from app.modules.mercari_listing.browser_adapter import is_signed_in


def fake_page(url: str, title: str, login_control_count: int = 0) -> Mock:
    page = Mock()
    page.url = url
    page.title.return_value = title
    page.locator.return_value.count.return_value = login_control_count
    return page


class ShopSignInDetectionTests(unittest.TestCase):
    def test_login_page_title_inside_seller_route_is_not_signed_in(self):
        page = fake_page(
            "https://mercari-shops.com/seller/shops/example",
            "【公式】メルカリShops 管理画面 ログインページ",
        )

        self.assertFalse(is_signed_in(page))

    def test_visible_login_control_is_not_signed_in(self):
        page = fake_page(
            "https://mercari-shops.com/seller/shops/example",
            "Mercari Shops 管理画面",
            login_control_count=1,
        )

        self.assertFalse(is_signed_in(page))

    def test_shop_management_page_without_login_controls_is_signed_in(self):
        page = fake_page(
            "https://mercari-shops.com/seller/shops/example/products",
            "商品 - Mercari Shops",
        )

        self.assertTrue(is_signed_in(page))


if __name__ == "__main__":
    unittest.main()
