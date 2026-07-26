"""Zamanlayıcı testleri — gerçek zamanlayıcı başlatmadan, ağa çıkmadan.

Asıl soru: kaçırılan koşu telafi ediliyor mu, aynı gün ikinci kez API yorulup
yorulmuyor mu. Bu proje kişisel makinede koştuğu için ikisi de kritik.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import scheduler
from app.config import Settings, get_settings
from app.database.session import engine
from app.models import Depot, Market, PriceHistory, Product
from app.services.pipeline_runner import bugun_toplandi_mi


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


def _fiyat_ekle(db, gun: date) -> None:
    market = db.scalar(select(Market).where(Market.slug == "a101"))
    if market is None:
        market = Market(slug="a101", name="A101")
        db.add(market)
        db.flush()
    depo = Depot(id="t-sch-1", market_id=market.id, name="Örnek", active=True)
    urun = Product(source_product_id="TS01", title="Zamanlayıcı Testi")
    db.add_all([depo, urun])
    db.flush()
    db.add(PriceHistory(
        product_id=urun.id, depot_id=depo.id, market_id=market.id,
        price=10, collected_date=gun,
    ))
    db.flush()


# --- "bugün toplandı mı" -------------------------------------------------


def test_bugun_veri_yoksa_false(db) -> None:
    ileri_gun = date.today() + timedelta(days=400)
    assert bugun_toplandi_mi(db, gun=ileri_gun) is False


def test_bugun_veri_varsa_true(db) -> None:
    ileri_gun = date.today() + timedelta(days=400)
    _fiyat_ekle(db, ileri_gun)
    assert bugun_toplandi_mi(db, gun=ileri_gun) is True


# --- kaçırılan koşu tespiti ---------------------------------------------


def _ayar(saat: int, dakika: int = 0) -> Settings:
    temel = get_settings()
    return temel.model_copy(update={
        "pipeline_schedule_hour": saat,
        "pipeline_schedule_minute": dakika,
    })


def test_planlanan_saat_gectiyse_kacirilmis_sayilir() -> None:
    simdi = datetime.now()
    gecmis_saat = max(0, simdi.hour - 1)
    assert scheduler._kacirilan_kosu_var_mi(_ayar(gecmis_saat)) is True


def test_planlanan_saat_gelmediyse_kacirilmamis() -> None:
    simdi = datetime.now()
    if simdi.hour >= 23:
        pytest.skip("gece yarısına yakın — gelecek saat kurulamıyor")
    assert scheduler._kacirilan_kosu_var_mi(_ayar(simdi.hour + 1)) is False


# --- günlük koşu ---------------------------------------------------------


def test_bugun_toplandiysa_kosu_atlaniyor(monkeypatch) -> None:
    """Aynı gün ikinci kez API yorulmamalı."""
    cagrildi = {"pipeline": False}

    monkeypatch.setattr(scheduler, "bugun_toplandi_mi", lambda db, gun=None: True)
    monkeypatch.setattr(
        scheduler, "pipeline_calistir",
        lambda db, **kw: cagrildi.__setitem__("pipeline", True),
    )
    scheduler.gunluk_kosu()
    assert cagrildi["pipeline"] is False


def test_veri_yoksa_kosu_yapiliyor(monkeypatch) -> None:
    cagrildi = {"pipeline": False}

    class SahteSonuc:
        def ozet(self) -> str:
            return "sahte"

    def sahte_pipeline(db, **kw):
        cagrildi["pipeline"] = True
        return SahteSonuc()

    monkeypatch.setattr(scheduler, "bugun_toplandi_mi", lambda db, gun=None: False)
    monkeypatch.setattr(scheduler, "pipeline_calistir", sahte_pipeline)
    scheduler.gunluk_kosu()
    assert cagrildi["pipeline"] is True


def test_kosu_hatasi_sureci_dusurmuyor(monkeypatch) -> None:
    """Zamanlayıcı işi çökerse uygulama ölmemeli; hata loglanır."""
    def patlat(db, **kw):
        raise RuntimeError("API çöktü")

    monkeypatch.setattr(scheduler, "bugun_toplandi_mi", lambda db, gun=None: False)
    monkeypatch.setattr(scheduler, "pipeline_calistir", patlat)
    scheduler.gunluk_kosu()  # istisna sızmamalı


# --- açılış davranışı ----------------------------------------------------


def test_autostart_kapaliyken_zamanlayici_baslamiyor() -> None:
    """Varsayılan kapalı: uygulamayı açmak gerçek API'ye istek atmamalı."""
    ayar = get_settings().model_copy(update={"pipeline_autostart": False})
    assert scheduler.baslat(ayar) is None
    assert scheduler.durum()["acik"] is False
