"""Takip listesi iş mantığı testleri — ağa çıkmadan.

İzolasyon: dış transaction + rollback (servis kendi içinde commit çağırıyor).

⚠️ Ürün adları/ID'leri gerçek platform ID'leri (Red Bull, herkese açık) —
kişisel veri içermez. Mağaza ID'leri uydurmadır.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.session import engine
from app.models import Depot, Market, Product, WatchlistItem, WatchlistSourceId
from app.services import watchlist_service as ws
from app.services.watchlist_service import WatchlistError


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
def depo(db) -> Depot:
    """Arama için en az bir aktif depo gerekli."""
    market = db.scalar(select(Market).where(Market.slug == "a101"))
    if market is None:
        market = Market(slug="a101", name="A101")
        db.add(market)
        db.flush()
    depo = Depot(id="test-depo-0001", market_id=market.id, name="Örnek Mağaza", active=True)
    db.add(depo)
    db.flush()
    return depo


def _urun(db, spid: str, baslik: str, marka: str = "Red Bull",
          gramaj: str = "250 ML") -> Product:
    urun = Product(source_product_id=spid, title=baslik, brand=marka,
                   refined_volume_or_weight=gramaj)
    db.add(urun)
    db.flush()
    return urun


# --- kalem yönetimi ------------------------------------------------------


def test_kalem_tek_urunle_aciliyor(db) -> None:
    _urun(db, "TT01", "Red Bull Enerji İçeceği 250 Ml")
    kalem = ws.kalem_ekle(db, label=None, source_product_ids=["TT01"])

    assert kalem.label == "Red Bull Enerji İçeceği 250 Ml"  # etiket ürün adından
    assert len(kalem.sources) == 1
    assert kalem.sources[0].title_snapshot == "Red Bull Enerji İçeceği 250 Ml"
    assert kalem.sources[0].link_confirmed_by == "user"


def test_kalem_bastan_iki_kayitla_acilabiliyor(db) -> None:
    """Dedup senaryosu: aynı ürünün iki katalog kaydı tek kaleme bağlanır."""
    _urun(db, "TT02", "Red Bull Blue Edition 250 Ml")
    _urun(db, "TT03", "Red Bull Blue Edition Enerji İçeceği 250 Ml")

    kalem = ws.kalem_ekle(db, label="Red Bull Blue Edition 250 ml",
                          source_product_ids=["TT02", "TT03"])

    assert {s.source_product_id for s in kalem.sources} == {"TT02", "TT03"}


def test_katalogda_olmayan_urun_reddediliyor(db) -> None:
    """Sessizce boş kalem açmaktansa açık hata verilsin."""
    with pytest.raises(WatchlistError, match="katalogda yok"):
        ws.kalem_ekle(db, label=None, source_product_ids=["YOKBOYLE"])


def test_kaynaksiz_kalem_acilamiyor(db) -> None:
    with pytest.raises(WatchlistError):
        ws.kalem_ekle(db, label="boş", source_product_ids=[])


# --- kaynak bağlama ------------------------------------------------------


def test_sonradan_ikinci_kayit_baglanabiliyor(db) -> None:
    _urun(db, "TT02", "Red Bull Blue Edition 250 Ml")
    _urun(db, "TT03", "Red Bull Blue Edition Enerji İçeceği 250 Ml")

    kalem = ws.kalem_ekle(db, label=None, source_product_ids=["TT02"])
    guncel = ws.kaynak_bagla(db, kalem.id, "TT03")

    assert len(guncel.sources) == 2


def test_ayni_urun_iki_kaleme_baglanamiyor(db) -> None:
    """Bağlanırsa fiyatı iki kez sayılır — açık hata verilmeli."""
    _urun(db, "TT01", "Red Bull 250 Ml")
    _urun(db, "TT04", "Red Bull 355 Ml", gramaj="355 ML")

    ws.kalem_ekle(db, label="kalem 1", source_product_ids=["TT01"])
    kalem2 = ws.kalem_ekle(db, label="kalem 2", source_product_ids=["TT04"])

    with pytest.raises(WatchlistError, match="zaten"):
        ws.kaynak_bagla(db, kalem2.id, "TT01")


def test_ayni_kaleme_tekrar_baglamak_zararsiz(db) -> None:
    _urun(db, "TT01", "Red Bull 250 Ml")
    kalem = ws.kalem_ekle(db, label=None, source_product_ids=["TT01"])

    guncel = ws.kaynak_bagla(db, kalem.id, "TT01")
    assert len(guncel.sources) == 1


def test_son_kaynak_cikarilamiyor(db) -> None:
    """Kaynaksız kalem toplanamaz — sessizce işe yaramaz hale gelmesin."""
    _urun(db, "TT01", "Red Bull 250 Ml")
    kalem = ws.kalem_ekle(db, label=None, source_product_ids=["TT01"])

    with pytest.raises(WatchlistError, match="son kaynağı"):
        ws.kaynak_cikar(db, kalem.id, "TT01")


def test_ikiden_biri_cikarilabiliyor(db) -> None:
    _urun(db, "TT02", "Red Bull Blue Edition 250 Ml")
    _urun(db, "TT03", "Red Bull Blue Edition Enerji İçeceği 250 Ml")
    kalem = ws.kalem_ekle(db, label=None, source_product_ids=["TT02", "TT03"])

    guncel = ws.kaynak_cikar(db, kalem.id, "TT03")
    assert {s.source_product_id for s in guncel.sources} == {"TT02"}


def test_kalem_silinince_urun_katalogda_kaliyor(db) -> None:
    """Fiyat geçmişi ürüne bağlı; kalem silmek geçmişi silmemeli."""
    _urun(db, "TT01", "Red Bull 250 Ml")
    kalem = ws.kalem_ekle(db, label=None, source_product_ids=["TT01"])
    ws.kalem_sil(db, kalem.id)

    assert db.scalar(select(Product).where(Product.source_product_id == "TT01")) is not None
    assert db.scalar(
        select(WatchlistSourceId).where(WatchlistSourceId.source_product_id == "TT01")
    ) is None


# --- mükerrer aday önerisi ----------------------------------------------


def test_ayni_marka_gramaj_aday_olarak_oneriliyor(db) -> None:
    _urun(db, "TT02", "Red Bull Blue Edition 250 Ml")
    _urun(db, "TT03", "Red Bull Blue Edition Enerji İçeceği 250 Ml")
    kalem = ws.kalem_ekle(db, label=None, source_product_ids=["TT02"])

    adaylar = ws.mukerrer_adaylari(db, kalem.id)
    assert "TT03" in {a.source_product_id for a in adaylar}


def test_farkli_gramaj_aday_degil(db) -> None:
    """355 ml, 250 ml'nin mükerreri değil — farklı ürün (anayasa md. 7)."""
    _urun(db, "TT01", "Red Bull 250 Ml", gramaj="250 ML")
    _urun(db, "TT04", "Red Bull 355 Ml", gramaj="355 ML")
    kalem = ws.kalem_ekle(db, label=None, source_product_ids=["TT01"])

    adaylar = ws.mukerrer_adaylari(db, kalem.id)
    assert "TT04" not in {a.source_product_id for a in adaylar}


