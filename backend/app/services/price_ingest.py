"""raw_records → normalize → price_history.

Collector'dan ayrı tutuldu: ayrıştırma hatası bulunduğunda kaynağı tekrar
yormadan `raw_records`'tan yeniden üretilebilsin (anayasa md. 3).

Idempotency veritabanı kısıtıyla garanti: `uq_price_history_urun_depo_gun`
(ürün + depo + gün). Aynı gün ikinci koşu INSERT değil UPDATE yapar — pipeline
iki kez çalışırsa kayıt katlanmaz.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import Depot, Market, PriceHistory, Product, RawRecord
from app.services.normalizer import (
    gramaj_ayristir,
    index_time_ayristir,
    para,
)


@dataclass
class IsleneSonucu:
    islenen_kayit: int = 0
    yazilan_fiyat: int = 0
    guncellenen_fiyat: int = 0
    atlanan_depo: int = 0
    hatali_kayit: int = 0
    hatalar: list[str] = field(default_factory=list)

    def ozet(self) -> str:
        return (
            f"{self.islenen_kayit} ham kayıt işlendi · "
            f"{self.yazilan_fiyat} yeni fiyat, {self.guncellenen_fiyat} güncellendi"
            + (f" · {self.atlanan_depo} bilinmeyen depo atlandı" if self.atlanan_depo else "")
            + (f" · {self.hatali_kayit} hata" if self.hatali_kayit else "")
        )


def ham_kayitlari_isle(db: Session, gun: date | None = None) -> IsleneSonucu:
    """İşlenmemiş `raw_records` satırlarını `price_history`'ye aktarır."""
    sonuc = IsleneSonucu()
    gun = gun or datetime.now(timezone.utc).date()

    depo_market = {
        d.id: d.market_id for d in db.scalars(select(Depot))
    }
    market_slug_id = {
        m.slug: m.id for m in db.scalars(select(Market))
    }

    kayitlar = list(
        db.scalars(
            select(RawRecord)
            .where(RawRecord.processed.is_(False))
            .order_by(RawRecord.id)
        )
    )

    for kayit in kayitlar:
        try:
            self_sonuc = _tek_kayit_isle(
                db, kayit, gun, depo_market, market_slug_id
            )
        except Exception as hata:  # noqa: BLE001 — kayıt bazında izole edilir
            kayit.processed = True
            kayit.process_error = f"{type(hata).__name__}: {hata}"
            sonuc.hatali_kayit += 1
            sonuc.hatalar.append(f"raw_record #{kayit.id}: {hata}")
            continue

        kayit.processed = True
        kayit.process_error = None
        sonuc.islenen_kayit += 1
        sonuc.yazilan_fiyat += self_sonuc[0]
        sonuc.guncellenen_fiyat += self_sonuc[1]
        sonuc.atlanan_depo += self_sonuc[2]

    db.commit()
    return sonuc


def _tek_kayit_isle(
    db: Session,
    kayit: RawRecord,
    gun: date,
    depo_market: dict[str, int],
    market_slug_id: dict[str, int],
) -> tuple[int, int, int]:
    """Bir ham kaydı işler. (yeni, güncellenen, atlanan_depo) döner."""
    if not kayit.raw_json:
        return (0, 0, 0)

    # Para float'a düşmesin (anayasa md. 1).
    veri = json.loads(kayit.raw_json, parse_float=Decimal)
    icerik = (veri or {}).get("content") or []

    yeni = guncellenen = atlanan = 0

    for urun_kaydi in icerik:
        urun = _urun_guncelle(db, urun_kaydi)
        if urun is None:
            continue

        for depo_bilgi in urun_kaydi.get("productDepotInfoList") or []:
            depo_id = depo_bilgi.get("depotId")
            if not depo_id or depo_id not in depo_market:
                # Gönderdiğimiz depo listesi dışından bir kayıt: yabancı anahtar
                # kırılmasın diye atlanır, sessizce uydurulmaz.
                atlanan += 1
                continue

            fiyat = para(depo_bilgi.get("price"))
            if fiyat is None:
                continue

            market_id = (
                market_slug_id.get(depo_bilgi.get("marketAdi") or "")
                or depo_market[depo_id]
            )

            eklendi = _fiyat_yaz(
                db,
                product_id=urun.id,
                depot_id=depo_id,
                market_id=market_id,
                gun=gun,
                fiyat=fiyat,
                depo_bilgi=depo_bilgi,
            )
            if eklendi:
                yeni += 1
            else:
                guncellenen += 1

    return (yeni, guncellenen, atlanan)


def _urun_guncelle(db: Session, urun_kaydi: dict[str, Any]) -> Product | None:
    """Ürünü bulur ve normalize alanlarını tazeler. Katalogda yoksa oluşturur."""
    spid = urun_kaydi.get("id")
    if not spid:
        return None

    urun = db.scalar(select(Product).where(Product.source_product_id == spid))
    if urun is None:
        urun = Product(
            source_product_id=spid,
            title=(urun_kaydi.get("title") or spid).strip(),
        )
        db.add(urun)

    baslik = (urun_kaydi.get("title") or urun.title or spid).strip()
    refined = urun_kaydi.get("refinedVolumeOrWeight")

    urun.title = baslik
    urun.brand = (urun_kaydi.get("brand") or None) or urun.brand
    urun.refined_volume_or_weight = refined or urun.refined_volume_or_weight
    urun.image_url = urun_kaydi.get("imageUrl") or urun.image_url
    urun.last_seen_at = datetime.now(timezone.utc)

    gramaj = gramaj_ayristir(urun.refined_volume_or_weight, baslik)
    if gramaj.quantity is not None:
        urun.quantity = gramaj.quantity
    if gramaj.unit:
        urun.unit = gramaj.unit
    if gramaj.package_count is not None:
        urun.package_count = gramaj.package_count

    db.flush()
    return urun


def _fiyat_yaz(
    db: Session,
    *,
    product_id: int,
    depot_id: str,
    market_id: int,
    gun: date,
    fiyat: Decimal,
    depo_bilgi: dict[str, Any],
) -> bool:
    """Fiyatı yazar veya aynı gün varsa günceller. Yeni yazıldıysa True.

    Idempotency: `uq_price_history_urun_depo_gun` üzerinden ON CONFLICT.
    """
    degerler = {
        "product_id": product_id,
        "depot_id": depot_id,
        "market_id": market_id,
        "collected_date": gun,
        "price": fiyat,
        "discountless_price": para(depo_bilgi.get("discountlessPrice")),
        "percentage": para(depo_bilgi.get("percentage")),
        "unit_price_value": para(depo_bilgi.get("unitPriceValue")),
        "unit_price_text": (depo_bilgi.get("unitPrice") or None),
        "index_time": index_time_ayristir(depo_bilgi.get("indexTime")),
    }

    onceki_var = db.scalar(
        select(PriceHistory.id).where(
            PriceHistory.product_id == product_id,
            PriceHistory.depot_id == depot_id,
            PriceHistory.collected_date == gun,
        )
    )

    deyim = pg_insert(PriceHistory).values(**degerler)
    deyim = deyim.on_conflict_do_update(
        constraint="uq_price_history_urun_depo_gun",
        set_={
            "price": deyim.excluded.price,
            "discountless_price": deyim.excluded.discountless_price,
            "percentage": deyim.excluded.percentage,
            "unit_price_value": deyim.excluded.unit_price_value,
            "unit_price_text": deyim.excluded.unit_price_text,
            "index_time": deyim.excluded.index_time,
        },
    )
    db.execute(deyim)
    return onceki_var is None
