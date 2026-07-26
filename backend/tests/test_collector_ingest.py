"""Collector + price_ingest testleri — ağa çıkmadan, sahte istemciyle.

İzolasyon: dış transaction + rollback (servisler kendi içinde commit çağırıyor).

Buradaki asıl soru "API ne döndürüyor" değil: ham veri dokunulmadan yazılıyor mu,
418'de duruluyor mu, aynı gün iki koşuda kayıt katlanıyor mu, para Decimal kalıyor mu.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors.market_fiyati import MarketFiyatiCollector
from app.collectors.market_fiyati_client import WafBlockedError
from app.config import get_settings
from app.database.session import engine
from app.models import (
    Depot,
    Market,
    PriceHistory,
    Product,
    RawRecord,
    WatchlistItem,
    WatchlistSourceId,
)
from app.services.price_ingest import ham_kayitlari_isle
from app.utils.tarih import yerel_bugun

BUGUN = date(2026, 7, 26)


@pytest.fixture
def db():
    baglanti = engine.connect()
    dis_islem = baglanti.begin()
    oturum = Session(bind=baglanti, join_transaction_mode="create_savepoint")
    try:
        yield oturum
    finally:
        oturum.close()
        dis_islem.rollback()
        baglanti.close()


@pytest.fixture
def ortam(db):
    """İki markette birer depo + takip listesinde tek ürün.

    Gerçek takip listesi (seed.py ile yüklenen ~76 kalem) bu transaction içinde
    pasife alınır — yoksa collector onları da çeker ve testin saydığı sayılar
    gerçek veriye bağımlı hale gelir. İşlem sonunda geri sarılır.
    """
    db.query(WatchlistItem).update({WatchlistItem.active: False},
                                   synchronize_session=False)
    db.flush()

    sok = db.scalar(select(Market).where(Market.slug == "sok"))
    if sok is None:
        sok = Market(slug="sok", name="ŞOK")
        db.add(sok)
    a101 = db.scalar(select(Market).where(Market.slug == "a101"))
    if a101 is None:
        a101 = Market(slug="a101", name="A101")
        db.add(a101)
    db.flush()

    db.add_all([
        Depot(id="t-sok-1", market_id=sok.id, name="Örnek 1", active=True),
        Depot(id="t-a101-1", market_id=a101.id, name="Örnek 2", active=True),
    ])
    urun = Product(source_product_id="TC01", title="Test Ürün 250 Ml",
                   brand="TestMarka", refined_volume_or_weight="250 ML")
    db.add(urun)
    db.flush()

    kalem = WatchlistItem(label="Test Ürün")
    db.add(kalem)
    db.flush()
    db.add(WatchlistSourceId(watchlist_item_id=kalem.id, source_product_id="TC01"))
    db.flush()
    return {"kalem": kalem, "urun": urun}


def _yanit(fiyat_sok: str, fiyat_a101: str) -> dict[str, Any]:
    return {
        "content": [{
            "id": "TC01",
            "title": "Test Ürün 250 Ml",
            "brand": "TestMarka",
            "refinedVolumeOrWeight": "250 ML",
            "productDepotInfoList": [
                {
                    "depotId": "t-sok-1", "marketAdi": "sok",
                    "price": Decimal(fiyat_sok), "percentage": Decimal("0"),
                    "unitPrice": "238,00 ₺/Lt", "unitPriceValue": Decimal("238.0"),
                    "indexTime": "26.07.2026 12:00",
                },
                {
                    "depotId": "t-a101-1", "marketAdi": "a101",
                    "price": Decimal(fiyat_a101), "percentage": Decimal("17.647058"),
                    "discountlessPrice": Decimal("80.00"),
                    "indexTime": "26.07.2026 12:00",
                },
            ],
        }]
    }


class SahteIstemci:
    def __init__(self, yanit: Any, hata: Exception | None = None) -> None:
        self._yanit = yanit
        self._hata = hata
        self.cagrilar: list[str] = []
        self.kapatildi = False

    def search_by_identity(self, identity, depots, latitude, longitude,
                           distance_km, identity_type="id"):
        self.cagrilar.append(identity)
        if self._hata:
            raise self._hata
        return self._yanit

    def close(self) -> None:
        self.kapatildi = True


# --- toplama -------------------------------------------------------------


def test_ham_veri_degistirilmeden_yaziliyor(db, ortam) -> None:
    """Anayasa md. 3: raw_records dokunulmamış veri taşır."""
    api = SahteIstemci(_yanit("59.50", "70.00"))
    sonuc = MarketFiyatiCollector(api=api, settings=get_settings()).topla(db)

    assert sonuc.basarili == 1
    kayit = db.scalar(select(RawRecord).where(RawRecord.source_product_id == "TC01"))
    assert kayit is not None
    assert kayit.processed is False

    # Fiyat metinde Decimal sadakatiyle durmalı — float'a düşmemeli.
    assert '"59.50"' in kayit.raw_json
    geri = json.loads(kayit.raw_json, parse_float=Decimal)
    assert geri["content"][0]["productDepotInfoList"][0]["price"] == "59.50"


def test_yalniz_takip_listesindekiler_cekiliyor(db, ortam) -> None:
    """Listede olmayan ürün toplanmaz."""
    db.add(Product(source_product_id="TC99", title="Listede Olmayan"))
    db.flush()

    api = SahteIstemci(_yanit("59.50", "70.00"))
    MarketFiyatiCollector(api=api, settings=get_settings()).topla(db)
    assert api.cagrilar == ["TC01"]


def test_418_gorulunce_derhal_duruluyor(db, ortam) -> None:
    """Anayasa md. 12: WAF bloğunda kalan ürünler DENENMEZ (IP banı riski)."""
    api = SahteIstemci(None, hata=WafBlockedError("HTTP 418"))
    sonuc = MarketFiyatiCollector(api=api, settings=get_settings()).topla(db)

    assert sonuc.durduruldu is True
    assert "418" in (sonuc.durma_nedeni or "")
    assert sonuc.basarili == 0


def test_depo_yoksa_toplama_baslamiyor(db, ortam) -> None:
    """Konumsuz toplama yanlış şehirden veri demek — sessizce yapılmaz."""
    db.query(Depot).update({Depot.active: False}, synchronize_session=False)
    db.flush()

    api = SahteIstemci(_yanit("59.50", "70.00"))
    sonuc = MarketFiyatiCollector(api=api, settings=get_settings()).topla(db)

    assert sonuc.durduruldu is True
    assert "depo" in (sonuc.durma_nedeni or "").lower()
    assert api.cagrilar == []


def test_bos_yanit_hata_sayilmiyor(db, ortam) -> None:
    api = SahteIstemci({"content": []})
    sonuc = MarketFiyatiCollector(api=api, settings=get_settings()).topla(db)
    assert sonuc.bos_donen == 1
    assert sonuc.hatali == 0


# --- işleme --------------------------------------------------------------


def test_fiyatlar_price_historye_yaziliyor(db, ortam) -> None:
    api = SahteIstemci(_yanit("59.50", "70.00"))
    MarketFiyatiCollector(api=api, settings=get_settings()).topla(db)
    sonuc = ham_kayitlari_isle(db, gun=BUGUN)

    assert sonuc.islenen_kayit == 1
    assert sonuc.yazilan_fiyat == 2

    kayitlar = list(db.scalars(
        select(PriceHistory).where(PriceHistory.product_id == ortam["urun"].id)
    ))
    assert len(kayitlar) == 2
    fiyatlar = {k.depot_id: k.price for k in kayitlar}
    assert fiyatlar["t-sok-1"] == Decimal("59.50")
    assert all(isinstance(f, Decimal) for f in fiyatlar.values())


def test_yan_alanlar_da_yaziliyor(db, ortam) -> None:
    api = SahteIstemci(_yanit("59.50", "70.00"))
    MarketFiyatiCollector(api=api, settings=get_settings()).topla(db)
    ham_kayitlari_isle(db, gun=BUGUN)

    a101 = db.scalar(select(PriceHistory).where(PriceHistory.depot_id == "t-a101-1"))
    assert a101.discountless_price == Decimal("80.00")
    # Ham hassasiyet korunmalı (site %17,6 gösterir, API 17.647058 döner).
    assert a101.percentage == Decimal("17.647058")
    assert a101.index_time is not None and a101.index_time.year == 2026


def test_islenen_kayit_tekrar_islenmiyor(db, ortam) -> None:
    api = SahteIstemci(_yanit("59.50", "70.00"))
    MarketFiyatiCollector(api=api, settings=get_settings()).topla(db)
    ham_kayitlari_isle(db, gun=BUGUN)

    ikinci = ham_kayitlari_isle(db, gun=BUGUN)
    assert ikinci.islenen_kayit == 0


def test_ayni_gun_iki_kosu_kaydi_katlamiyor(db, ortam) -> None:
    """Faz 1 kabul kriteri: pipeline iki kez çalışınca kayıt katlanmaz."""
    for _ in range(2):
        api = SahteIstemci(_yanit("59.50", "70.00"))
        MarketFiyatiCollector(api=api, settings=get_settings()).topla(db)
        ham_kayitlari_isle(db, gun=BUGUN)

    adet = db.scalar(
        select(func.count(PriceHistory.id)).where(
            PriceHistory.product_id == ortam["urun"].id
        )
    )
    assert adet == 2, "aynı gün ikinci koşu kayıt katlamamalı"


def test_ayni_gun_fiyat_degisirse_guncelleniyor(db, ortam) -> None:
    api = SahteIstemci(_yanit("59.50", "70.00"))
    MarketFiyatiCollector(api=api, settings=get_settings()).topla(db)
    ham_kayitlari_isle(db, gun=BUGUN)

    api2 = SahteIstemci(_yanit("55.00", "70.00"))
    MarketFiyatiCollector(api=api2, settings=get_settings()).topla(db)
    sonuc = ham_kayitlari_isle(db, gun=BUGUN)

    assert sonuc.guncellenen_fiyat == 2
    guncel = db.scalar(select(PriceHistory).where(PriceHistory.depot_id == "t-sok-1"))
    assert guncel.price == Decimal("55.00")


def test_farkli_gun_zaman_serisi_birikiyor(db, ortam) -> None:
    api = SahteIstemci(_yanit("59.50", "70.00"))
    MarketFiyatiCollector(api=api, settings=get_settings()).topla(db)
    ham_kayitlari_isle(db, gun=date(2026, 7, 25))

    api2 = SahteIstemci(_yanit("55.00", "70.00"))
    MarketFiyatiCollector(api=api2, settings=get_settings()).topla(db)
    ham_kayitlari_isle(db, gun=date(2026, 7, 26))

    adet = db.scalar(
        select(func.count(PriceHistory.id)).where(
            PriceHistory.product_id == ortam["urun"].id
        )
    )
    assert adet == 4  # 2 depo × 2 gün


def test_bilinmeyen_depo_atlaniyor(db, ortam) -> None:
    """Gönderdiğimiz liste dışından gelen depo yabancı anahtarı kırmamalı."""
    yanit = _yanit("59.50", "70.00")
    yanit["content"][0]["productDepotInfoList"].append({
        "depotId": "bilinmeyen-9999", "marketAdi": "sok",
        "price": Decimal("10.00"), "indexTime": "26.07.2026 12:00",
    })
    api = SahteIstemci(yanit)
    MarketFiyatiCollector(api=api, settings=get_settings()).topla(db)
    sonuc = ham_kayitlari_isle(db, gun=BUGUN)

    assert sonuc.atlanan_depo == 1
    assert sonuc.yazilan_fiyat == 2


def test_normalize_alanlari_urune_yaziliyor(db, ortam) -> None:
    api = SahteIstemci(_yanit("59.50", "70.00"))
    MarketFiyatiCollector(api=api, settings=get_settings()).topla(db)
    ham_kayitlari_isle(db, gun=BUGUN)

    db.refresh(ortam["urun"])
    assert ortam["urun"].quantity == Decimal("250")
    assert ortam["urun"].unit == "ML"


def test_gun_index_timedan_turuyor(db, ortam) -> None:
    """`gun` verilmezse kayıt, platformun indekslediği güne yazılır.

    Gece geç saatte çekilen veri çekim gününe yazılsaydı, aynı indeks iki
    ayrı günmüş gibi sayılır ve uydurma bir gözlem üretilirdi.
    """
    api = SahteIstemci(_yanit("59.50", "70.00"))
    MarketFiyatiCollector(api=api, settings=get_settings()).topla(db)
    ham_kayitlari_isle(db)  # gun VERİLMEDİ

    kayitlar = list(db.scalars(
        select(PriceHistory).where(PriceHistory.product_id == ortam["urun"].id)
    ))
    assert kayitlar
    # Sahte yanıttaki indexTime: "26.07.2026 12:00"
    assert all(k.collected_date == date(2026, 7, 26) for k in kayitlar)


def test_index_time_yoksa_yerel_gune_yaziliyor(db, ortam) -> None:
    yanit = _yanit("59.50", "70.00")
    for depo in yanit["content"][0]["productDepotInfoList"]:
        depo.pop("indexTime", None)

    api = SahteIstemci(yanit)
    MarketFiyatiCollector(api=api, settings=get_settings()).topla(db)
    ham_kayitlari_isle(db)

    kayit = db.scalar(
        select(PriceHistory).where(PriceHistory.product_id == ortam["urun"].id)
    )
    assert kayit.collected_date == yerel_bugun()


def test_bozuk_ham_kayit_pipelineyi_durdurmuyor(db, ortam) -> None:
    """Bir kaydın hatası diğerlerini engellememeli; hata kayıtta saklanır."""
    db.add(RawRecord(source="market_fiyati", source_product_id="TC01",
                     raw_json="{bozuk json", processed=False))
    db.flush()

    api = SahteIstemci(_yanit("59.50", "70.00"))
    MarketFiyatiCollector(api=api, settings=get_settings()).topla(db)
    sonuc = ham_kayitlari_isle(db, gun=BUGUN)

    assert sonuc.hatali_kayit == 1
    assert sonuc.yazilan_fiyat == 2  # sağlam kayıt yine de işlendi
    bozuk = db.scalar(
        select(RawRecord).where(RawRecord.raw_json == "{bozuk json")
    )
    assert bozuk.processed is True and bozuk.process_error
