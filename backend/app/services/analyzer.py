"""Takip kalemi analizi: anlık en ucuz + fiyat düşüşü.

İki soruyu yanıtlar:
  1. Bu ürünü bugün en ucuz nereden alırım?
  2. Fiyatı son gözleme göre düştü mü?

Neden kalem düzeyinde: platform aynı fiziksel ürünü zincir başına ayrı katalog
kaydında bırakabiliyor ve her kayıt **kendi içinde** "en ucuz"unu ilan ediyor
(26.07.2026: `1TOK` en ucuz 60,00 derken `21D5` aynı üründe a101 55,00'ti,
ortak depo yok). Bu yüzden en ucuz, kaleme bağlı TÜM `source_product_id`'ler
birleştirilerek hesaplanır; platformun `percentage` alanı tek kayıt içinde
geçerlidir ve tek başına yetki değildir (anayasa md. 7).

Aynı zincirin şubeleri farklı fiyat verebiliyor (`a101-XXXX` 70,00 ⟷
`a101-YYYY` 55,00), bu yüzden zincir düzeyinde **en ucuz şube** alınır. Mesajda
zincir adı yazılır, şube iddiası edilmez.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import (
    Market,
    PriceHistory,
    Product,
    WatchlistItem,
    WatchlistSourceId,
)


@dataclass(frozen=True)
class MarketFiyati:
    """Bir zincirin bu kalem için verdiği en ucuz şube fiyatı."""

    market_id: int
    slug: str
    ad: str
    # Zincirin EN UCUZ şubesinin fiyatı (şubeler arası fark MIN ile eritilir).
    fiyat: Decimal
    # Bu zincirde o gün fiyatı bilinen depo sayısı — hepsi bu fiyatta demek
    # DEĞİL. Yalnız kapsamı görmeye yarar (1 depo mu, 5 depo mu bakılmış).
    depo_sayisi: int


@dataclass(frozen=True)
class DususBilgisi:
    """İki gözlem günü arasındaki değişim.

    ⚠️ Günler **ardışık olmak zorunda değildir**. Pipeline kişisel makinede
    koşuyor; makine kapalıysa gün atlanır. Bu yüzden "dün" değil, gerçek
    tarihler taşınır ve mesaj bunları yazar (SPEC §6.3).
    """

    onceki_gun: date
    onceki_fiyat: Decimal
    son_gun: date
    son_fiyat: Decimal
    onceki_market: str
    son_market: str

    @property
    def fark(self) -> Decimal:
        """Pozitif = ucuzladı."""
        return self.onceki_fiyat - self.son_fiyat

    @property
    def yuzde(self) -> Decimal:
        if self.onceki_fiyat == 0:
            return Decimal("0")
        return (self.fark / self.onceki_fiyat) * Decimal("100")

    @property
    def dustu_mu(self) -> bool:
        return self.fark > 0

    @property
    def market_degisti_mi(self) -> bool:
        """En ucuz zincir değiştiyse düşüş "aynı markette indirim" değildir.

        Mesajın dürüstlüğü buna bağlı: fiyat, A101 pahalılaştığı için değil
        ŞOK listeye girdiği için düşmüş olabilir.
        """
        return self.onceki_market != self.son_market


@dataclass(frozen=True)
class KalemAnalizi:
    kalem_id: int
    etiket: str
    son_gun: date
    market_fiyatlari: list[MarketFiyati]
    dusus: DususBilgisi | None

    @property
    def en_ucuz(self) -> MarketFiyati | None:
        return self.market_fiyatlari[0] if self.market_fiyatlari else None

    @property
    def en_ucuz_marketler(self) -> list[MarketFiyati]:
        """En düşük fiyatı veren zincirlerin TAMAMI.

        Beraberlik gerçek ve sık: 27.07.2026'da Çaykur Rize Turist 1 kg
        A101/BİM/ŞOK'ta aynı anda 365,00'ti. Sıralamadan ilkini alıp tek isim
        yazmak, kullanıcıyı gereksiz yere belli bir markete yönlendirirdi.
        """
        if not self.market_fiyatlari:
            return []
        en_dusuk = self.market_fiyatlari[0].fiyat
        return [m for m in self.market_fiyatlari if m.fiyat == en_dusuk]

    @property
    def beraberlik_var_mi(self) -> bool:
        return len(self.en_ucuz_marketler) > 1

    @property
    def market_sayisi(self) -> int:
        return len(self.market_fiyatlari)

    @property
    def en_ucuz_denebilir_mi(self) -> bool:
        """"En ucuz" demek için gerçek bir kıyas gerekir.

        İki şart: (a) birden fazla marketin fiyatı bilinecek — tek market
        biliniyorsa doğru ifade "Yalnızca X'te" (anayasa md. 7), (b) en az bir
        market daha PAHALI olacak. Hepsi aynı fiyattaysa ortada en ucuz yoktur;
        "en ucuz A101" demek kullanıcıyı boş yere yönlendirirdi.
        """
        if self.market_sayisi <= 1:
            return False
        return self.market_fiyatlari[-1].fiyat > self.market_fiyatlari[0].fiyat

    @property
    def en_pahali_fark(self) -> Decimal | None:
        """En ucuz ile en pahalı arasındaki fark. Tek market varsa None."""
        if not self.en_ucuz_denebilir_mi:
            return None
        return self.market_fiyatlari[-1].fiyat - self.market_fiyatlari[0].fiyat


def kalem_analiz_et(
    db: Session,
    kalem: WatchlistItem,
    *,
    settings: Settings | None = None,
) -> KalemAnalizi | None:
    """Tek kalemi analiz eder. Hiç fiyat gözlemi yoksa None."""
    settings = settings or get_settings()

    gunluk = _gunluk_market_fiyatlari(db, kalem.id)
    if not gunluk:
        return None

    gunler = sorted(gunluk)
    son_gun = gunler[-1]

    market_fiyatlari = sorted(gunluk[son_gun], key=lambda m: (m.fiyat, m.slug))

    dusus = None
    if len(gunler) >= 2:
        # ⚠️ "Bir önceki gün" değil "bir önceki GÖZLEM günü": aradaki boşluk
        # gerçek olabilir ve tarihler mesaja olduğu gibi yazılır (SPEC §6.3).
        onceki_gun = gunler[-2]
        onceki = sorted(gunluk[onceki_gun], key=lambda m: (m.fiyat, m.slug))
        if onceki and market_fiyatlari:
            dusus = DususBilgisi(
                onceki_gun=onceki_gun,
                onceki_fiyat=onceki[0].fiyat,
                son_gun=son_gun,
                son_fiyat=market_fiyatlari[0].fiyat,
                onceki_market=onceki[0].ad,
                son_market=market_fiyatlari[0].ad,
            )

    return KalemAnalizi(
        kalem_id=kalem.id,
        etiket=kalem.label,
        son_gun=son_gun,
        market_fiyatlari=market_fiyatlari,
        dusus=dusus,
    )


def kalem_fiyat_gecmisi(
    db: Session, kalem_id: int
) -> dict[date, list[MarketFiyati]]:
    """Gün → zincir başına en ucuz fiyat. Grafik ve geçmiş ucu için.

    Kaleme bağlı tüm platform ID'leri birleştirilmiş haldedir; bir bağlantı
    sonradan eklenirse geçmiş de o gözden yeniden okunur (fiyat verisi kalem
    düzeyinde değil ürün düzeyinde saklandığı için bu ücretsizdir).
    """
    return _gunluk_market_fiyatlari(db, kalem_id)


def _gunluk_market_fiyatlari(
    db: Session, kalem_id: int
) -> dict[date, list[MarketFiyati]]:
    """Gün → zincir başına EN UCUZ şube fiyatı.

    Kaleme bağlı tüm platform ID'leri tek havuzda toplanır; zincir içindeki
    şube farkı `MIN(price)` ile eritilir.
    """
    satirlar = db.execute(
        select(
            PriceHistory.collected_date,
            Market.id,
            Market.slug,
            Market.name,
            func.min(PriceHistory.price),
            func.count(PriceHistory.depot_id),
        )
        .join(Market, Market.id == PriceHistory.market_id)
        .join(Product, Product.id == PriceHistory.product_id)
        .join(
            WatchlistSourceId,
            WatchlistSourceId.source_product_id == Product.source_product_id,
        )
        .where(WatchlistSourceId.watchlist_item_id == kalem_id)
        .group_by(PriceHistory.collected_date, Market.id, Market.slug, Market.name)
    ).all()

    gunluk: dict[date, list[MarketFiyati]] = {}
    for gun, market_id, slug, ad, fiyat, depo_sayisi in satirlar:
        gunluk.setdefault(gun, []).append(
            MarketFiyati(
                market_id=market_id,
                slug=slug,
                ad=ad,
                fiyat=fiyat,
                depo_sayisi=depo_sayisi,
            )
        )
    return gunluk


def tum_kalemleri_analiz_et(
    db: Session,
    *,
    yalniz_aktif: bool = True,
    settings: Settings | None = None,
) -> list[KalemAnalizi]:
    """Takip listesinin tamamını analiz eder. Gözlemi olmayan kalemler düşer."""
    settings = settings or get_settings()

    sorgu = select(WatchlistItem).order_by(WatchlistItem.id)
    if yalniz_aktif:
        sorgu = sorgu.where(WatchlistItem.active.is_(True))

    sonuclar = []
    for kalem in db.scalars(sorgu):
        analiz = kalem_analiz_et(db, kalem, settings=settings)
        if analiz is not None:
            sonuclar.append(analiz)
    return sonuclar


def dusenler(
    analizler: list[KalemAnalizi], *, settings: Settings | None = None
) -> list[KalemAnalizi]:
    """Eşiği aşan düşüş gösteren kalemler — en çok düşen başta.

    Eşik `.env`'den (`PRICE_DROP_THRESHOLD_PCT`). Eşiğin altındaki oynama
    "indirim" sayılmaz; kuruşluk dalgalanma mesajı çöpe çevirirdi.
    """
    settings = settings or get_settings()
    esik = Decimal(settings.price_drop_threshold_pct)

    secilen = [
        a for a in analizler
        if a.dusus is not None and a.dusus.dustu_mu and a.dusus.yuzde >= esik
    ]
    return sorted(secilen, key=lambda a: a.dusus.yuzde, reverse=True)  # type: ignore[union-attr]
