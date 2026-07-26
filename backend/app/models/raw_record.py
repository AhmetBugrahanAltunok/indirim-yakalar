"""Ham API yanıtları — değiştirilmeden saklanır.

Amaç yeniden işlenebilirlik: normalizer'da hata bulunursa veya alan anlamı
sonradan değişirse, API'yi tekrar yormadan geçmiş veriden yeniden üretilebilir.
Belgesiz bir API'ye bağlı olduğumuz için bu tablo sigortadır.

⚠️ JSONB'ye yazarken: yanıt `json.loads(..., parse_float=Decimal)` ile ayrıştırılır,
ama Decimal doğrudan JSON'a serileştirilemez. Collector ham METNİ saklar
(`raw_json`), Decimal'e çevrilmiş hâli yalnız işleme sırasında kullanılır.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class RawRecord(Base):
    __tablename__ = "raw_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50), index=True, default="market_fiyati")
    # Hangi ürün için çekildi (platform ID'si) — henüz products'ta olmayabilir.
    source_product_id: Mapped[str | None] = mapped_column(String(32), index=True)
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.id"))

    # Yanıtın kendisi. JSONB sorgulanabilirlik için, raw_json ise birebir sadakat için.
    raw_data: Mapped[dict | None] = mapped_column(JSONB)
    raw_json: Mapped[str | None] = mapped_column(Text)

    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    processed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", index=True
    )
    process_error: Mapped[str | None] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"<RawRecord {self.id} {self.source_product_id} processed={self.processed}>"
