"""Faz 1 şema testleri — kısıtların gerçekten iş gördüğünü kanıtlar.

Bu testler gerçek PostgreSQL'e yazar (DB'siz çalışmazlar) çünkü test edilen şeyler
(bileşik tekillik, CASCADE, NUMERIC hassasiyeti) veritabanı davranışıdır;
SQLite ya da mock ile doğrulanmış sayılmazlar.

Her test kendi verisini benzersiz ön ekle yaratır ve sonunda temizler.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.database.session import SessionLocal
from app.models import (
    Depot,
    Market,
    PriceHistory,
    Product,
    WatchlistItem,
    WatchlistSourceId,
)

ON_EK = "TEST-"


@pytest.fixture
def db():
    oturum = SessionLocal()
    try:
        yield oturum
    finally:
        oturum.rollback()
        # Testin yarattığı her şeyi sil (FK sırasına dikkat).
        oturum.query(PriceHistory).filter(
            PriceHistory.depot_id.like(f"{ON_EK}%")
        ).delete(synchronize_session=False)
        oturum.query(WatchlistSourceId).filter(
            WatchlistSourceId.source_product_id.like(f"{ON_EK}%")
        ).delete(synchronize_session=False)
        oturum.query(WatchlistItem).filter(
            WatchlistItem.label.like(f"{ON_EK}%")
        ).delete(synchronize_session=False)
        oturum.query(Depot).filter(Depot.id.like(f"{ON_EK}%")).delete(
            synchronize_session=False
        )
        oturum.query(Product).filter(
            Product.source_product_id.like(f"{ON_EK}%")
        ).delete(synchronize_session=False)
        oturum.query(Market).filter(Market.slug.like(f"{ON_EK}%")).delete(
            synchronize_session=False
        )
        oturum.commit()
        oturum.close()


def _market(db, slug: str) -> Market:
    m = Market(slug=f"{ON_EK}{slug}", name=slug)
    db.add(m)
    db.flush()
    return m


def _depo(db, market: Market, ek: str) -> Depot:
    d = Depot(id=f"{ON_EK}{ek}", market_id=market.id, name=f"{ek} magaza")
    db.add(d)
    db.flush()
    return d


def _urun(db, spid: str, baslik: str, marka: str = "Red Bull",
          gramaj: str = "250 ML") -> Product:
    p = Product(
        source_product_id=f"{ON_EK}{spid}",
        title=baslik,
        brand=marka,
        refined_volume_or_weight=gramaj,
    )
    db.add(p)
    db.flush()
    return p


def test_fiyat_decimal_olarak_geri_geliyor(db) -> None:
    """Para float'a dönüşmemeli (anayasa md. 1)."""
    m = _market(db, "sok")
    d = _depo(db, m, "sok-1")
    p = _urun(db, "1LMO", "Red Bull Enerji İçeceği 250 Ml")
    db.add(PriceHistory(
        product_id=p.id, depot_id=d.id, market_id=m.id,
        price=Decimal("59.50"), percentage=Decimal("17.647058"),
        collected_date=date(2026, 7, 26),
    ))
    db.commit()

    kayit = db.query(PriceHistory).filter_by(product_id=p.id).one()
    assert isinstance(kayit.price, Decimal)
    assert kayit.price == Decimal("59.50")
    # Ham hassasiyet korunmalı — site %17,6 gösterir ama API 17.647058 döner.
    assert kayit.percentage == Decimal("17.647058")


def test_ayni_gun_ayni_urun_ayni_depo_iki_kez_yazilamaz(db) -> None:
    """Idempotency: pipeline iki kez koşarsa kayıt katlanmaz."""
    m = _market(db, "bim")
    d = _depo(db, m, "bim-1")
    p = _urun(db, "1ZQB", "Red Bull 473 Ml")
    ortak = dict(product_id=p.id, depot_id=d.id, market_id=m.id,
                 collected_date=date(2026, 7, 26))

    db.add(PriceHistory(price=Decimal("70.00"), **ortak))
    db.commit()

    db.add(PriceHistory(price=Decimal("70.00"), **ortak))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_farkli_gun_ayni_urun_yazilabilir(db) -> None:
    """Zaman serisi birikebilmeli — kısıt günü de kapsıyor."""
    m = _market(db, "migros")
    d = _depo(db, m, "migros-1")
    p = _urun(db, "1K1H", "Red Bull 355 Ml")
    ortak = dict(product_id=p.id, depot_id=d.id, market_id=m.id)

    db.add(PriceHistory(price=Decimal("95.00"), collected_date=date(2026, 7, 25), **ortak))
    db.add(PriceHistory(price=Decimal("92.50"), collected_date=date(2026, 7, 26), **ortak))
    db.commit()

    assert db.query(PriceHistory).filter_by(product_id=p.id).count() == 2


