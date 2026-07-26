"""depot_resolver testleri — ağa çıkmadan, sahte API istemcisiyle.

İzolasyon: her test dış bir transaction içinde koşar ve sonunda geri alınır.
`depolari_coz` kendi içinde `commit()` çağırdığı için oturum
`join_transaction_mode="create_savepoint"` ile bağlanır — böylece içerideki
commit'ler savepoint'e dönüşür ve dıştaki rollback her şeyi temizler.

Bu şart: resolver, gelen listede olmayan depoları PASİFE ALIYOR. İzolasyon
olmasaydı testler veritabanındaki gerçek depoları bozardı.

⚠️ Buradaki mağaza adları ve koordinatlar UYDURMADIR. Gerçek değerler proje
sahibinin mahallesini işaret eder ve repo'ya girmez (anayasa md. 5).
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.market_fiyati_client import WafBlockedError
from app.config import Settings, get_settings
from app.database.session import engine
from app.models import Depot, Market, Setting
from app.services.depot_resolver import (
    AYAR_SON_TAZELEME,
    aktif_depo_idleri,
    depolari_coz,
)


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
def ayarlar() -> Settings:
    return get_settings()


def _depo_kaydi(depo_id: str, market: str, ad: str, mesafe: float) -> dict[str, Any]:
    """Gerçek `/nearest` yanıtının BİÇİMİ (26.07.2026'da doğrulandı), uydurma değerlerle."""
    return {
        "id": depo_id,
        "sellerName": ad,
        "marketName": market,
        "location": {"lat": 40.0, "lon": 30.0},
        "distance": mesafe,
    }


class SahteIstemci:
    """`nearest` çağrısını taklit eder; ağa çıkmaz."""

    def __init__(self, kayitlar: list[dict[str, Any]] | Exception) -> None:
        self._kayitlar = kayitlar
        self.cagri_sayisi = 0
        self.kapatildi = False

    def nearest(self, latitude: float, longitude: float, distance_km: int):
        self.cagri_sayisi += 1
        if isinstance(self._kayitlar, Exception):
            raise self._kayitlar
        return self._kayitlar

    def close(self) -> None:
        self.kapatildi = True


ILK_PARTI = [
    _depo_kaydi("test-a101-0001", "a101", "Örnek Mağaza 1", 186.18),
    _depo_kaydi("test-bim-0002", "bim", "Örnek Mağaza 2", 389.35),
    _depo_kaydi("test-sok-0003", "sok", "Örnek Mağaza 3", 575.0),
]


def test_depolar_ve_marketler_yaziliyor(db, ayarlar) -> None:
    sonuc = depolari_coz(db, api=SahteIstemci(ILK_PARTI), settings=ayarlar)

    assert sonuc.toplam == 3
    assert sonuc.yeni_depo == 3
    # `yeni_market` sayısına bakılmaz: zincirler gerçek koşudan zaten var olabilir.
    # Önemli olan marketin var olması ve depoya doğru bağlanması.

    depo = db.get(Depot, "test-a101-0001")
    assert depo is not None
    assert depo.name == "Örnek Mağaza 1"
    assert depo.active is True
    assert float(depo.distance_m) == pytest.approx(186.18)
    assert depo.latitude == pytest.approx(40.0)

    market = db.scalar(select(Market).where(Market.slug == "a101"))
    assert market is not None
    assert market.name == "A101"  # slug değil okunabilir ad


def test_bilinmeyen_zincir_sistemi_durdurmuyor(db, ayarlar) -> None:
    """Platforma yeni bir zincir eklenirse toplama durmamalı; kod ada düşer."""
    parti = [_depo_kaydi("test-yenizincir-1", "test_yeni_zincir", "Yeni Mağaza", 100.0)]
    sonuc = depolari_coz(db, api=SahteIstemci(parti), settings=ayarlar)

    assert sonuc.yeni_market == 1
    market = db.scalar(select(Market).where(Market.slug == "test_yeni_zincir"))
    assert market is not None
    assert market.name == "test_yeni_zincir"  # bilinmeyen kod → kodun kendisi


def test_ikinci_kosu_mukerrer_kayit_uretmiyor(db, ayarlar) -> None:
    depolari_coz(db, api=SahteIstemci(ILK_PARTI), settings=ayarlar)
    ikinci = depolari_coz(db, api=SahteIstemci(ILK_PARTI), settings=ayarlar)

    assert ikinci.yeni_depo == 0
    assert ikinci.guncellenen_depo == 3
    assert ikinci.yeni_market == 0

    kayitlar = list(db.scalars(select(Depot.id).where(Depot.id.like("test-%"))))
    assert len(kayitlar) == 3


def test_menzilden_cikan_depo_silinmiyor_pasife_aliniyor(db, ayarlar) -> None:
    """Geçmiş fiyatlar depoya bağlı — silmek yabancı anahtarı kırardı."""
    depolari_coz(db, api=SahteIstemci(ILK_PARTI), settings=ayarlar)

    eksik_parti = ILK_PARTI[:2]  # üçüncü depo artık gelmiyor
    sonuc = depolari_coz(db, api=SahteIstemci(eksik_parti), settings=ayarlar)

    assert sonuc.pasife_alinan_depo == 1
    dusen = db.get(Depot, "test-sok-0003")
    assert dusen is not None, "depo silinmemeli"
    assert dusen.active is False

    aktifler = aktif_depo_idleri(db)
    assert "test-sok-0003" not in aktifler
    assert "test-a101-0001" in aktifler


def test_geri_donen_depo_tekrar_aktif_oluyor(db, ayarlar) -> None:
    depolari_coz(db, api=SahteIstemci(ILK_PARTI), settings=ayarlar)
    depolari_coz(db, api=SahteIstemci(ILK_PARTI[:2]), settings=ayarlar)
    depolari_coz(db, api=SahteIstemci(ILK_PARTI), settings=ayarlar)

    assert db.get(Depot, "test-sok-0003").active is True


def test_son_tazeleme_ayari_yaziliyor(db, ayarlar) -> None:
    depolari_coz(db, api=SahteIstemci(ILK_PARTI), settings=ayarlar)
    ayar = db.get(Setting, AYAR_SON_TAZELEME)
    assert ayar is not None and ayar.value


def test_waf_blogu_yutulmuyor(db, ayarlar) -> None:
    """418 sessizce geçilmemeli; çağıran durabilmeli."""
    with pytest.raises(WafBlockedError):
        depolari_coz(db, api=SahteIstemci(WafBlockedError("418")), settings=ayarlar)


def test_bozuk_yanit_sessizce_yutulmuyor(db, ayarlar) -> None:
    """Sözleşme değişirse hata versin — yanlış veri yazmaktansa dursun."""
    bozuk = [{"sellerName": "id'siz kayıt", "marketName": "a101"}]
    with pytest.raises(ValueError):
        depolari_coz(db, api=SahteIstemci(bozuk), settings=ayarlar)


def test_disaridan_verilen_istemci_kapatilmiyor(db, ayarlar) -> None:
    """Sahibi kapatır: dışarıdan geçilen istemcinin ömrünü resolver yönetmez."""
    istemci = SahteIstemci(ILK_PARTI)
    depolari_coz(db, api=istemci, settings=ayarlar)
    assert istemci.kapatildi is False
    assert istemci.cagri_sayisi == 1
