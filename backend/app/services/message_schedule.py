"""Mesaj günü kararı: veri her gün toplanır, mesaj N günde bir üretilir.

Ayrım bilinçli. Fiyat geçmişi ne kadar sıksa o kadar değerli — kaçan gün geri
gelmiyor (bkz. [[Gotchas]]). Ama alıcıya her gün mesaj gitmesi gereksiz;
proje sahibi 3 günde bir istedi (29.07.2026).

Karar takvimden değil **durumdan** okunur: "ayın günü 3'e bölünüyorsa" gibi bir
kural, makine iki gün kapalı kalınca mesajı sessizce atlardı. Bunun yerine son
mesaj tarihi saklanır ve üzerinden N gün geçtiyse yeni mesaj üretilir.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.config import Settings, get_settings
from app.services.message_export import mesaj_dizini
from app.utils.tarih import yerel_bugun

logger = logging.getLogger(__name__)

DURUM_DOSYASI = "mesaj-takvimi.json"


@dataclass(frozen=True)
class MesajKarari:
    uretilecek: bool
    neden: str
    # Düşüşlerin kıyaslanacağı gün: son mesajın gözlem günü. İlk mesajda None
    # (kıyas için elde bir taban yok, analyzer bir önceki gözleme düşer).
    taban_gun: date | None
    # Son mesajın üretildiği gün — aralık bundan sayılır.
    son_uretim_gunu: date | None


def _durum_yolu(settings: Settings) -> Path:
    return mesaj_dizini(settings) / DURUM_DOSYASI


def _durum_oku(settings: Settings, alan: str) -> date | None:
    yol = _durum_yolu(settings)
    if not yol.exists():
        return None
    try:
        ham = json.loads(yol.read_text(encoding="utf-8")).get(alan)
        return date.fromisoformat(ham) if ham else None
    except (json.JSONDecodeError, OSError, ValueError):
        # Bozuk durum dosyası mesajı kalıcı olarak durdurmamalı: en kötü
        # ihtimalle bir mesaj erken gider.
        logger.warning("Mesaj takvimi okunamadı, sıfırdan sayılıyor: %s", yol)
        return None


def son_mesaj_gunu(settings: Settings | None = None) -> date | None:
    """Son mesajın dayandığı GÖZLEM günü — bir sonraki kıyasın tabanı."""
    return _durum_oku(settings or get_settings(), "son_mesaj_gunu")


def son_uretim_gunu(settings: Settings | None = None) -> date | None:
    """Son mesajın ÜRETİLDİĞİ gün — aralık sayacı bunu kullanır.

    Gözlem gününden ayrı tutuluyor: ikisi bir gün kayabiliyor (mesaj 29'unda
    üretilir ama verisi 28'inindir). Sayaç gözlem gününü kullansaydı mesajlar
    arası süre istenenden kısa olurdu.
    """
    return _durum_oku(settings or get_settings(), "uretildigi_gun")


def mesaj_gunu_mu(
    settings: Settings | None = None,
    *,
    gun: date | None = None,
    zorla: bool = False,
) -> MesajKarari:
    """Bugün mesaj üretilmeli mi?"""
    settings = settings or get_settings()
    gun = gun or yerel_bugun()
    aralik = max(1, settings.message_interval_days)

    # Taban = son mesajın GÖZLEM günü (kıyas için).
    # Sayaç = son mesajın ÜRETİM günü (aralık için). İkisi bir gün kayabilir.
    taban = son_mesaj_gunu(settings)
    uretim = son_uretim_gunu(settings) or taban

    if zorla:
        return MesajKarari(True, "elle zorlandı", taban, uretim)

    if uretim is None:
        return MesajKarari(True, "ilk mesaj", None, None)

    gecen = (gun - uretim).days

    if gecen < 0:
        # Sistem saati geri alınmış ya da durum dosyası gelecekten. Kilitli
        # kalmaktansa üret; tarih mesajda zaten yazıyor.
        return MesajKarari(True, "durum dosyası gelecekte, sıfırlanıyor", taban, uretim)

    if gecen >= aralik:
        return MesajKarari(
            True, f"son mesajdan {gecen} gün geçti (aralık {aralik})", taban, uretim
        )

    return MesajKarari(
        False,
        f"son mesajdan {gecen} gün geçti, {aralik} gün gerekiyor "
        f"({aralik - gecen} gün sonra)",
        taban,
        uretim,
    )


def mesaj_uretildi(
    gozlem_gunu: date, settings: Settings | None = None, *, gun: date | None = None
) -> None:
    """Mesaj üretildiğini kaydeder.

    `gozlem_gunu` saklanır çünkü bir sonraki mesajın kıyas tabanı budur:
    "son mesajda gördüğün fiyatlara göre ne değişti". Üretim tarihi değil,
    verinin ait olduğu gün doğru tabandır — mesaj bir gün gecikirse kıyas
    kaymasın.
    """
    settings = settings or get_settings()
    gun = gun or yerel_bugun()

    yol = _durum_yolu(settings)
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(
        json.dumps(
            {
                "son_mesaj_gunu": gozlem_gunu.isoformat(),
                "uretildigi_gun": gun.isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("Mesaj takvimi güncellendi: taban %s", gozlem_gunu)
