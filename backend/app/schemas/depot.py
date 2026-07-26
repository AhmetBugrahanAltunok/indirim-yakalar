"""Market ve depo şemaları."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class MarketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str = Field(description="Platformdaki zincir kodu (a101, bim, sok...)")
    name: str


class DepotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Platform depo kimliği, ör. a101-XXXX")
    market_id: int
    name: str | None
    latitude: float | None
    longitude: float | None
    distance_m: Decimal | None = Field(description="Konuma uzaklık (metre)")
    active: bool
    refreshed_at: datetime


class DepotRefreshResult(BaseModel):
    toplam: int
    yeni_depo: int
    guncellenen_depo: int
    pasife_alinan_depo: int
    yeni_market: int
    ozet: str
