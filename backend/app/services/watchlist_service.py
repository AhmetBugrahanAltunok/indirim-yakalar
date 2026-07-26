"""Takip listesi iş mantığı.

İki katman (26.07.2026 dedup bulgusu):
    kalem (`WatchlistItem`)  =  kullanıcının kafasındaki ürün
      └─ 1..N kaynak (`WatchlistSourceId`)  =  platformdaki karşılıkları

Mükerrer aday önerisi burada YALNIZ ÖNERİDİR — bağlama kararını kullanıcı verir.
Otomatik birleştirme yapılmaz: yanlış birleştirme iki farklı ürünün fiyatını
karıştırır ve bu hatayı fark etmek zordur.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.collectors.market_fiyati_client import MarketFiyatiClient
from app.config import Settings, get_settings
from app.models import Product, WatchlistItem, WatchlistSourceId
from app.services.depot_resolver import aktif_depo_idleri
from app.services.product_catalog import urun_kaydet


class WatchlistError(RuntimeError):
    """Takip listesi işlemi yapılamadı."""


@dataclass(frozen=True)
class AramaAdayi:
    source_product_id: str
    title: str
    brand: str | None
    refined_volume_or_weight: str | None
    image_url: str | None
    market_sayisi: int
    en_dusuk_fiyat: Any | None
    zaten_takipte: bool
    bagli_kalem_id: int | None


# --- arama (listeye eklenecek ürünü bulmak için) -------------------------


def urun_ara(
    db: Session,
    keywords: str,
    api: MarketFiyatiClient | None = None,
    settings: Settings | None = None,
    sayfa: int = 0,
) -> list[AramaAdayi]:
    """Platformda kelimeyle arar; bulunanları `products`'a yazar ve aday döner.

    ⚠️ `/search` sonuç kümesi günden güne değişir — bu bir envanter aracı değil,
    "eklemek istediğim ürünü bul" aracıdır. Takip her zaman ID üzerinden yapılır.
    """
    settings = settings or get_settings()
    depolar = aktif_depo_idleri(db)
    if not depolar:
        raise WatchlistError(
            "Aktif depo yok. Önce POST /depots/refresh ile konumu çözün; "
            "depo listesi olmadan fiyatlar yanlış şehirden gelir."
        )

    kendi_istemcimiz = api is None
    if api is None:
        api = MarketFiyatiClient(
            base_url=settings.marketfiyati_base_url,
            delay_sec=settings.collector_request_delay_sec,
        )
    try:
        yanit = api.search(
            keywords=keywords,
            depots=depolar,
            latitude=settings.location_lat,
            longitude=settings.location_lon,
            distance_km=settings.location_distance_km,
            page=sayfa,
        )
    finally:
        if kendi_istemcimiz:
            api.close()

    kayitlar = yanit.get("content") or []
    adaylar: list[AramaAdayi] = []

    for kayit in kayitlar:
        urun = urun_kaydet(db, kayit)
        depo_bilgi = kayit.get("productDepotInfoList") or []
        fiyatlar = [d["price"] for d in depo_bilgi if d.get("price") is not None]
        bag = db.scalar(
            select(WatchlistSourceId).where(
                WatchlistSourceId.source_product_id == urun.source_product_id
            )
        )
        adaylar.append(AramaAdayi(
            source_product_id=urun.source_product_id,
            title=urun.title,
            brand=urun.brand,
            refined_volume_or_weight=urun.refined_volume_or_weight,
            image_url=urun.image_url,
            market_sayisi=len({d.get("marketAdi") for d in depo_bilgi}),
            en_dusuk_fiyat=min(fiyatlar) if fiyatlar else None,
            zaten_takipte=bag is not None,
            bagli_kalem_id=bag.watchlist_item_id if bag else None,
        ))

    db.commit()
    return adaylar


# --- kalem yönetimi ------------------------------------------------------


def kalemleri_listele(db: Session, yalniz_aktif: bool = True) -> list[WatchlistItem]:
    sorgu = (
        select(WatchlistItem)
        .options(selectinload(WatchlistItem.sources))
        .order_by(WatchlistItem.added_at)
    )
    if yalniz_aktif:
        sorgu = sorgu.where(WatchlistItem.active.is_(True))
    return list(db.scalars(sorgu))


def kalem_ekle(
    db: Session,
    label: str | None,
    source_product_ids: list[str],
    note: str | None = None,
    onaylayan: str = "user",
) -> WatchlistItem:
    """Yeni takip kalemi açar ve verilen platform ID'lerini bağlar.

    `label` verilmezse ilk ürünün platformdaki adı kullanılır.
    """
    if not source_product_ids:
        raise WatchlistError("En az bir platform ürün ID'si gerekli.")

    urunler = _urunleri_getir(db, source_product_ids)
    kalem = WatchlistItem(label=label or urunler[0].title, note=note)
    db.add(kalem)
    db.flush()

    for urun in urunler:
        _bagla(db, kalem, urun, onaylayan)

    db.commit()
    db.refresh(kalem)
    return kalem


def kaynak_bagla(
    db: Session, kalem_id: int, source_product_id: str, onaylayan: str = "user"
) -> WatchlistItem:
    """Var olan bir kaleme ikinci (mükerrer) platform kaydını bağlar."""
    kalem = db.get(WatchlistItem, kalem_id)
    if kalem is None:
        raise WatchlistError(f"Takip kalemi bulunamadı: {kalem_id}")
    urun = _urunleri_getir(db, [source_product_id])[0]
    _bagla(db, kalem, urun, onaylayan)
    db.commit()
    db.refresh(kalem)
    return kalem


def kaynak_cikar(db: Session, kalem_id: int, source_product_id: str) -> WatchlistItem:
    kalem = db.get(WatchlistItem, kalem_id)
    if kalem is None:
        raise WatchlistError(f"Takip kalemi bulunamadı: {kalem_id}")

    bag = db.scalar(
        select(WatchlistSourceId).where(
            WatchlistSourceId.watchlist_item_id == kalem_id,
            WatchlistSourceId.source_product_id == source_product_id,
        )
    )
    if bag is None:
        raise WatchlistError(f"{source_product_id} bu kaleme bağlı değil.")
    if len(kalem.sources) <= 1:
        raise WatchlistError(
            "Kalemin son kaynağı çıkarılamaz — kaynaksız kalem toplanamaz. "
            "Kalemi tamamen silmek istiyorsanız kalemi silin."
        )

    db.delete(bag)
    db.commit()
    db.refresh(kalem)
    return kalem


def kalem_sil(db: Session, kalem_id: int) -> None:
    """Kalemi ve bağlantılarını siler. Fiyat geçmişi SİLİNMEZ (ürüne bağlı)."""
    kalem = db.get(WatchlistItem, kalem_id)
    if kalem is None:
        raise WatchlistError(f"Takip kalemi bulunamadı: {kalem_id}")
    db.delete(kalem)
    db.commit()


# --- mükerrer aday önerisi ----------------------------------------------


def _turkce_kucult(metin: str) -> str:
    """Türkçe-güvenli küçültme: `casefold()` öncesi I→ı, İ→i (bkz. Gotchas)."""
    return metin.replace("I", "ı").replace("İ", "i").casefold()


_BIRIMLER = {
    "gr", "g", "kg", "lt", "l", "ml", "cl", "adet", "li", "lı", "lu", "lü", "x",
}


def _sayi_mi(kelime: str) -> bool:
    return bool(kelime) and all(k in "0123456789.,%" for k in kelime)


def _ayirt_edici_kelimeler(urun: Product) -> set[str]:
    """Başlıktan marka ve gramajı çıkarıp geriye kalan anlamlı kelimeler.

    "Muratbey Tam Yağlı Taze Kaşar Peyniri 500 Gr" → {tam, yağlı, taze, kaşar, peyniri}
    Marka ve gramaj zaten ayrı alanlarda eşleştiği için ayırt edici değiller.

    ⚠️ Marka yalnız BAŞTAN ayrılır, alt dize olarak silinmez: "Red Bull Red
    Edition"dan marka alt dize sayılsaydı ikinci "Red" de silinir, ürün
    "Blue Edition"ın alt kümesi görünürdü.
    """
    baslik = _turkce_kucult(urun.title or "").strip()
    marka = _turkce_kucult(urun.brand or "").strip()
    if marka and baslik.startswith(marka):
        baslik = baslik[len(marka):]

    kelimeler = set()
    for ham in baslik.split():
        k = ham.strip("'’\"()[]{}.,;:")
        if not k or k in _BIRIMLER or _sayi_mi(k):
            continue
        kelimeler.add(k)
    return kelimeler


def _mukerrer_olabilir(a: Product, b: Product) -> bool:
    """İki katalog kaydı aynı fiziksel ürün olabilir mi?

    Marka + gramaj eşitliği tek başına YETMİYOR (26.07.2026 gözlemi): aynı
    markanın aynı gramajda farklı ürünleri var — "Mis Tam Yağlı Kaşar" ile
    "Mis Yarım Yağlı Süzme Beyaz Peynir" ikisi de [Mis / 500 GR].

    Ek şart: birinin ayırt edici kelimeleri diğerinin ALT KÜMESİ olmalı.
    Platform mükerrer kaydı genelde "uzun ad" ⊃ "kısa ad" biçiminde tutuyor
    ("Blue Edition" ⊂ "Blue Edition Enerji İçeceği"). Farklı ürünlerde ise
    her iki tarafta da diğerinde olmayan kelime bulunur (rize ⟷ harman).
    """
    ka, kb = _ayirt_edici_kelimeler(a), _ayirt_edici_kelimeler(b)
    if not ka or not kb:
        return False
    return ka <= kb or kb <= ka


def mukerrer_adaylari(db: Session, kalem_id: int) -> list[Product]:
    """Bu kalemle aynı ürün OLABİLECEK, henüz bağlanmamış platform kayıtları.

    İki aşamalı: (1) aynı `brand` + aynı `refined_volume_or_weight`,
    (2) başlıkların ayırt edici kelimeleri alt küme ilişkisinde.
    Tek başına (1) çok gevşek — 77 kalemlik gerçek listede 27 aday üretti,
    çoğu yanlıştı (kaşar ⟷ beyaz peynir gibi).

    Bu bir ÖNERİDİR; bağlama kararı kullanıcınındır.
    """
    kalem = db.get(WatchlistItem, kalem_id)
    if kalem is None:
        raise WatchlistError(f"Takip kalemi bulunamadı: {kalem_id}")

    bagli_idler = [s.source_product_id for s in kalem.sources]
    if not bagli_idler:
        return []

    bagli_urunler = list(
        db.scalars(select(Product).where(Product.source_product_id.in_(bagli_idler)))
    )

    adaylar: dict[str, Product] = {}
    for kaynak in bagli_urunler:
        if not kaynak.brand or not kaynak.refined_volume_or_weight:
            continue  # imza eksikse öneri üretme — tahmin yapmıyoruz
        bulunan = db.scalars(
            select(Product).where(
                Product.brand == kaynak.brand,
                Product.refined_volume_or_weight == kaynak.refined_volume_or_weight,
                Product.source_product_id.notin_(bagli_idler),
            )
        )
        for urun in bulunan:
            if _mukerrer_olabilir(kaynak, urun):
                adaylar[urun.source_product_id] = urun

    # Başka bir kaleme bağlı olanları önerme.
    bagli_baskasinda = set(db.scalars(select(WatchlistSourceId.source_product_id)))
    return [u for spid, u in adaylar.items() if spid not in bagli_baskasinda]


# --- iç yardımcılar ------------------------------------------------------


def _urunleri_getir(db: Session, source_product_ids: list[str]) -> list[Product]:
    urunler = {
        u.source_product_id: u
        for u in db.scalars(
            select(Product).where(Product.source_product_id.in_(source_product_ids))
        )
    }
    eksik = [s for s in source_product_ids if s not in urunler]
    if eksik:
        raise WatchlistError(
            f"Bu ürünler katalogda yok: {', '.join(eksik)}. "
            "Önce GET /search ile aratın (arama sonuçları katalogla kaydedilir)."
        )
    return [urunler[s] for s in source_product_ids]


def _bagla(
    db: Session, kalem: WatchlistItem, urun: Product, onaylayan: str
) -> WatchlistSourceId:
    mevcut = db.scalar(
        select(WatchlistSourceId).where(
            WatchlistSourceId.source_product_id == urun.source_product_id
        )
    )
    if mevcut is not None:
        if mevcut.watchlist_item_id == kalem.id:
            return mevcut
        raise WatchlistError(
            f"{urun.source_product_id} zaten {mevcut.watchlist_item_id} numaralı "
            "kaleme bağlı. Bir platform ürünü tek kaleme ait olabilir "
            "(yoksa fiyatı iki kez sayılır)."
        )

    bag = WatchlistSourceId(
        watchlist_item_id=kalem.id,
        source_product_id=urun.source_product_id,
        title_snapshot=urun.title,
        link_confirmed_by=onaylayan,
    )
    db.add(bag)
    db.flush()
    return bag
