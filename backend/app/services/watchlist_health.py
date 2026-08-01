"""Takip listesinin sağlığı: hangi kalemler veri vermiyor.

Neden gerekli: platform bir ürünü katalogdan düşürdüğünde ya da geçici olarak
boş döndürdüğünde kalem **sessizce** listeden çıkıyor. Toplama başarılı görünüyor
(WAF bloğu yok, hata yok), kayıt sayısı birkaç azalıyor ve kimse fark etmiyor.

29.07-31.07.2026 arasında tam bu oldu: `Safya Ayçiçek Yağı 5 L` iki gün boyunca
boş döndü, kimse görmedi. `İçim Beyaz Peynir`'de de aynı şey oldu ama o kalemin
ikinci bir bağlı ID'si olduğu için fiyat akmaya devam etti — mükerrer kayıt
birleştirmesinin beklenmedik bir faydası.

Kıyas **bugüne göre değil son gözlem gününe göre** yapılır: platform bir gün
indekslemezse (01.08.2026'da oldu) bütün liste bayat görünürdü ve uyarı
anlamsızlaşırdı.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import PriceHistory, Product, WatchlistItem, WatchlistSourceId


@dataclass(frozen=True)
class BayatKalem:
    kalem_id: int
    etiket: str
    son_veri: date | None
    # Son gözlem gününe göre kaç gün geride. Hiç verisi yoksa None.
    gun_farki: int | None
    bagli_id_sayisi: int

    @property
    def hic_veri_yok(self) -> bool:
        return self.son_veri is None

    def ozet(self) -> str:
        if self.hic_veri_yok:
            return f"{self.etiket}: hiç fiyat gözlemi yok"
        return (
            f"{self.etiket}: son veri {self.son_veri.strftime('%d.%m.%Y')} "
            f"({self.gun_farki} gün geride, {self.bagli_id_sayisi} bağlı ID)"
        )


def bayat_kalemler(
    db: Session,
    *,
    settings: Settings | None = None,
    esik_gun: int | None = None,
) -> list[BayatKalem]:
    """Eşik kadar gün geride kalan aktif takip kalemleri. En geride olan başta.

    Hiç fiyat gözlemi olmayan kalemler eşikten bağımsız olarak listelenir:
    onlar için "kaç gün geride" sorusunun anlamı yok, doğrudan bozuk demektir.
    """
    settings = settings or get_settings()
    esik = settings.stale_item_days if esik_gun is None else esik_gun

    son_gozlem = db.scalar(select(func.max(PriceHistory.collected_date)))
    if son_gozlem is None:
        return []  # Hiç toplama yapılmamış; söylenecek bir şey yok.

    satirlar = db.execute(
        select(
            WatchlistItem.id,
            WatchlistItem.label,
            func.max(PriceHistory.collected_date),
            func.count(func.distinct(WatchlistSourceId.source_product_id)),
        )
        .join(WatchlistSourceId, WatchlistSourceId.watchlist_item_id == WatchlistItem.id)
        .join(
            Product,
            Product.source_product_id == WatchlistSourceId.source_product_id,
            isouter=True,
        )
        .join(PriceHistory, PriceHistory.product_id == Product.id, isouter=True)
        .where(WatchlistItem.active.is_(True))
        .group_by(WatchlistItem.id, WatchlistItem.label)
    ).all()

    bulunan: list[BayatKalem] = []
    for kalem_id, etiket, son_veri, bagli in satirlar:
        if son_veri is None:
            bulunan.append(BayatKalem(kalem_id, etiket, None, None, bagli))
            continue
        fark = (son_gozlem - son_veri).days
        if fark >= esik:
            bulunan.append(BayatKalem(kalem_id, etiket, son_veri, fark, bagli))

    # Hiç verisi olmayanlar en başa; sonra en geride olan.
    return sorted(
        bulunan,
        key=lambda b: (0 if b.hic_veri_yok else 1, -(b.gun_farki or 0)),
    )
