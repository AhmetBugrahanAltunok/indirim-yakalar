"""Gün sınırı testleri.

Bu proje UTC+3'te koşuyor. `collected_date` UTC gününden türetilseydi gün sınırı
gece 03:00'te döner; 00:00-03:00 arasındaki bir koşu bir önceki güne yazılır ve
ertesi gün o günün verisinin ÜSTÜNE binerdi. Zaman serisi sessizce bozulurdu.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.utils.tarih import gozlem_gunu, yerel_bugun


def test_yerel_bugun_utc_degil() -> None:
    """Yerel gün, sistem takvimini izler."""
    assert yerel_bugun() == datetime.now().date()


def test_gece_yarisi_sonrasi_utc_yanlis_gunu_verir() -> None:
    """Bug'ın kaynağı: UTC+3'te 01:44 yerelken UTC hâlâ bir önceki gündedir.

    Gerçekten yaşandı — 27.07.2026 01:44 yerel iken UTC 26.07 22:44'tü.
    """
    yerel = datetime(2026, 7, 27, 1, 44, tzinfo=timezone(timedelta(hours=3)))
    assert yerel.date() == date(2026, 7, 27)
    assert yerel.astimezone(timezone.utc).date() == date(2026, 7, 26)


def test_gozlem_gunu_index_timedan_turer() -> None:
    """Fiyat, platformun indekslediği güne aittir — çekildiği saate değil.

    Gerçek durum (27.07.2026 01:38'de yaşandı): veri gece çekildi ama
    platform onu 26.07 12:00'de indekslemişti. Kayıt 26.07'ye yazılmalı,
    yoksa aynı indeks iki ayrı günmüş gibi sayılır.
    """
    assert gozlem_gunu(datetime(2026, 7, 26, 12, 0)) == date(2026, 7, 26)


def test_index_time_yoksa_yerel_gune_dusuluyor() -> None:
    assert gozlem_gunu(None) == yerel_bugun()


def test_ayni_index_iki_gun_sayilmiyor() -> None:
    """Aynı indeks farklı saatlerde çekilse de tek güne yazılır."""
    idx = datetime(2026, 7, 26, 12, 0)
    assert gozlem_gunu(idx) == gozlem_gunu(idx)
