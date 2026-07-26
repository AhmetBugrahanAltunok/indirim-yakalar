"""Market ve depo uçları.

`POST /depots/refresh` gerçek API'ye istek atar — WAF disiplini gereği
elle/periyodik çağrılır, her fiyat toplamada değil.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.market_fiyati_client import MarketFiyatiError, WafBlockedError
from app.database.session import get_db
from app.models import Depot, Market
from app.schemas.depot import DepotOut, DepotRefreshResult, MarketOut
from app.services.depot_resolver import depolari_coz

router = APIRouter(tags=["konum"])


@router.get("/markets", response_model=list[MarketOut])
def market_listesi(db: Session = Depends(get_db)) -> list[Market]:
    return list(db.scalars(select(Market).order_by(Market.slug)))


@router.get("/depots", response_model=list[DepotOut])
def depo_listesi(
    db: Session = Depends(get_db),
    yalniz_aktif: bool = Query(True, description="Menzil dışı depoları gizle"),
) -> list[Depot]:
    sorgu = select(Depot).order_by(Depot.distance_m)
    if yalniz_aktif:
        sorgu = sorgu.where(Depot.active.is_(True))
    return list(db.scalars(sorgu))


@router.post("/depots/refresh", response_model=DepotRefreshResult)
def depolari_tazele(db: Session = Depends(get_db)) -> DepotRefreshResult:
    """Konumu `/nearest` ile yeniden çözer ve depo tablosunu günceller."""
    try:
        sonuc = depolari_coz(db)
    except WafBlockedError as hata:
        # 503: bizim hatamız değil, kaynak bizi engelledi; tekrar denemek zararlı.
        raise HTTPException(status_code=503, detail=str(hata)) from hata
    except MarketFiyatiError as hata:
        raise HTTPException(status_code=502, detail=str(hata)) from hata

    return DepotRefreshResult(
        toplam=sonuc.toplam,
        yeni_depo=sonuc.yeni_depo,
        guncellenen_depo=sonuc.guncellenen_depo,
        pasife_alinan_depo=sonuc.pasife_alinan_depo,
        yeni_market=sonuc.yeni_market,
        ozet=sonuc.ozet(),
    )
