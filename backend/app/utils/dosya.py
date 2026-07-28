"""Tarih damgalı üretilmiş dosyaların saklama süresi yönetimi.

Yedekler (`indirim-yakalar-2026-07-29.sql`) ve mesajlar
(`mesaj-2026-07-29-1.txt`) aynı kurala tabi: adında tarih taşırlar, süresi
geçince silinirler. Kural tek yerde tutuluyor — iki ayrı kopya olsaydı biri
düzeltilip diğeri unutulurdu.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

# <önek>YYYY-AA-GG[-sayfa]<uzantı>
_TARIH_DESENI = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-\d+)?$")


def tarihli_dosyalari_temizle(
    dizin: Path, *, onek: str, uzanti: str, gun: date, saklanan_gun: int
) -> list[Path]:
    """Saklama süresini aşan dosyaları siler. Silinenlerin listesini döner.

    ⚠️ Adı desene UYMAYAN dosyaya dokunulmaz. Bizim ürettiğimiz olmayabilir ve
    silmek veri kaybı olur; bu klasörde kullanıcının kendi dosyası da durabilir.
    """
    if not dizin.exists():
        return []

    sinir = gun - timedelta(days=saklanan_gun)
    silinen: list[Path] = []

    for dosya in sorted(dizin.glob(f"{onek}*{uzanti}")):
        eslesme = _TARIH_DESENI.match(dosya.stem[len(onek):])
        if eslesme is None:
            continue
        try:
            dosya_gunu = date.fromisoformat(eslesme.group(1))
        except ValueError:
            continue
        if dosya_gunu < sinir:
            dosya.unlink()
            silinen.append(dosya)

    return silinen
