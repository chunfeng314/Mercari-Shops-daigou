from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator
from urllib.parse import urlparse


class JapanSearch(BaseModel):
    site_id: Literal["mercari"] = "mercari"
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=20, ge=1, le=100)
    available_only: bool = True
    sort: Literal["newest", "price_low", "price_high", "recommended"] = "newest"

    @field_validator("query")
    @classmethod
    def query_required(cls, value):
        if not value.strip():
            raise ValueError("关键词不能为空白")
        return value.strip()


class JapanCollection(BaseModel):
    site_id: Literal["mercari"] = "mercari"
    url: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=20, ge=1, le=100)


class ChinaSearch(BaseModel):
    item_id: str = Field(min_length=1, max_length=100)
    browser_mode: Literal["managed", "existing_chrome"] = "managed"
    browser_channel: Literal["chrome", "msedge"] = "chrome"
    limit: int = Field(default=20, ge=1, le=50)


class BrowserSessionTask(BaseModel):
    scope: Literal["china", "japan"] = "china"
    browser_channel: Literal["chrome", "msedge"] = "chrome"
    urls: list[str] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validate_urls(self):
        allowed_domains = (
            ("goofish.com", "taobao.com", "dewu.com")
            if self.scope == "china"
            else ("mercari.com", "mercari-shops.com")
        )
        for value in self.urls:
            parsed = urlparse(value)
            host = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or not any(
                host == domain or host.endswith("." + domain)
                for domain in allowed_domains
            ):
                raise ValueError(f"{self.scope} 专用浏览器不允许打开此平台地址")
        return self


class ImportSelection(BaseModel):
    indexes: list[int] = Field(min_length=1, max_length=100)


class WatchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["japan_search", "japan_shop", "listing_prepare"]
    site_id: Literal["mercari"] = "mercari"
    query: str = Field(default="", max_length=200)
    url: str = Field(default="", max_length=2000)
    interval_minutes: int = Field(default=360, ge=60, le=43200)
    result_limit: int = Field(default=20, ge=1, le=100)


class WatchUpdate(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = Field(default=None, ge=60, le=43200)


class ShopTask(BaseModel):
    # The user supplies their real shop management URL after signing in.
    url: str = Field(default="", max_length=2000)
    browser_mode: Literal["managed", "temporary", "existing_chrome"] | None = None
    browser_channel: Literal["chrome", "msedge"] | None = None


class ShopBrowserSettings(BaseModel):
    url: str = Field(default="", max_length=2000)
    browser_mode: Literal["managed", "temporary", "existing_chrome"] = "managed"
    browser_channel: Literal["chrome", "msedge"] = "chrome"


class ShopOrderMapping(BaseModel):
    item_id: str = Field(min_length=1)
    amount_jpy: int | None = Field(default=None, gt=0)
    quantity: int | None = Field(default=None, gt=0)
