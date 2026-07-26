"""Market zincirleri ve mağazaları (depolar).

Depo, aramanın konum anahtarıdır: her API çağrısı depo ID listesiyle yapılır,
yoksa fiyatlar yanlış şehirden gelir ve bu sessizce olur.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class Market(Base):
    """Zincir: a101, bim, sok, migros, carrefour, tarim_kredi, hakmar."""

    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Platformun `marketAdi` alanı — kaynak tarafındaki kimlik.
    slug: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))

    depots: Mapped[list[Depot]] = relationship(back_populates="market")

    def __repr__(self) -> str:
        return f"<Market {self.slug}>"


class Depot(Base):
    """Tek mağaza. Kimliği platformdan gelir (ör. `a101-XXXX`) — kendi ID'mizi üretmeyiz.

    Aynı zincirin iki şubesi farklı fiyat verebilir (26.07.2026 gözlemi: aynı
    zincirin iki şubesinde 70,00 ⟷ 55,00), bu yüzden fiyat depo düzeyinde tutulur.
    """

    __tablename__ = "depots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)
    name: Mapped[str | None] = mapped_column(String(200))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    # /nearest yanıtındaki `distance` (metre).
    distance_m: Mapped[float | None] = mapped_column(Numeric(10, 2))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    market: Mapped[Market] = relationship(back_populates="depots")

    def __repr__(self) -> str:
        return f"<Depot {self.id}>"