def test_takip_kalemi_birden_cok_platform_idsine_baglanir(db) -> None:
    """26.07.2026 dedup bulgusu: aynı ürün iki katalog kaydında olabilir.

    Gerçek örnek — Red Bull Blue Edition 250 ml:
      1TOK -> carrefour 60,00 / migros 70,95   (kendi içinde "en ucuz" 60,00)
      21D5 -> a101 55,00
    İkisi tek kaleme bağlanınca gerçek en ucuz 55,00 çıkmalı.
    """
    carrefour = _market(db, "carrefour")
    a101 = _market(db, "a101")
    d_carrefour = _depo(db, carrefour, "carrefour-0001")
    d_a101 = _depo(db, a101, "a101-0002")

    p_1tok = _urun(db, "1TOK", "Red Bull Blue Edition 250 Ml")
    p_21d5 = _urun(db, "21D5", "Red Bull Blue Edition Enerji İçeceği 250 Ml")

    kalem = WatchlistItem(label=f"{ON_EK}Red Bull Blue Edition 250 ml")
    db.add(kalem)
    db.flush()
    db.add_all([
        WatchlistSourceId(watchlist_item_id=kalem.id,
                          source_product_id=p_1tok.source_product_id,
                          title_snapshot=p_1tok.title, link_confirmed_by="user"),
        WatchlistSourceId(watchlist_item_id=kalem.id,
                          source_product_id=p_21d5.source_product_id,
                          title_snapshot=p_21d5.title, link_confirmed_by="user"),
    ])
    bugun = date(2026, 7, 26)
    db.add_all([
        # 1TOK kendi kaydı içinde en ucuz olduğunu iddia ediyor (percentage 0).
        PriceHistory(product_id=p_1tok.id, depot_id=d_carrefour.id,
                     market_id=carrefour.id, price=Decimal("60.00"),
                     percentage=Decimal("0"), collected_date=bugun),
        PriceHistory(product_id=p_21d5.id, depot_id=d_a101.id,
                     market_id=a101.id, price=Decimal("55.00"),
                     percentage=Decimal("0"), collected_date=bugun),
    ])
    db.commit()

    db.refresh(kalem)
    assert len(kalem.sources) == 2

    # Kalemin TÜM bağlı ID'leri üzerinden en ucuzu bul.
    bagli = [s.source_product_id for s in kalem.sources]
    urun_idleri = [
        r.id for r in db.query(Product).filter(Product.source_product_id.in_(bagli))
    ]
    fiyatlar = db.query(PriceHistory).filter(
        PriceHistory.product_id.in_(urun_idleri),
        PriceHistory.collected_date == bugun,
    ).all()

    en_ucuz = min(f.price for f in fiyatlar)
    assert en_ucuz == Decimal("55.00"), "Dedup çalışmıyor: platformun yanılttığı fiyat kaldı"
    # Platformun percentage'ına güvenilseydi iki kayıt da "0 = en ucuz" diyordu.
    assert sum(1 for f in fiyatlar if f.percentage == Decimal("0")) == 2


def test_ayni_platform_urunu_iki_kaleme_baglanamaz(db) -> None:
    """Bir platform ürünü tek kaleme aittir — yoksa fiyat iki kez sayılır."""
    p = _urun(db, "1LMO2", "Red Bull 250 Ml")
    k1 = WatchlistItem(label=f"{ON_EK}kalem 1")
    k2 = WatchlistItem(label=f"{ON_EK}kalem 2")
    db.add_all([k1, k2])
    db.flush()

    db.add(WatchlistSourceId(watchlist_item_id=k1.id,
                             source_product_id=p.source_product_id))
    db.commit()

    db.add(WatchlistSourceId(watchlist_item_id=k2.id,
                             source_product_id=p.source_product_id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_kalem_silinince_baglantilar_da_silinir(db) -> None:
    """CASCADE: kalem silinince öksüz bağlantı kalmamalı."""
    p = _urun(db, "1Z9X", "Red Bull 4 x 250 ML")
    kalem = WatchlistItem(label=f"{ON_EK}silinecek")
    db.add(kalem)
    db.flush()
    db.add(WatchlistSourceId(watchlist_item_id=kalem.id,
                             source_product_id=p.source_product_id))
    db.commit()
    kalem_id = kalem.id

    db.delete(kalem)
    db.commit()

    kalan = db.query(WatchlistSourceId).filter_by(watchlist_item_id=kalem_id).count()
    assert kalan == 0
    # Ürün kataloğu silinmemeli — geçmiş veri ona bağlı.
    assert db.query(Product).filter_by(source_product_id=p.source_product_id).count() == 1
