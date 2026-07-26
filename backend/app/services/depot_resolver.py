"""Depo çözümleme — konum katmanı.

Sabit koordinat + mesafe, `POST /api/v2/nearest` ile depo ID listesine çevrilir ve
`markets` + `depots` tablolarına yazılır. Bundan sonraki her fiyat çağrısı bu
listeyi `depots` alanında gönderir.

⚠️ Bu adım atlanırsa fiyatlar yanlış şehirden gelir ve bu SESSİZCE olur —
API hata vermez, sadece varsayılan (İstanbul) depolarını döner.

Mağaza listesi sık değişmez (25→26.07.2026 arasında 21 depo sabit kaldı), bu yüzden
her toplama koşusunda değil, periyodik olarak tazelenir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.market_fiyati_client import MarketFiyatiClient
from app.config import Settings, get_settings
from app.models import Depot, Market, Setting

# Zincir kodundan okunabilir ad. Bilinmeyen kod gelirse kodun kendisi kullanılır
# (yeni zincir eklenirse sistem durmasın).
_ZINCIR_ADLARI = {
    "a101": "A101",
    "bim": "BİM",
    "sok": "ŞOK",
    "migros": "Migros",
    "carrefour": "CarrefourSA",
    "tarim_kredi": "Tarım Kredi Kooperatif",
    "hakmar": "Hakmar",
}

AYAR_SON_TAZELEME = "depots_refreshed_at"


@dataclass(frozen=True)
class DepoCozumlemeSonucu:
    toplam: int
    yeni_depo: int
    guncellenen_depo: int
    pasife_alinan_depo: int
    yeni_market: int

    def ozet(self) -> str:
        return (
            f"{self.toplam} depo çözüldü "
            f"(+{self.yeni_depo} yeni, ~{self.guncellenen_depo} güncel, "
            f"-{self.pasife_alinan_depo} pasif, +{self.yeni_market} yeni market)"
        )


def _market_bul_veya_olustur(db: Session, slug: str) -> tuple[Market, bool]:
    market = db.scalar(select(Market).where(Market.slug == slug))
    if market is not None:
        return market, False
    market = Market(slug=slug, name=_ZINCIR_ADLARI.get(slug, slug))
    db.add(market)
    db.flush()
    return market, True


def _kayittan_koordinat(kayit: dict[str, Any]) -> tuple[float | None, float | None]:
    konum = kayit.get("location") or {}
    lat, lon = konum.get("lat"), konum.get("lon")
    return (
        float(lat) if lat is not None else None,
        float(lon) if lon is not None else None,
    )


def depolari_coz(
    db: Session,
    api: MarketFiyatiClient | None = None,
    settings: Settings | None = None,
) -> DepoCozumlemeSonucu:
    """`/nearest` sonucunu `markets` + `depots` tablolarına yazar.

    `api` verilmezse ayarlardan bir istemci kurulur (testte sahte istemci geçilebilir).
    Radyus dışında kalan depolar SİLİNMEZ, `active=False` yapılır — geçmiş fiyat
    kayıtları onlara bağlı ve yabancı anahtar kırılmamalı.
    """
    settings = settings or get_settings()
    kendi_istemcimiz = api is None
    if api is None:
        api = MarketFiyatiClient(
            base_url=settings.marketfiyati_base_url,
            delay_sec=settings.collector_request_delay_sec,
        )

    try:
        kayitlar = api.nearest(
            latitude=settings.location_lat,
            longitude=settings.location_lon,
            distance_km=settings.location_distance_km,
        )
    finally:
        if kendi_istemcimiz:
            api.close()

    yeni_depo = guncellenen = yeni_market = 0
    gelen_idler: set[str] = set()

    for kayit in kayitlar:
        depo_id = kayit.get("id")
        market_slug = kayit.get("marketName")
        if not depo_id or not market_slug:
            # Sözleşme beklenmedik biçimde değişmiş; sessizce yutma.
            raise ValueError(f"/nearest kaydında id/marketName yok: {kayit!r}")

        gelen_idler.add(depo_id)
        market, market_yeni = _market_bul_veya_olustur(db, market_slug)
        yeni_market += int(market_yeni)

        lat, lon = _kayittan_koordinat(kayit)
        mesafe = kayit.get("distance")
        mesafe_m = Decimal(str(mesafe)) if mesafe is not None else None

        depo = db.get(Depot, depo_id)
        if depo is None:
            db.add(Depot(
                id=depo_id,
                market_id=market.id,
                name=kayit.get("sellerName"),
                latitude=lat,
                longitude=lon,
                distance_m=mesafe_m,
                active=True,
            ))
            yeni_depo += 1
        else:
            depo.market_id = market.id
            depo.name = kayit.get("sellerName")
            depo.latitude = lat
            depo.longitude = lon
            depo.distance_m = mesafe_m
            depo.active = True
            depo.refreshed_at = datetime.now(timezone.utc)
            guncellenen += 1

    # Artık menzilde olmayanlar: sil değil, pasife al.
    pasife_alinan = 0
    for depo in db.scalars(select(Depot).where(Depot.active.is_(True))):
        if depo.id not in gelen_idler:
            depo.active = False
            pasife_alinan += 1

    _ayar_yaz(db, AYAR_SON_TAZELEME, datetime.now(timezone.utc).isoformat(),
              "Depo listesinin en son çözüldüğü an (depot_resolver).")
    db.commit()

    return DepoCozumlemeSonucu(
        toplam=len(gelen_idler),
        yeni_depo=yeni_depo,
        guncellenen_depo=guncellenen,
        pasife_alinan_depo=pasife_alinan,
        yeni_market=yeni_market,
    )


def aktif_depo_idleri(db: Session) -> list[str]:
    """Fiyat çağrılarına gönderilecek `depots` listesi.

    Boş dönerse toplama BAŞLATILMAZ — konumsuz çağrı yanlış şehirden veri getirir.
    """
    return list(db.scalars(select(Depot.id).where(Depot.active.is_(True))))


def _ayar_yaz(db: Session, anahtar: str, deger: str, aciklama: str) -> None:
    ayar = db.get(Setting, anahtar)
    if ayar is None:
        db.add(Setting(key=anahtar, value=deger, description=aciklama))
    else:
        ayar.value = deger
