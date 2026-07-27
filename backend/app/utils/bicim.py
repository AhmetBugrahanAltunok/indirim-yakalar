"""Kullanıcıya görünen biçimlendirme: tarih GG.AA.YYYY, para 189,00 TL.

Anayasa md. 2. Tek yerde toplandı çünkü bu kural mesajda, panelde ve API
yanıtlarında aynı anda geçerli; üç yerde ayrı yazılsaydı biri bozulurdu.

Python'un `locale` modülü kullanılmıyor: süreç genelinde durum değiştiriyor,
sunucuda hangi locale'in kurulu olduğu garanti değil ve Docker imajında
`tr_TR` üretilmemiş durumda (bkz. docker-compose.yml notu).
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal


def tarih_yaz(gun: date) -> str:
    """27.07.2026"""
    return gun.strftime("%d.%m.%Y")


def para_yaz(tutar: Decimal, *, birim: str = "TL") -> str:
    """189,00 TL · 1.234,56 TL

    Binlik ayıracı nokta, ondalık ayıracı virgül. Kuruş her zaman iki hane —
    "59,5 TL" fiyat gibi durmuyor.
    """
    if not isinstance(tutar, Decimal):
        # Anayasa md. 1: para float'a düşmemeli. Sessizce dönüştürmek yerine
        # çağıranı uyar; buraya float gelmesi zaten bir hatanın belirtisidir.
        raise TypeError(f"Para Decimal olmalı, {type(tutar).__name__} geldi")

    tam, _, kurus = f"{tutar:.2f}".partition(".")
    negatif = tam.startswith("-")
    tam = tam.lstrip("-")

    parcalar = []
    while len(tam) > 3:
        parcalar.insert(0, tam[-3:])
        tam = tam[:-3]
    parcalar.insert(0, tam)

    gosterim = ".".join(parcalar) + "," + kurus
    if negatif:
        gosterim = "-" + gosterim
    return f"{gosterim} {birim}".strip()


def yuzde_yaz(oran: Decimal) -> str:
    """%15 · %8,3 — tam sayıysa ondalık gösterilmez.

    Yuvarlama açıkça HALF_UP: Decimal'in varsayılanı HALF_EVEN (bankacı
    yuvarlaması) ve %8,25'i "%8,2" yapıyor. Gösterimde beklenen "%8,3".
    """
    yuvarlak = oran.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if yuvarlak == yuvarlak.to_integral_value():
        return f"%{int(yuvarlak)}"
    return f"%{yuvarlak}".replace(".", ",")
