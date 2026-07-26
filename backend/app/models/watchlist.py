"""Takip listesi — iki katmanlı (26.07.2026 dedup bulgusunun sonucu).

    watchlist_items        = kullanıcının kafasındaki ürün ("Red Bull Blue Edition 250 ml")
        └─ 1..N ─> watchlist_source_ids = platformdaki karşılıkları (1TOK, 21D5, ...)

Neden iki tablo: platform aynı fiziksel ürünü zincir başına ayrı katalog kaydında
bırakabiliyor ve bu kayıtların depo kümeleri AYRIK oluyor. Tek kayda bakan
"en ucuz 60,00" derken aynı ürün başka kayıtta 55,00 olabiliyor.
Bkz. Obsidian → Veri-Kaynaklari → "26.07.2026 doğrulaması", Bulgu 3.

Bağlama kararı KULLANICININDIR; sistem yalnız aday önerir (`link_confirmed_by`).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class WatchlistItem(Base):
    """Takip kalemi — fiyat karşılaştırması ve mesaj bu düzeyde üretilir."""

    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(300))
    note: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    sources: Mapped[list[WatchlistSourceId]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<WatchlistItem {self.id} {self.label[:30]!r}>"


class WatchlistSourceId(Base):
    """Kalemin platformdaki bir karşılığı. Toplama bu tablodaki her satır için çalışır."""

    __tablename__ = "watchlist_source_ids"

    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_item_id: Mapped[int] = mapped_column(
        ForeignKey("watchlist_items.id", ondelete="CASCADE"), index=True
    )
    # Aynı platform ürünü iki kaleme bağlanamaz.
    source_product_id: Mapped[str] = mapped_column(
        ForeignKey("products.source_product_id"), unique=True, index=True
    )
    # Bağlandığı andaki platform adı — ürünün adı sonradan değişirse iz kalsın.
    title_snapshot: Mapped[str | None] = mapped_column(String(500))
    # 'user' = kullanıcı onayladı, 'seed' = başlangıç listesinden geldi.
    link_confirmed_by: Mapped[str] = mapped_column(String(20), default="user")
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    item: Mapped[WatchlistItem] = relationship(back_populates="sources")

    def __repr__(self) -> str:
        return f"<WatchlistSourceId {self.source_product_id} -> item {self.watchlist_item_id}>"
