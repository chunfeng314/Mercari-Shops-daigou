from datetime import date
from typing import Any, Literal

from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field, field_validator


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


class JapanCandidateCreate(BaseModel):
    japan_site: str
    japan_url: str = Field(min_length=1)
    japan_title: str = Field(min_length=1)
    japan_price_jpy: int | None = Field(default=None, gt=0)
    japan_image_url: str | None = None
    note: str = ""


class ChinaSourceCreate(BaseModel):
    china_site: str
    source_url: str = Field(min_length=1)
    source_title: str = ""
    price_cny: float | None = Field(default=None, gt=0)
    account_note: str = ""


class ChinaSourceConfirmation(BaseModel):
    match_note: str = Field(min_length=1)
    availability_status: Literal["available", "unavailable", "unknown"]
    price_cny: float | None = Field(default=None, gt=0)
    availability_commitment: bool = False
    committed_quantity: int | None = Field(default=None, gt=0)
    commitment_valid_until: date | None = None


class ListingDraftCreate(BaseModel):
    china_source_id: str = Field(min_length=1)
    title_ja: str = Field(min_length=1, max_length=130)
    description_ja: str = Field(default="", max_length=3000)
    image_refs: list[str] = Field(default_factory=list)
    image_asset_ids: list[str] = Field(default_factory=list)
    category: str = Field(min_length=1)
    category_attributes: dict[str, Any] = Field(default_factory=dict)
    brand: str = ""
    condition: str = Field(min_length=1)
    reservation_sale: bool = False
    multi_variant: bool = False
    inventory_quantity: int = Field(default=1, gt=0)
    max_quantity_per_order: int | None = Field(default=None, gt=0)
    inventory_variants: list[dict] = Field(default_factory=list)
    reservation_release_date: date | None = None
    reservation_start_date: date | None = None
    reservation_end_date: date | None = None
    reservation_cancel_deadline: date | None = None
    reservation_delivery_timing: Literal["release_date", "after_release"] = "after_release"
    jan_code: str = ""
    management_code: str = ""
    shipping_method: str = Field(min_length=1)
    shipping_payer: str = Field(min_length=1)
    shipping_origin: str = Field(min_length=1)
    handling_days: str = Field(min_length=1)
    estimated_china_to_japan_shipping_cny: float | None = Field(default=None, ge=0)
    price_jpy: int = Field(ge=300, le=9_999_999)
    exchange_rate_cny_per_jpy: float | None = Field(default=None, gt=0)
    mercari_fee_rate: float = Field(ge=0, lt=1)
    shipping_jpy: int | None = Field(default=None, ge=0)
    other_costs_jpy: int | None = Field(default=None, ge=0)

    @field_validator("title_ja", "category", "condition", "shipping_method", "shipping_payer", "shipping_origin", "handling_days")
    @classmethod
    def required_text(cls, value):
        if not value.strip():
            raise ValueError("必填资料不能只有空格")
        return value.strip()


class ListingDefaultsUpdate(BaseModel):
    shipping_method: str = Field(min_length=1, max_length=120)
    shipping_payer: str = Field(min_length=1, max_length=120)
    shipping_origin: str = Field(min_length=1, max_length=120)
    handling_days: str = Field(min_length=1, max_length=120)
    mercari_fee_rate: float = Field(ge=0, lt=1)


class ListingPublishConfirmation(BaseModel):
    listing_url: str = Field(min_length=1)


class SalesOrderCreate(BaseModel):
    item_id: str = Field(min_length=1)
    mercari_order_id: str = Field(min_length=1)
    quantity: int = Field(default=1, gt=0)
    sold_price_jpy: int = Field(gt=0)


class OrderPurchaseConfirmation(BaseModel):
    china_source_id: str = Field(min_length=1)
    actual_price_cny: float = Field(gt=0)
    actual_china_to_japan_shipping_cny: float = Field(default=0, ge=0)


class OrderChinaShipment(BaseModel):
    carrier: str = Field(min_length=1)
    tracking_number: str = Field(min_length=1)


class OrderJapanReceipt(BaseModel):
    inspection_result: Literal["passed", "issue"]
    inspection_note: str = ""


class OrderDomesticShipment(BaseModel):
    carrier: str = Field(min_length=1)
    tracking_number: str = Field(min_length=1)
