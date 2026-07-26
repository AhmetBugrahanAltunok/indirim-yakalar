"""Platform ürün kayıtlarını `products` tablosuna yazar.

Bu katman ürünü YORUMLAMAZ — platformun verdiği alanları olduğu gibi saklar.
Gramaj/adet ayrıştırma normalizer'ın işi (Faz 1 adım 6); burada yalnız kimlik
ve gösterim alanları tutulur.

`source_product_id` günler arası kalıcıdır (26.07.2026'da 7/7 doğrulandı),
bu yüzden upsert anahtarı odur.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Product


def _ilk_dolu(*degerler: Any) -> str | None:
    for d in degerler:
        if isinstance(d, str) and d.strip():
            return d.strip()
    return None


def urun_kaydet(db: Session, kayit: dict[str, Any]) -> Product:
    """Platform ürün kaydını yazar veya günceller, `Product` döner.

    `kayit`, `/search` veya `/searchByIdentity` yanıtındaki tek bir ürün nesnesidir.
    """
    spid = kayit.get("id")
    if not spid:
        raise ValueError(f"Ürün kaydında `id` yok: {kayit!r}")

    baslik = _ilk_dolu(kayit.get("title")) or spid
    urun = db.scalar(select(Product).where(Product.source_product_id == spid))
    simdi = datetime.now(timezone.utc)

    if urun is None:
        urun = Product(source_product_id=spid, title=baslik)
        db.add(urun)

    urun.title = baslik
    urun.brand = _ilk_dolu(kayit.get("brand"))
    urun.refined_volume_or_weight = _ilk_dolu(kayit.get("refinedVolumeOrWeight"))
    urun.image_url = _ilk_dolu(kayit.get("imageUrl"))
    urun.main_category = _ilk_dolu(
        kayit.get("main_category"), kayit.get("mainCategory")
    )
    urun.menu_category = _ilk_dolu(
        kayit.get("menu_category"), kayit.get("menuCategory")
    )
    urun.last_seen_at = simdi

    db.flush()
    return urun


def urunleri_kaydet(db: Session, kayitlar: list[dict[str, Any]]) -> list[Product]:
    return [urun_kaydet(db, k) for k in kayitlar]
