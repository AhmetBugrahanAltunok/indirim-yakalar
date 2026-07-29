"""Mesaj takvimi: veri her gün toplanır, mesaj N günde bir üretilir.

Kovalanan asıl hata: mesajın **sessizce atlanması**. Takvim kararı ayın
gününden okunsaydı ("gün % 3 == 0"), makine o gün kapalıysa mesaj hiç
üretilmezdi ve kimse fark etmezdi. Karar durumdan okunuyor; testler makinenin
günlerce kapalı kaldığı senaryoları da içeriyor.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.config import Settings, get_settings
from app.services.message_schedule import (
    mesaj_gunu_mu,
    mesaj_uretildi,
    son_mesaj_gunu,
)

GUN = date(2026, 7, 29)


def _ayar(tmp_path: Path, aralik: int = 3) -> Settings:
    return get_settings().model_copy(update={
        "message_dir": str(tmp_path),
        "message_interval_days": aralik,
    })


# --- ilk mesaj -----------------------------------------------------------


def test_hic_mesaj_uretilmemisse_uretilir(tmp_path) -> None:
    karar = mesaj_gunu_mu(_ayar(tmp_path), gun=GUN)
    assert karar.uretilecek is True
    assert karar.taban_gun is None, "ilk mesajda kıyas tabanı yok"


def test_son_mesaj_gunu_bastan_none(tmp_path) -> None:
    assert son_mesaj_gunu(_ayar(tmp_path)) is None


# --- aralık --------------------------------------------------------------


@pytest.mark.parametrize(("gecen", "beklenen"), [
    (0, False),
    (1, False),
    (2, False),
    (3, True),
    (4, True),
    (10, True),
])
def test_aralik_uygulaniyor(tmp_path, gecen, beklenen) -> None:
    ayar = _ayar(tmp_path, aralik=3)
    mesaj_uretildi(GUN - timedelta(days=gecen), ayar, gun=GUN - timedelta(days=gecen))

    assert mesaj_gunu_mu(ayar, gun=GUN).uretilecek is beklenen


def test_aralik_ayardan_okunuyor(tmp_path) -> None:
    ayar = _ayar(tmp_path, aralik=7)
    mesaj_uretildi(GUN - timedelta(days=4), ayar, gun=GUN - timedelta(days=4))
    assert mesaj_gunu_mu(ayar, gun=GUN).uretilecek is False


def test_neden_metni_kalan_gunu_soyluyor(tmp_path) -> None:
    ayar = _ayar(tmp_path, aralik=3)
    mesaj_uretildi(GUN - timedelta(days=1), ayar, gun=GUN - timedelta(days=1))
    assert "2 gün sonra" in mesaj_gunu_mu(ayar, gun=GUN).neden


# --- makine kapalıyken gün atlanması ------------------------------------


def test_makine_gunlerce_kapali_kalsa_da_mesaj_kaybolmuyor(tmp_path) -> None:
    """Takvim ayın gününden okunsaydı bu senaryoda mesaj sessizce atlanırdı."""
    ayar = _ayar(tmp_path, aralik=3)
    mesaj_uretildi(date(2026, 7, 1), ayar, gun=date(2026, 7, 1))

    # Makine 20 gün kapalı kaldı, sonra açıldı.
    karar = mesaj_gunu_mu(ayar, gun=date(2026, 7, 21))
    assert karar.uretilecek is True
    assert karar.taban_gun == date(2026, 7, 1)


def test_ayni_gun_ikinci_kosu_tekrar_uretmiyor(tmp_path) -> None:
    """Günlük koşu iki kez çalışırsa mesaj iki kez üretilmemeli."""
    ayar = _ayar(tmp_path, aralik=3)
    mesaj_uretildi(GUN, ayar, gun=GUN)
    assert mesaj_gunu_mu(ayar, gun=GUN).uretilecek is False


# --- taban günü ----------------------------------------------------------


def test_taban_gun_son_mesajin_gozlem_gunu(tmp_path) -> None:
    """Kıyas "son mesajda gördüğün fiyatlara göre" olmalı."""
    ayar = _ayar(tmp_path, aralik=3)
    gozlem = date(2026, 7, 25)
    # Mesaj 26'sında üretildi ama verisi 25'inindi.
    mesaj_uretildi(gozlem, ayar, gun=date(2026, 7, 26))

    assert mesaj_gunu_mu(ayar, gun=GUN).taban_gun == gozlem


def test_aralik_uretim_gununden_sayiliyor_gozlemden_degil(tmp_path) -> None:
    """Gözlem günü sayaç olsaydı mesajlar arası süre istenenden kısa olurdu.

    Gerçek durum: mesaj 29'unda üretildi, verisi 28'inindi. Sayaç 28'den
    sayarsa sonraki mesaj 31'inde (2 gün sonra) çıkardı; doğrusu 1 Ağustos.
    """
    ayar = _ayar(tmp_path, aralik=3)
    mesaj_uretildi(date(2026, 7, 28), ayar, gun=date(2026, 7, 29))

    assert mesaj_gunu_mu(ayar, gun=date(2026, 7, 31)).uretilecek is False
    assert mesaj_gunu_mu(ayar, gun=date(2026, 8, 1)).uretilecek is True


def test_uretim_tarihi_ile_gozlem_gunu_ayri_saklaniyor(tmp_path) -> None:
    ayar = _ayar(tmp_path, aralik=3)
    mesaj_uretildi(date(2026, 7, 25), ayar, gun=date(2026, 7, 26))

    icerik = json.loads((tmp_path / "mesaj-takvimi.json").read_text(encoding="utf-8"))
    assert icerik["son_mesaj_gunu"] == "2026-07-25"
    assert icerik["uretildigi_gun"] == "2026-07-26"


# --- dayanıklılık --------------------------------------------------------


def test_bozuk_durum_dosyasi_mesaji_durdurmuyor(tmp_path) -> None:
    """Kalıcı olarak susmaktansa bir mesajı erken göndermek yeğdir."""
    ayar = _ayar(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "mesaj-takvimi.json").write_text("{bozuk", encoding="utf-8")

    assert mesaj_gunu_mu(ayar, gun=GUN).uretilecek is True


def test_gelecek_tarihli_durum_kilitlemiyor(tmp_path) -> None:
    """Sistem saati geri alınırsa mesaj sonsuza dek ertelenmemeli."""
    ayar = _ayar(tmp_path, aralik=3)
    mesaj_uretildi(GUN + timedelta(days=30), ayar, gun=GUN + timedelta(days=30))

    assert mesaj_gunu_mu(ayar, gun=GUN).uretilecek is True


def test_sifir_aralik_gunluge_dusuyor(tmp_path) -> None:
    """Yanlış ayar sonsuz döngüye ya da bölme hatasına dönüşmemeli."""
    ayar = _ayar(tmp_path, aralik=0)
    mesaj_uretildi(GUN - timedelta(days=1), ayar, gun=GUN - timedelta(days=1))
    assert mesaj_gunu_mu(ayar, gun=GUN).uretilecek is True


def test_zorla_arali_deliyor(tmp_path) -> None:
    ayar = _ayar(tmp_path, aralik=3)
    mesaj_uretildi(GUN, ayar, gun=GUN)
    assert mesaj_gunu_mu(ayar, gun=GUN, zorla=True).uretilecek is True
