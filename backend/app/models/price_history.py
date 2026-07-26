"""Fiyat zaman serisi — projenin merkezî tablosu.

Grain: bir ürün + bir depo + bir gün = tek satır. Idempotency bu bileşik
anahtarla sağlanır; pipeline aynı gün iki kez koşarsa kayıt katlanmaz.

Fiyat düzeyi PLATFORM KAYDI (`product_id`) bazındadır, takip kalemi bazında değil.
Birleştirme okuma/analiz anında yapılır — böylece bir bağlantı sonradan
düzeltilirse geçmiş veri bozulmaz.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "depot_id", "collected_date",
            name="uq_price_history_urun_depo_gun",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    depot_id: Mapped[str] = mapped_column(ForeignKey("depots.id"), index=True)
    # Depodan türetilebilir; sorgu kolaylığı için denormalize tutuluyor.
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), index=True)

    # Para: her yerde Decimal / NUMERIC — float ASLA (anayasa md. 1).
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # Üstü çizili eski fiyat (varsa) — destekleyici indirim sinyali.
    discountless_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # Platformun en-ucuza fark yüzdesi. 0 = o kayıt içinde en ucuz.
    # ⚠️ Yalnız TEK katalog kaydı içinde geçerlidir; kalem düzeyinde yetki değildir.
    # Ham hassasiyet saklanır (API 17.647058 döner, site %17,6 gösterir).
    percentage: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    unit_price_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    unit_price_text: Mapped[str | None] = mapped_column(String(50))

    # Platformun indeksleme anı (yanıttaki `indexTime`).
    index_time: Mapped[datetime | None] = mapped_column(DateTime)
    # Gözlemin ait olduğu gün — idempotency anahtarının parçası.
    # `indexTime`'ın gününden türetilir; yoksa YEREL güne düşülür (UTC değil,
    # yoksa gün sınırı UTC+3'te gece 03:00'te döner). Bkz. `utils/tarih.py`.
    collected_date: Mapped[date] = mapped_column(Date, index=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<PriceHistory p{self.product_id} {self.depot_id} {self.collected_date} {self.price}>"
