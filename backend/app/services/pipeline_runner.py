"""Pipeline'ın tek giriş noktası: topla → işle.

API ucu, zamanlayıcı ve elle çalıştırma hep buradan geçer — üç yerde ayrı akış
olsaydı biri güncellenip diğerleri unutulurdu.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import ToplamaSonucu
from app.collectors.market_fiyati import MarketFiyatiCollector
from app.collectors.market_fiyati_client import MarketFiyatiClient
from app.config import Settings, get_settings
from app.models import PriceHistory
from app.services.price_ingest import IsleneSonucu, ham_kayitlari_isle

logger = logging.getLogger(__name__)


@dataclass
class PipelineSonucu:
    toplama: ToplamaSonucu
    isleme: IsleneSonucu

    @property
    def basarili_mi(self) -> bool:
        return self.toplama.basarili > 0

    def ozet(self) -> str:
        return f"{self.toplama.ozet()} | {self.isleme.ozet()}"


def bugun_toplandi_mi(db: Session, gun: date | None = None) -> bool:
    """O gün için `price_history`'de kayıt var mı?

    Zamanlayıcının telafi kararı buna dayanır: makine kapalıyken koşu kaçtıysa
    açılışta tamamlanır, ama aynı gün ikinci kez API yorulmaz.
    """
    gun = gun or datetime.now(timezone.utc).date()
    return db.scalar(
        select(PriceHistory.id).where(PriceHistory.collected_date == gun).limit(1)
    ) is not None


def pipeline_calistir(
    db: Session,
    api: MarketFiyatiClient | None = None,
    settings: Settings | None = None,
    gun: date | None = None,
) -> PipelineSonucu:
    """Toplar, sonra ham kayıtları `price_history`'ye aktarır.

    Toplama yarıda kesilse bile (WAF bloğu) o ana kadar yazılan ham kayıtlar
    işlenir — kısmi veri, veri yokluğundan iyidir.
    """
    settings = settings or get_settings()
    toplama = MarketFiyatiCollector(api=api, settings=settings).topla(db)
    if toplama.durduruldu:
        logger.warning("Toplama durduruldu: %s", toplama.durma_nedeni)
    isleme = ham_kayitlari_isle(db, gun=gun)
    return PipelineSonucu(toplama=toplama, isleme=isleme)
