"""Takip listesi ve arama şemaları."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SearchCandidate(BaseModel):
    """Aramadan dönen aday ürün — listeye eklenmek üzere."""

    source_product_id: str = Field(description="Platform ürün ID'si, ör. 1LMO")
    title: str
    brand: str | None
    refined_volume_or_weight: str | None = Field(description="Platformun gramaj metni")
    image_url: str | None
    market_sayisi: int = Field(description="Bu kayıtta fiyatı olan market sayısı")
    en_dusuk_fiyat: Decimal | None
    zaten_takipte: bool
    bagli_kalem_id: int | None


class WatchlistSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_product_id: str
    title_snapshot: str | None
    link_confirmed_by: str
    linked_at: datetime


class WatchlistItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    note: str | None
    active: bool
    added_at: datetime
    sources: list[WatchlistSourceOut]


class WatchlistItemCreate(BaseModel):
    label: str | None = Field(
        default=None,
        description="Boş bırakılırsa ilk ürünün platformdaki adı kullanılır.",
    )
    source_product_ids: list[str] = Field(
        min_length=1,
        description=(
            "Bağlanacak platform ürün ID'leri. Aynı fiziksel ürünün birden çok "
            "katalog kaydı varsa hepsi buraya yazılır — en ucuz o zaman doğru bulunur."
        ),
    )
    note: str | None = None


class WatchlistSourceAdd(BaseModel):
    source_product_id: str


class DuplicateCandidate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_product_id: str
    title: str
    brand: str | None
    refined_volume_or_weight: str | None
    image_url: str | None
