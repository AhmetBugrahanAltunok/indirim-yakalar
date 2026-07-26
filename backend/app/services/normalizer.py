"""Platform alanlarını ayrıştırır ve doğrular.

Platform `brand` ve `refinedVolumeOrWeight` ("250 ML") alanlarını hazır veriyor,
bu yüzden burada ağır regex ayıklama yok — gelen değer parse edilip doğrulanır.

⚠️ Türkçe küçültme: `casefold()` ÖNCESİ `I→ı, İ→i` dönüşümü zorunlu.
Python'da `"İ".lower()` İngilizce yerelinde `i̇` (i + birleşen nokta) üretir ve
Türkçe ürün adları yanlış eşleşir (bkz. Obsidian → Gotchas).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# Platformun kullandığı birimler → kanonik biçim.
_BIRIM_ESLEME = {
    "ML": "ML", "MILILITRE": "ML",
    "LT": "LT", "L": "LT", "LITRE": "LT",
    "GR": "GR", "G": "GR", "GRAM": "GR",
    "KG": "KG", "KILOGRAM": "KG",
    "ADET": "ADET", "AD": "ADET",
    "CL": "CL",
    "M": "M", "METRE": "M",
}

# "250 ML", "1.08 LT", "1,5 KG"
_GRAMAJ = re.compile(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*([A-Za-zİIŞĞÜÖÇşğüöçı]+)\s*$")

# Başlıktaki çoklu paket kalıpları: "6x180 Ml", "4 x 250 ML", "32'li", "12 Adet"
_CARPIM = re.compile(r"(?<![0-9])([0-9]{1,3})\s*[xX]\s*([0-9]+(?:[.,][0-9]+)?)")
_LI_EKI = re.compile(r"(?<![0-9])([0-9]{1,3})\s*['’]?\s*(?:li|lı|lu|lü)\b", re.IGNORECASE)
_ADET = re.compile(r"(?<![0-9])([0-9]{1,3})\s*adet\b", re.IGNORECASE)


def turkce_kucult(metin: str) -> str:
    """Türkçe-güvenli küçültme. `casefold()` öncesi I→ı, İ→i."""
    return metin.replace("I", "ı").replace("İ", "i").casefold()


@dataclass(frozen=True)
class Gramaj:
    """Ayrıştırılmış miktar bilgisi. Anayasa md. 9: kimliğin belirleyici parçası."""

    quantity: Decimal | None
    unit: str | None
    package_count: int | None

    @property
    def gecerli(self) -> bool:
        return self.quantity is not None and self.unit is not None


def gramaj_ayristir(refined: str | None, title: str | None = None) -> Gramaj:
    """`refinedVolumeOrWeight` + başlıktan miktar/birim/paket adedini çıkarır.

    Platform gramajı ayrı alanda veriyor; paket adedi ise yalnız başlıkta geçiyor
    ("Red Bull Enerji İçeceği 4 x 250 ML", "Selpak ... 32 Adet").

    Ayrıştırılamayan değer sessizce 0 sayılmaz — `None` döner ve çağıran karar verir.
    """
    quantity: Decimal | None = None
    unit: str | None = None

    if refined:
        eslesme = _GRAMAJ.match(refined)
        if eslesme:
            ham_sayi, ham_birim = eslesme.groups()
            try:
                quantity = Decimal(ham_sayi.replace(",", "."))
            except InvalidOperation:
                quantity = None
            unit = _BIRIM_ESLEME.get(ham_birim.upper())

    return Gramaj(
        quantity=quantity,
        unit=unit,
        package_count=paket_adedi(title) if title else None,
    )


def paket_adedi(title: str) -> int | None:
    """Başlıktan paket adedini çıkarır; bulunamazsa None (1 VARSAYILMAZ).

    1 varsaymak yanlış olurdu: "32 Adet" ile adet bilgisi olmayan bir kayıt
    aynı sayılır ve farklı ürünler eşleşirdi (anayasa md. 9).
    """
    if not title:
        return None
    for kalip in (_CARPIM, _LI_EKI, _ADET):
        eslesme = kalip.search(title)
        if eslesme:
            try:
                sayi = int(eslesme.group(1))
            except ValueError:
                continue
            if 1 < sayi <= 999:  # "1'li" anlamsız, 999 üstü kalıp hatası
                return sayi
    return None


def index_time_ayristir(ham: str | None) -> "datetime | None":  # noqa: F821
    """Platformun `indexTime` alanı: `GG.AA.YYYY SS:DD` → datetime.

    Ayrıştırılamazsa None döner — uydurma tarih yazmaktansa boş bırakılır
    (anayasa md. 11).
    """
    from datetime import datetime

    if not ham or not isinstance(ham, str):
        return None
    for bicim in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(ham.strip(), bicim)
        except ValueError:
            continue
    return None


def para(deger: object) -> Decimal | None:
    """Fiyat değerini Decimal'e çevirir. float ASLA kabul edilmez (anayasa md. 1).

    Collector yanıtı `parse_float=Decimal` ile ayrıştırdığı için buraya Decimal
    gelir. Yine de savunma amaçlı str/int kabul edilir; float gelirse bu, JSON
    ayrıştırmasının yanlış yapıldığı anlamına gelir ve hata verilir.
    """
    if deger is None:
        return None
    if isinstance(deger, Decimal):
        return deger
    if isinstance(deger, bool):
        return None
    if isinstance(deger, int):
        return Decimal(deger)
    if isinstance(deger, str):
        try:
            return Decimal(deger.replace(",", "."))
        except InvalidOperation:
            return None
    if isinstance(deger, float):
        raise TypeError(
            "Fiyat float olarak geldi — JSON `parse_float=Decimal` ile "
            "ayrıştırılmamış. Anayasa md. 1 ihlali."
        )
    return None
