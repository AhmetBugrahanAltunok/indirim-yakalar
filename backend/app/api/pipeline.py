"""Pipeline tetikleme ve durum uçları.

`POST /pipeline/run/market-fiyati` gerçek API'ye ~80 istek atar (istekler arası
bekleme istemcide) — birkaç dakika sürer. WAF bloğu görülürse 503 döner ve
kalan ürünler DENENMEZ.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import scheduler
from app.database.session import get_db
from app.models import PriceHistory, RawRecord, WatchlistItem, WatchlistSourceId
from app.services.pipeline_runner import bugun_toplandi_mi, pipeline_calistir

router = APIRouter(tags=["pipeline"], prefix="/pipeline")


class PipelineRunResult(BaseModel):
    kaynak: str
    istenen: int
    basarili: int
    bos_donen: int
    hatali: int
    durduruldu: bool
    durma_nedeni: str | None
    islenen_ham_kayit: int
    yazilan_fiyat: int
    guncellenen_fiyat: int
    ozet: str
    hatalar: list[str] = Field(default_factory=list)


class PipelineStatus(BaseModel):
    takip_kalemi: int
    takip_edilen_platform_id: int
    islenmemis_ham_kayit: int
    toplam_fiyat_kaydi: int
    ilk_gozlem: date | None
    son_gozlem: date | None
    gozlem_gunu: int
    bugun_toplandi: bool
    zamanlayici_acik: bool
    sonraki_kosu: str | None


@router.post("/run/market-fiyati", response_model=PipelineRunResult)
def market_fiyati_calistir(db: Session = Depends(get_db)) -> PipelineRunResult:
    sonuc = pipeline_calistir(db)
    toplama, isleme = sonuc.toplama, sonuc.isleme

    if toplama.durduruldu and toplama.basarili == 0:
        raise HTTPException(
            status_code=503,
            detail=toplama.durma_nedeni or "Toplama başlatılamadı.",
        )

    return PipelineRunResult(
        kaynak=toplama.kaynak,
        istenen=toplama.istenen,
        basarili=toplama.basarili,
        bos_donen=toplama.bos_donen,
        hatali=toplama.hatali,
        durduruldu=toplama.durduruldu,
        durma_nedeni=toplama.durma_nedeni,
        islenen_ham_kayit=isleme.islenen_kayit,
        yazilan_fiyat=isleme.yazilan_fiyat,
        guncellenen_fiyat=isleme.guncellenen_fiyat,
        ozet=f"{toplama.ozet()} | {isleme.ozet()}",
        hatalar=(toplama.hatalar + isleme.hatalar)[:20],
    )


@router.get("/status", response_model=PipelineStatus)
def durum(db: Session = Depends(get_db)) -> PipelineStatus:
    gunler = db.execute(
        select(
            func.min(PriceHistory.collected_date),
            func.max(PriceHistory.collected_date),
            func.count(func.distinct(PriceHistory.collected_date)),
        )
    ).one()
    zamanlayici = scheduler.durum()

    return PipelineStatus(
        bugun_toplandi=bugun_toplandi_mi(db),
        zamanlayici_acik=zamanlayici["acik"],
        sonraki_kosu=zamanlayici["sonraki_kosu"],
        takip_kalemi=db.scalar(
            select(func.count(WatchlistItem.id)).where(WatchlistItem.active.is_(True))
        ) or 0,
        takip_edilen_platform_id=db.scalar(
            select(func.count(WatchlistSourceId.id))
        ) or 0,
        islenmemis_ham_kayit=db.scalar(
            select(func.count(RawRecord.id)).where(RawRecord.processed.is_(False))
        ) or 0,
        toplam_fiyat_kaydi=db.scalar(select(func.count(PriceHistory.id))) or 0,
        ilk_gozlem=gunler[0],
        son_gozlem=gunler[1],
        gozlem_gunu=gunler[2] or 0,
    )
