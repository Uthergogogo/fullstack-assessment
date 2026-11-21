from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class OptionValue(BaseModel):
    id: str
    label: str


class ProductOption(BaseModel):
    id: str
    label: str
    values: list[OptionValue]


class Sku(BaseModel):
    id: str
    option_values: dict[str, str]
    price_minor: int
    available_quantity: int
    image_url: str
    is_available: bool


class Product(BaseModel):
    id: str
    name: str
    description: str
    currency: str
    options: list[ProductOption]
    skus: list[Sku]


class AddCartItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]
    quantity: Annotated[int, Field(strict=True, gt=0, le=2**31 - 1)]


class CartItem(BaseModel):
    sku_id: str
    quantity: int
    unit_price_minor: int
    currency: str


class Cart(BaseModel):
    items: list[CartItem]
    total_item_count: int


class AddCartResult(BaseModel):
    cart: Cart
    sku_id: str
    available_quantity: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, object] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
