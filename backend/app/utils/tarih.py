"""Tarih yardımcıları.

⚠️ Bu projede "gün" **yerel gündür**, UTC günü değil. Proje sahibi UTC+3'te;
UTC kullanılsaydı gün sınırı gece 03:00'te döner ve 00:00-03:00 arasındaki bir
koşu bir önceki güne yazılır, ertesi gün de o günün verisinin üstüne binerdi.
Zaman serisi bozulur ve bu SESSİZCE olur.
"""

from __future__ import annotations

from datetime import date, datetime


def yerel_bugun() -> date:
    """Sistemin yerel takvim günü."""
    return datetime.now().date()


def gozlem_gunu(index_time: datetime | None) -> date:
    """Bir fiyat gözleminin ait olduğu gün.

    Öncelik platformun `indexTime` alanındadır: fiyat, platformun o günkü
    indekslemesine aittir. Gece geç saatte çekilen veri, indekslendiği güne
    yazılır — böylece aynı indeks iki ayrı günmüş gibi sayılmaz (uydurma
    gözlem üretilmez, bkz. anayasa md. 11).

    `indexTime` yoksa yerel güne düşülür.
    """
    return index_time.date() if index_time is not None else yerel_bugun()