def test_baska_kaleme_bagli_urun_onerilmiyor(db) -> None:
    _urun(db, "TT02", "Red Bull Blue Edition 250 Ml")
    _urun(db, "TT03", "Red Bull Blue Edition Enerji İçeceği 250 Ml")
    kalem1 = ws.kalem_ekle(db, label="kalem 1", source_product_ids=["TT02"])
    ws.kalem_ekle(db, label="kalem 2", source_product_ids=["TT03"])

    adaylar = ws.mukerrer_adaylari(db, kalem1.id)
    assert "TT03" not in {a.source_product_id for a in adaylar}


def test_ayni_marka_gramaj_tek_basina_yetmiyor(db) -> None:
    """Marka+gramaj eşitliği yanlış eşleştirir — başlık benzerliği de şart.

    Gerçek örnek (26.07.2026, 77 kalemlik liste): [Mis / 500 GR] altında hem
    "Mis Tam Yağlı Kaşar Peyniri" hem "Mis Yarım Yağlı Süzme Beyaz Peynir" var.
    Marka+gramaj ölçütü tek başına 27 kalemde aday üretti, çoğu yanlıştı.
    """
    _urun(db, "TT02", "Red Bull Blue Edition 250 Ml")
    # Aynı marka + aynı gramaj, ama farklı ürün: iki tarafta da diğerinde
    # olmayan ayırt edici kelime var (blue/edition ⟷ red/edition).
    _urun(db, "TT05", "Red Bull Red Edition 250 Ml")
    kalem = ws.kalem_ekle(db, label=None, source_product_ids=["TT02"])

    adaylar = ws.mukerrer_adaylari(db, kalem.id)
    assert "TT05" not in {a.source_product_id for a in adaylar}


