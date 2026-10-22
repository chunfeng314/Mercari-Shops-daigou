from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from app.schemas import BaseModel


class ItemUpdate(BaseModel):
    japan_title: str | None = Field(default=None, min_length=1, max_length=500)
    japan_url: str | None = None
    japan_price_jpy: int | None = Field(default=None, gt=0)
    japan_image_url: str | None = None
    note: str | None = Field(default=None, max_length=10000)

    @field_validator("japan_url", "japan_image_url")
    @classmethod
    def http_url(cls, value):
        if value in (None, ""):
            return value
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("请填写完整的 http 或 https 链接")
        return value

    @model_validator(mode="after")
    def non_null_text(self):
        for name in ("japan_title", "japan_url", "note"):
            if name in self.model_fields_set:
                value = getattr(self, name)
                if value is None or (name != "note" and not value.strip()):
                    raise ValueError(f"{name} 不能为空")
        return self


class SourceUpdate(BaseModel):
    source_url: str | None = None
    source_title: str | None = Field(default=None, max_length=500)
    price_cny: float | None = Field(default=None, gt=0)
    account_note: str | None = Field(default=None, max_length=10000)

    @model_validator(mode="after")
    def validate_values(self):
        for name in ("source_url", "source_title", "account_note"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} 不能为 null")
        if "source_url" in self.model_fields_set:
            parsed = urlparse(self.source_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("请填写完整的货源链接")
        return self


class OrderCancellation(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    release_inventory: bool = False

    @field_validator("reason")
    @classmethod
    def reason_required(cls, value):
        if not value.strip():
            raise ValueError("请填写取消原因")
        return value.strip()


class OrderReturnReceipt(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class RefundConfirmation(BaseModel):
    refund_reference: str = Field(min_length=1, max_length=200)
    amount_jpy: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("refund_reference", "reason")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("不能为空白")
        return value.strip()


class StockConfirmation(BaseModel):
    remaining_quantity: int = Field(ge=0)
    note: str = Field(min_length=1, max_length=1000)


class WithdrawalConfirmation(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
