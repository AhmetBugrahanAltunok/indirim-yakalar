"""Takip listesi ve ürün arama uçları.

`GET /search` gerçek API'ye istek atar (WAF disiplini: istekler arası bekleme
istemcide uygulanır). Diğer uçlar yalnız veritabanıyla çalışır.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.collectors.market_fiyati_client import MarketFiyatiError, WafBlockedError
from app.database.session import get_db
from app.models import WatchlistItem
from app.schemas.watchlist import (
    DuplicateCandidate,
    SearchCandidate,
    WatchlistItemCreate,
    WatchlistItemOut,
    WatchlistSourceAdd,
)
from app.services import watchlist_service
from app.services.watchlist_service import WatchlistError

router = APIRouter(tags=["takip listesi"])


def _hata(exc: WatchlistError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/search", response_model=list[SearchCandidate], tags=["arama"])
def urun_ara(
    q: str = Query(min_length=2, description="Aranacak ürün adı"),
    sayfa: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[SearchCandidate]:
    """Platformda ürün arar. Sonuçlar katalogla kaydedilir, sonra listeye eklenebilir.

    ⚠️ Sonuç kümesi günden güne değişir — envanter aracı değildir.
    """
    try:
        adaylar = watchlist_service.urun_ara(db, keywords=q, sayfa=sayfa)
    except WafBlockedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except MarketFiyatiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except WatchlistError as exc:
        raise _hata(exc) from exc

    return [SearchCandidate(**vars(a)) for a in adaylar]


@router.get("/watchlist", response_model=list[WatchlistItemOut])
def liste(
    yalniz_aktif: bool = Query(True),
    db: Session = Depends(get_db),
) -> list[WatchlistItem]:
    return watchlist_service.kalemleri_listele(db, yalniz_aktif=yalniz_aktif)


@router.post(
    "/watchlist", response_model=WatchlistItemOut, status_code=status.HTTP_201_CREATED
)
def kalem_ekle(
    govde: WatchlistItemCreate, db: Session = Depends(get_db)
) -> WatchlistItem:
    try:
        return watchlist_service.kalem_ekle(
            db,
            label=govde.label,
            source_product_ids=govde.source_product_ids,
            note=govde.note,
        )
    except WatchlistError as exc:
        raise _hata(exc) from exc


@router.delete("/watchlist/{kalem_id}", status_code=status.HTTP_204_NO_CONTENT)
def kalem_sil(kalem_id: int, db: Session = Depends(get_db)) -> None:
    try:
        watchlist_service.kalem_sil(db, kalem_id)
    except WatchlistError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/watchlist/{kalem_id}/sources", response_model=WatchlistItemOut)
def kaynak_bagla(
    kalem_id: int, govde: WatchlistSourceAdd, db: Session = Depends(get_db)
) -> WatchlistItem:
    """Kaleme ikinci bir platform kaydı bağlar (mükerrer katalog kaydı birleştirme)."""
    try:
        return watchlist_service.kaynak_bagla(db, kalem_id, govde.source_product_id)
    except WatchlistError as exc:
        raise _hata(exc) from exc


@router.delete(
    "/watchlist/{kalem_id}/sources/{source_product_id}",
    response_model=WatchlistItemOut,
)
def kaynak_cikar(
    kalem_id: int, source_product_id: str, db: Session = Depends(get_db)
) -> WatchlistItem:
    try:
        return watchlist_service.kaynak_cikar(db, kalem_id, source_product_id)
    except WatchlistError as exc:
        raise _hata(exc) from exc


@router.get(
    "/watchlist/{kalem_id}/duplicate-candidates",
    response_model=list[DuplicateCandidate],
)
def mukerrer_adaylari(kalem_id: int, db: Session = Depends(get_db)):
    """Bu kalemle aynı ürün olabilecek, bağlanmamış kayıtlar. ÖNERİDİR; karar kullanıcının."""
    try:
        return watchlist_service.mukerrer_adaylari(db, kalem_id)
    except WatchlistError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
