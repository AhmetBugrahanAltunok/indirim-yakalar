"""Biçimlendirme testleri — anayasa md. 2 (tarih GG.AA.YYYY, para 189,00 TL)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.utils.bicim import para_yaz, tarih_yaz, yuzde_yaz


def test_tarih_gg_aa_yyyy() -> None:
    assert tarih_yaz(date(2026, 7, 27)) == "27.07.2026"


def test_tek_haneli_gun_ve_ay_sifirla_doldurulur() -> None:
    assert tarih_yaz(date(2026, 1, 5)) == "05.01.2026"


@pytest.mark.parametrize(("tutar", "beklenen"), [
    ("189", "189,00 TL"),
    ("189.5", "189,50 TL"),
    ("59.50", "59,50 TL"),
    ("0", "0,00 TL"),
    ("1234.56", "1.234,56 TL"),
    ("1234567.89", "1.234.567,89 TL"),
])
def test_para_turkce_yazilir(tutar, beklenen) -> None:
    assert para_yaz(Decimal(tutar)) == beklenen


def test_kurus_her_zaman_iki_hane() -> None:
    """"59,5 TL" fiyat gibi durmuyor."""
    assert para_yaz(Decimal("59.5")).endswith(",50 TL")


def test_negatif_tutar_isaretini_korur() -> None:
    assert para_yaz(Decimal("-12.30")) == "-12,30 TL"


def test_binlik_ayraci_dogru_yerde() -> None:
    assert para_yaz(Decimal("1000")) == "1.000,00 TL"


def test_float_reddediliyor() -> None:
    """Anayasa md. 1: para float'a düşmemeli — sessizce kabul edilmez."""
    with pytest.raises(TypeError):
        para_yaz(189.0)  # type: ignore[arg-type]


def test_birim_degistirilebilir() -> None:
    assert para_yaz(Decimal("5"), birim="") == "5,00"


@pytest.mark.parametrize(("oran", "beklenen"), [
    ("15", "%15"),
    ("15.0", "%15"),
    ("8.3", "%8,3"),
    ("8.25", "%8,3"),
    ("0", "%0"),
])
def test_yuzde_yazimi(oran, beklenen) -> None:
    assert yuzde_yaz(Decimal(oran)) == beklenen
