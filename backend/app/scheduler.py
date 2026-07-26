"""Günlük toplama zamanlayıcısı.

Platform günde bir kez indeksliyor (`indexTime` tüm kayıtlarda aynı saat), bu
yüzden günde tek koşu yeterli — daha sık çekmenin faydası yok, WAF açısından
zararı var.

**Telafi mantığı (bu projenin özel şartı):** pipeline kişisel makinede koşuyor,
makine kapalıyken planlanan saat geçebiliyor. Uygulama açıldığında o gün için
veri yoksa VE planlanan saat geçmişse koşu hemen tamamlanır. Aynı gün ikinci
kez çalışmaz — `bugun_toplandi_mi` kontrolü API'yi gereksiz yormayı önler.

Varsayılan olarak KAPALI (`PIPELINE_AUTOSTART=false`): test/geliştirme sırasında
uygulamayı başlatmak gerçek API'ye istek atmamalı. Üretimde `.env`'den açılır.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings, get_settings
from app.database.session import SessionLocal
from app.services.pipeline_runner import bugun_toplandi_mi, pipeline_calistir

logger = logging.getLogger(__name__)

_zamanlayici: BackgroundScheduler | None = None
IS_ADI = "gunluk_market_fiyati"


def gunluk_kosu() -> None:
    """Zamanlayıcının çağırdığı iş. Kendi oturumunu açar ve asla istisna sızdırmaz."""
    db = SessionLocal()
    try:
        if bugun_toplandi_mi(db):
            logger.info("Bugün zaten toplandı, koşu atlandı.")
            return
        sonuc = pipeline_calistir(db)
        logger.info("Günlük koşu: %s", sonuc.ozet())
    except Exception:  # noqa: BLE001 — zamanlayıcı işi çökerse süreç ölmemeli
        logger.exception("Günlük koşu başarısız oldu.")
    finally:
        db.close()


def _kacirilan_kosu_var_mi(settings: Settings) -> bool:
    """Bugünün planlanan saati geçti mi?"""
    simdi = datetime.now()
    planlanan = simdi.replace(
        hour=settings.pipeline_schedule_hour,
        minute=settings.pipeline_schedule_minute,
        second=0,
        microsecond=0,
    )
    return simdi >= planlanan


def _telafi_et() -> None:
    """Açılışta: gün için veri yoksa ve saat geçmişse koşuyu tamamla."""
    settings = get_settings()
    if not _kacirilan_kosu_var_mi(settings):
        return
    db = SessionLocal()
    try:
        if bugun_toplandi_mi(db):
            return
        logger.info("Kaçırılan koşu tespit edildi, telafi ediliyor.")
    finally:
        db.close()
    gunluk_kosu()


def baslat(settings: Settings | None = None) -> BackgroundScheduler | None:
    """Zamanlayıcıyı kurar. Kapalıysa None döner."""
    global _zamanlayici
    settings = settings or get_settings()

    if not settings.pipeline_autostart:
        logger.info("Zamanlayıcı kapalı (PIPELINE_AUTOSTART=false).")
        return None
    if _zamanlayici is not None:
        return _zamanlayici

    # Saat dilimi APScheduler'a bırakılır (tzlocal ile çözer).
    # ⚠️ `datetime.now().astimezone().tzinfo` KULLANILMAZ: Windows'ta yerel
    # Windows adını döner ("Türkiye Standart Saati") ve bu geçerli bir IANA
    # anahtarı olmadığı için ZoneInfoNotFoundError ile açılışta patlar.
    # Gerekirse `.env`'den IANA adıyla (ör. Europe/Istanbul) geçersiz kılınır.
    kwargs = {"timezone": settings.pipeline_timezone} if settings.pipeline_timezone else {}
    _zamanlayici = BackgroundScheduler(**kwargs)
    _zamanlayici.add_job(
        gunluk_kosu,
        trigger=CronTrigger(
            hour=settings.pipeline_schedule_hour,
            minute=settings.pipeline_schedule_minute,
        ),
        id=IS_ADI,
        name="Günlük market fiyatı toplama",
        replace_existing=True,
        # Makine uykudan dönerse saatler sonra bile tetiklenebilsin.
        misfire_grace_time=6 * 60 * 60,
        coalesce=True,  # biriken tetiklemeler tek koşuya indirilir
        max_instances=1,
    )
    _zamanlayici.start()
    logger.info(
        "Zamanlayıcı açık — her gün %02d:%02d",
        settings.pipeline_schedule_hour,
        settings.pipeline_schedule_minute,
    )

    _telafi_et()
    return _zamanlayici


def durdur() -> None:
    global _zamanlayici
    if _zamanlayici is not None:
        _zamanlayici.shutdown(wait=False)
        _zamanlayici = None


def durum() -> dict:
    """Zamanlayıcının canlı durumu — `/pipeline/status` bunu gösterir."""
    if _zamanlayici is None:
        return {"acik": False, "sonraki_kosu": None}
    is_ = _zamanlayici.get_job(IS_ADI)
    return {
        "acik": True,
        "sonraki_kosu": is_.next_run_time.isoformat() if is_ and is_.next_run_time else None,
    }
