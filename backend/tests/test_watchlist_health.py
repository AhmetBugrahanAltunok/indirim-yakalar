"""Kör kalan takip kalemlerinin tespiti.

Bu kontrol, 29-31.07.2026'da gerçekten yaşanan sessiz bir arıza yüzünden var:
`Safya Ayçiçek Yağı 5 L` iki gün boyunca platformdan boş döndü. Toplama başarılı
görünüyordu (WAF bloğu yok, hata yok), yalnız kayıt sayısı birkaç azalmıştı.
Kimse fark etmedi.

Aynı gün `İçim Beyaz Peynir` de boş döndü ama o kalemin ikinci bir bağlı ID'si
olduğu için fiyat akmaya devam etti — bu yüzden `bagli_id_sayisi` de taşınıyor.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.session import engine
from app.models import (
    Depot,
    Market,
    PriceHistory,
    Product,
    WatchlistItem,
    WatchlistSourceId,
)
from app.services.watchlist_health import bayat_kalemler

ONEK = "BK"
GUN = date.today() + timedelta(days=800)


@pytest.fixture
def db():
    baglanti = engine.connect()
    dis_islem = baglanti.begin()
    oturum = Session(bind=baglanti, join_transaction_mode="create_savepoint")
    try:
        oturum.query(WatchlistItem).update({WatchlistItem.active: False})
        oturum.flush()
        yield oturum
    finally:
        oturum.close()
        dis_islem.rollback()
        baglanti.close()


def _market(db, slug: str) -> Market:
    m = db.scalar(select(Market).where(Market.slug == slug))
    if m is None:
        m = Market(slug=slug, name=slug.upper())
        db.add(m)
        db.flush()
    return m


def _kalem(db, etiket: str, spidler: list[str]) -> WatchlistItem:
    kalem = WatchlistItem(label=etiket, active=True)
    db.add(kalem)
    db.flush()
    for spid in spidler:
        db.add(Product(source_product_id=spid, title=f"{etiket} [{spid}]"))
        db.flush()
        db.add(WatchlistSourceId(
            watchlist_item_id=kalem.id, source_product_id=spid,
            link_confirmed_by="test",
        ))
    db.flush()
    return kalem


def _fiyat(db, spid: str, gun: date) -> None:
    market = _market(db, "sok")
    depo_id = f"{ONEK}-sok-1"
    if db.get(Depot, depo_id) is None:
        db.add(Depot(id=depo_id, market_id=market.id, name=depo_id, active=True))
        db.flush()
    urun = db.scalar(select(Product).where(Product.source_product_id == spid))
    db.add(PriceHistory(
        product_id=urun.id, depot_id=depo_id, market_id=market.id,
        price="10.00", collected_date=gun,
    ))
    db.flush()


# --- temel tespit --------------------------------------------------------


def test_guncel_kalem_bayat_sayilmiyor(db) -> None:
    _kalem(db, "Guncel", [f"{ONEK}01"])
    _fiyat(db, f"{ONEK}01", GUN)
    assert [b.etiket for b in bayat_kalemler(db, esik_gun=2)] == []


def test_geride_kalan_kalem_yakalaniyor(db) -> None:
    """Gerçek vaka: Safya Ayçiçek Yağı 2 gün boş döndü."""
    _kalem(db, "Guncel", [f"{ONEK}02"])
    _fiyat(db, f"{ONEK}02", GUN)

    _kalem(db, "Safya benzeri", [f"{ONEK}03"])
    _fiyat(db, f"{ONEK}03", GUN - timedelta(days=2))

    bayatlar = bayat_kalemler(db, esik_gun=2)
    assert [b.etiket for b in bayatlar] == ["Safya benzeri"]
    assert bayatlar[0].gun_farki == 2
    assert bayatlar[0].son_veri == GUN - timedelta(days=2)


def test_esik_altindaki_gecikme_uyarmiyor(db) -> None:
    """Platform bir ürünü tek gün boş döndürebiliyor; her seferinde uyarmak
    gürültü olurdu."""
    _kalem(db, "Guncel", [f"{ONEK}04"])
    _fiyat(db, f"{ONEK}04", GUN)

    _kalem(db, "Bir gun geride", [f"{ONEK}05"])
    _fiyat(db, f"{ONEK}05", GUN - timedelta(days=1))

    assert bayat_kalemler(db, esik_gun=2) == []


def test_esik_ayardan_okunuyor(db) -> None:
    _kalem(db, "Guncel", [f"{ONEK}06"])
    _fiyat(db, f"{ONEK}06", GUN)
    _kalem(db, "Bir gun geride", [f"{ONEK}07"])
    _fiyat(db, f"{ONEK}07", GUN - timedelta(days=1))

    ayar = get_settings().model_copy(update={"stale_item_days": 1})
    assert len(bayat_kalemler(db, settings=ayar)) == 1


# --- hiç verisi olmayanlar ----------------------------------------------


def test_hic_verisi_olmayan_kalem_esikten_bagimsiz_listeleniyor(db) -> None:
    """"Kaç gün geride" sorusunun anlamı yok — doğrudan bozuk demektir."""
    _kalem(db, "Guncel", [f"{ONEK}08"])
    _fiyat(db, f"{ONEK}08", GUN)
    _kalem(db, "Hic verisi yok", [f"{ONEK}09"])

    bayatlar = bayat_kalemler(db, esik_gun=90)
    assert [b.etiket for b in bayatlar] == ["Hic verisi yok"]
    assert bayatlar[0].hic_veri_yok is True
    assert bayatlar[0].gun_farki is None


def test_hic_verisi_olmayanlar_basta(db) -> None:
    _kalem(db, "Guncel", [f"{ONEK}10"])
    _fiyat(db, f"{ONEK}10", GUN)
    _kalem(db, "Cok geride", [f"{ONEK}11"])
    _fiyat(db, f"{ONEK}11", GUN - timedelta(days=10))
    _kalem(db, "Verisiz", [f"{ONEK}12"])

    assert [b.etiket for b in bayat_kalemler(db, esik_gun=2)] == [
        "Verisiz", "Cok geride",
    ]


def test_en_geride_olan_once(db) -> None:
    _kalem(db, "Guncel", [f"{ONEK}13"])
    _fiyat(db, f"{ONEK}13", GUN)
    for i, gecikme in enumerate([3, 9, 5], start=14):
        _kalem(db, f"Gecikme {gecikme}", [f"{ONEK}{i}"])
        _fiyat(db, f"{ONEK}{i}", GUN - timedelta(days=gecikme))

    assert [b.gun_farki for b in bayat_kalemler(db, esik_gun=2)] == [9, 5, 3]


# --- bağlı ID sayısı -----------------------------------------------------


def test_bagli_id_sayisi_tasiniyor(db) -> None:
    """İkinci ID varsa biri düşse de fiyat akabilir — teşhiste fark yaratır."""
    _kalem(db, "Guncel", [f"{ONEK}20"])
    _fiyat(db, f"{ONEK}20", GUN)
    _kalem(db, "Iki idli", [f"{ONEK}21", f"{ONEK}22"])
    _fiyat(db, f"{ONEK}21", GUN - timedelta(days=4))

    bayatlar = bayat_kalemler(db, esik_gun=2)
    assert bayatlar[0].bagli_id_sayisi == 2


def test_ikinci_id_veri_veriyorsa_kalem_bayat_degil(db) -> None:
    """Gerçek vaka: `İçim Beyaz Peynir` boş döndü ama kalem ayakta kaldı —
    mükerrer kayıt birleştirmesinin beklenmedik faydası."""
    _kalem(db, "Iki idli saglam", [f"{ONEK}23", f"{ONEK}24"])
    _fiyat(db, f"{ONEK}23", GUN - timedelta(days=5))  # düşen ID
    _fiyat(db, f"{ONEK}24", GUN)                      # ayakta kalan ID

    assert bayat_kalemler(db, esik_gun=2) == []


# --- kıyas tabanı --------------------------------------------------------


def test_kiyas_bugune_gore_degil_son_gozleme_gore(db) -> None:
    """Platform bir gün indekslemezse (01.08.2026'da oldu) bütün liste bayat
    görünürdü ve uyarı anlamını yitirirdi."""
    eski = GUN - timedelta(days=30)
    _kalem(db, "Hepsi eski 1", [f"{ONEK}30"])
    _fiyat(db, f"{ONEK}30", eski)
    _kalem(db, "Hepsi eski 2", [f"{ONEK}31"])
    _fiyat(db, f"{ONEK}31", eski)

    # İkisi de 30 gün eski ama BİRBİRİNE göre güncel.
    assert bayat_kalemler(db, esik_gun=2) == []


def test_pasif_kalem_uyarmiyor(db) -> None:
    _kalem(db, "Guncel", [f"{ONEK}40"])
    _fiyat(db, f"{ONEK}40", GUN)
    pasif = _kalem(db, "Pasif", [f"{ONEK}41"])
    _fiyat(db, f"{ONEK}41", GUN - timedelta(days=10))
    pasif.active = False
    db.flush()

    assert [b.etiket for b in bayat_kalemler(db, esik_gun=2)] == []


def test_hic_toplama_yoksa_uyari_yok(db) -> None:
    """Sistem yeni kurulmuşken 76 kalemin hepsini uyarı olarak basmak
    kullanıcıyı boğardı."""
    db.query(PriceHistory).delete()
    db.flush()
    _kalem(db, "Yeni kurulum", [f"{ONEK}50"])

    assert bayat_kalemler(db, esik_gun=2) == []


def test_ozet_okunabilir(db) -> None:
    _kalem(db, "Guncel", [f"{ONEK}60"])
    _fiyat(db, f"{ONEK}60", GUN)
    _kalem(db, "Safya Ayçiçek Yağı 5 L", [f"{ONEK}61"])
    _fiyat(db, f"{ONEK}61", GUN - timedelta(days=2))

    ozet = bayat_kalemler(db, esik_gun=2)[0].ozet()
    assert "Safya Ayçiçek Yağı 5 L" in ozet
    assert "2 gün geride" in ozet
