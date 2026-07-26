"""Normalizer testleri — DB ve ağ gerektirmez."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from app.services.normalizer import (
    gramaj_ayristir,
    index_time_ayristir,
    paket_adedi,
    para,
    turkce_kucult,
)


# --- Türkçe küçültme -----------------------------------------------------


def test_buyuk_i_dogru_kuculuyor() -> None:
    """`"İ".lower()` İngilizce yerelinde bozuk sonuç verir (bkz. Gotchas)."""
    assert turkce_kucult("İÇİM") == "içim"
    assert turkce_kucult("PINAR") == "pınar"
    assert turkce_kucult("Işık") == "ışık"


def test_ayni_urun_farkli_yazimla_esitleniyor() -> None:
    assert turkce_kucult("İçim Süt") == turkce_kucult("İÇİM SÜT")


# --- gramaj --------------------------------------------------------------


@pytest.mark.parametrize(
    ("refined", "beklenen_miktar", "beklenen_birim"),
    [
        ("250 ML", Decimal("250"), "ML"),
        ("1 LT", Decimal("1"), "LT"),
        ("5 KG", Decimal("5"), "KG"),
        ("500 GR", Decimal("500"), "GR"),
        ("1.08 LT", Decimal("1.08"), "LT"),
        ("4.5 KG", Decimal("4.5"), "KG"),
        ("1,5 KG", Decimal("1.5"), "KG"),
    ],
)
def test_gramaj_ayristiriliyor(refined, beklenen_miktar, beklenen_birim) -> None:
    g = gramaj_ayristir(refined)
    assert g.quantity == beklenen_miktar
    assert g.unit == beklenen_birim
    assert g.gecerli


def test_ayristirilamayan_gramaj_none_doner() -> None:
    """Sıfır veya 1 varsayılmaz — belirsizlik uydurulmaz (anayasa md. 11)."""
    g = gramaj_ayristir("belirsiz")
    assert g.quantity is None
    assert g.unit is None
    assert not g.gecerli


def test_gramaj_yoksa_cokmez() -> None:
    assert not gramaj_ayristir(None).gecerli


def test_miktar_decimal_kaliyor() -> None:
    assert isinstance(gramaj_ayristir("1.08 LT").quantity, Decimal)


# --- paket adedi ---------------------------------------------------------


@pytest.mark.parametrize(
    ("baslik", "beklenen"),
    [
        ("Red Bull Enerji İçeceği 4 x 250 ML", 4),
        ("Sütaş Sade Süt 6x180 Ml", 6),
        ("Selpak Pamuk Katkılı Tuvalet Kağıdı 32 Adet", 32),
        ("Carrefour Eco Planet Tuvalet Kağıdı 32'li", 32),
        ("Bambu Softy 3 Katlı Kağıt Havlu 12 Adet", 12),
    ],
)
def test_paket_adedi_bulunuyor(baslik, beklenen) -> None:
    assert paket_adedi(baslik) == beklenen


def test_paket_adedi_yoksa_none() -> None:
    """1 VARSAYILMAZ: "32 Adet" ile adetsiz kayıt aynı sayılırsa farklı
    ürünler eşleşir (anayasa md. 9)."""
    assert paket_adedi("Pınar Süt 1 Lt") is None


# --- indexTime -----------------------------------------------------------


def test_index_time_ayristiriliyor() -> None:
    assert index_time_ayristir("26.07.2026 12:00") == datetime(2026, 7, 26, 12, 0)


def test_bozuk_index_time_none_doner() -> None:
    """Uydurma tarih yazmaktansa boş bırakılır."""
    assert index_time_ayristir("dün") is None
    assert index_time_ayristir(None) is None


# --- para ----------------------------------------------------------------


def test_decimal_korunuyor() -> None:
    assert para(Decimal("59.50")) == Decimal("59.50")


def test_metin_decimale_cevriliyor() -> None:
    assert para("59,50") == Decimal("59.50")
    assert para("59.50") == Decimal("59.50")


def test_float_reddediliyor() -> None:
    """float gelmesi, JSON'un parse_float=Decimal ile ayrıştırılmadığını gösterir."""
    with pytest.raises(TypeError, match="float"):
        para(59.5)


def test_bos_deger_none() -> None:
    assert para(None) is None
    assert para("abc") is None
