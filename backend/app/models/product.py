"""Platform ürün kataloğu.

`source_product_id` platformun kendi ID'sidir (ör. `1LMO`) ve 26.07.2026'da
günler arası kalıcı olduğu doğrulandı (7/7) — takip bu anahtar üzerinden yapılır.

⚠️ Bir satır = bir PLATFORM KAYDI, bir fiziksel ürün değil. Platform aynı ürünü
zincir başına ayrı kayıtta bırakabiliyor (1TOK ⟷ 21D5 aynı Red Bull Blue Edition).
Fiziksel ürün düzeyi `watchlist_items` tarafındadır.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Platform `id` alanı — takip anahtarı.
    source_product_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(50), default="market_fiyati")

    title: Mapped[str] = mapped_column(String(500))
    brand: Mapped[str | None] = mapped_column(String(200), index=True)
    # Platformun hazır verdiği gramaj metni ("250 ML"). Dedup adayı bulmada kullanılır.
    refined_volume_or_weight: Mapped[str | None] = mapped_column(String(100), index=True)

    # Normalizer'ın ayrıştırdığı hâli (anayasa md. 7: gramaj kimliğin parçası).
    quantity: Mapped[float | None] = mapped_column(Numeric(12, 4))
    unit: Mapped[str | None] = mapped_column(String(20))
    package_count: Mapped[int | None] = mapped_column(Integer)
    variant: Mapped[str | None] = mapped_column(String(200))

    image_url: Mapped[str | None] = mapped_column(Text)
    main_category: Mapped[str | None] = mapped_column(String(200))
    menu_category: Mapped[str | None] = mapped_column(String(200))

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<Product {self.source_product_id} {self.title[:30]!r}>"