def test_uzun_ad_kisa_adin_ustkumesi_ise_aday(db) -> None:
    """Platform mükerrer kaydı 'uzun ad ⊃ kısa ad' biçiminde tutuyor."""
    _urun(db, "TT02", "Red Bull Blue Edition 250 Ml")
    _urun(db, "TT03", "Red Bull Blue Edition Enerji İçeceği 250 Ml")
    kalem = ws.kalem_ekle(db, label=None, source_product_ids=["TT02"])

    adaylar = ws.mukerrer_adaylari(db, kalem.id)
    assert "TT03" in {a.source_product_id for a in adaylar}


def test_marka_yoksa_oneri_uretilmiyor(db) -> None:
    """İmza eksikse tahmin yapılmaz — yanlış öneri, yanlış birleştirmeye yol açar."""
    urun = _urun(db, "TT07", "Markasız Ürün")
    urun.brand = None
    db.flush()
    kalem = ws.kalem_ekle(db, label=None, source_product_ids=["TT07"])

    assert ws.mukerrer_adaylari(db, kalem.id) == []


# --- arama ---------------------------------------------------------------


class SahteIstemci:
    def __init__(self, yanit: dict[str, Any]) -> None:
        self._yanit = yanit
        self.gonderilen_depolar: list[str] | None = None

    def search(self, keywords, depots, latitude, longitude, distance_km, page=0, size=24):
        self.gonderilen_depolar = depots
        return self._yanit

    def close(self) -> None:
        pass


_ARAMA_YANITI = {
    "content": [
        {
            "id": "TT01",
            "title": "Red Bull Enerji İçeceği 250 Ml",
            "brand": "Red Bull",
            "refinedVolumeOrWeight": "250 ML",
            "imageUrl": "https://ornek/1lmo.png",
            "productDepotInfoList": [
                {"marketAdi": "sok", "price": Decimal("59.50")},
                {"marketAdi": "migros", "price": Decimal("60.90")},
            ],
        }
    ]
}


def test_arama_urunu_kataloga_yaziyor(db, depo) -> None:
    istemci = SahteIstemci(_ARAMA_YANITI)
    adaylar = ws.urun_ara(db, "red bull", api=istemci)

    assert len(adaylar) == 1
    aday = adaylar[0]
    assert aday.source_product_id == "TT01"
    assert aday.market_sayisi == 2
    assert aday.en_dusuk_fiyat == Decimal("59.50")
    assert aday.zaten_takipte is False

    # katalogda kalıcı olmalı ki sonra listeye eklenebilsin
    assert db.scalar(select(Product).where(Product.source_product_id == "TT01")) is not None


def test_arama_depolari_gonderiyor(db, depo) -> None:
    """depots gönderilmezse fiyatlar yanlış şehirden gelir.

    Kesin listeye bakılmaz (veritabanında gerçek depolar da olabilir);
    önemli olan aktif depoların gönderiliyor olması.
    """
    istemci = SahteIstemci(_ARAMA_YANITI)
    ws.urun_ara(db, "red bull", api=istemci)
    assert istemci.gonderilen_depolar, "depots boş gönderilmiş"
    assert "test-depo-0001" in istemci.gonderilen_depolar


def test_takipteki_urun_isaretleniyor(db, depo) -> None:
    _urun(db, "TT01", "Red Bull Enerji İçeceği 250 Ml")
    kalem = ws.kalem_ekle(db, label=None, source_product_ids=["TT01"])

    adaylar = ws.urun_ara(db, "red bull", api=SahteIstemci(_ARAMA_YANITI))
    assert adaylar[0].zaten_takipte is True
    assert adaylar[0].bagli_kalem_id == kalem.id


def test_depo_yoksa_arama_yapilmiyor(db) -> None:
    """Konum çözülmeden arama, yanlış şehirden sonuç demek."""
    db.query(Depot).update({Depot.active: False}, synchronize_session=False)
    db.flush()
    with pytest.raises(WatchlistError, match="depo"):
        ws.urun_ara(db, "red bull", api=SahteIstemci(_ARAMA_YANITI))
