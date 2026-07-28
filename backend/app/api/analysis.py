"""Karşılaştırma, fiyat geçmişi ve WhatsApp mesajı uçları (Faz 2).

⚠️ Geçmiş ve karşılaştırma **takip kalemi** düzeyindedir, platform ürünü
düzeyinde değil. SPEC §8'de `GET /products/{id}/price-history` yazıyordu; o
liste dedup bulgusundan (26.07.2026) önce yazılmıştı. Aynı fiziksel ürün birden
çok katalog kaydına dağılabildiği için tek kayda bakan geçmiş yanıltıcı olur —
doğru birim kalemdir. Bkz. [[Notlar]] 28.07.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models import WatchlistItem
from app.schemas.analysis import (
    DususOut,
    FiyatGecmisiNoktasi,
    FiyatGecmisiOut,
    KarsilastirmaOut,
    MesajOut,
    MesajYanit,
)
from app.services.analyzer import (
    KalemAnalizi,
    kalem_analiz_et,
    kalem_fiyat_gecmisi,
    tum_kalemleri_analiz_et,
)
from app.services.message_builder import whatsapp_mesajlari

router = APIRouter(tags=["analiz"])


def _karsilastirmaya_cevir(analiz: KalemAnalizi) -> KarsilastirmaOut:
    dusus = None
    if analiz.dusus is not None:
        d = analiz.dusus
        dusus = DususOut(
            onceki_gun=d.onceki_gun,
            onceki_fiyat=d.onceki_fiyat,
            son_gun=d.son_gun,
            son_fiyat=d.son_fiyat,
            onceki_market=d.onceki_market,
            son_market=d.son_market,
            fark=d.fark,
            yuzde=d.yuzde,
            dustu_mu=d.dustu_mu,
            market_degisti_mi=d.market_degisti_mi,
        )

    return KarsilastirmaOut(
        kalem_id=analiz.kalem_id,
        etiket=analiz.etiket,
        son_gun=analiz.son_gun,
        marketler=analiz.market_fiyatlari,  # type: ignore[arg-type]
        market_sayisi=analiz.market_sayisi,
        en_ucuz_denebilir_mi=analiz.en_ucuz_denebilir_mi,
        beraberlik_var_mi=analiz.beraberlik_var_mi,
        en_pahali_fark=analiz.en_pahali_fark,
        dusus=dusus,
    )


@router.get("/comparisons", response_model=list[KarsilastirmaOut])
def karsilastirmalar(
    db: Session = Depends(get_db),
    yalniz_aktif: bool = Query(True, description="Pasif takip kalemlerini gizle"),
) -> list[KarsilastirmaOut]:
    """Her takip kalemi için anlık en ucuz + son gözlemdeki değişim.

    Hiç fiyat gözlemi olmayan kalemler listede yer almaz.
    """
    analizler = tum_kalemleri_analiz_et(db, yalniz_aktif=yalniz_aktif)
    return [_karsilastirmaya_cevir(a) for a in analizler]


@router.get("/watchlist/{kalem_id}/comparison", response_model=KarsilastirmaOut)
def kalem_karsilastirmasi(
    kalem_id: int, db: Session = Depends(get_db)
) -> KarsilastirmaOut:
    kalem = db.get(WatchlistItem, kalem_id)
    if kalem is None:
        raise HTTPException(status_code=404, detail="Takip kalemi bulunamadı")

    analiz = kalem_analiz_et(db, kalem)
    if analiz is None:
        raise HTTPException(
            status_code=404,
            detail="Bu kalem için henüz fiyat gözlemi yok — önce toplama çalışmalı",
        )
    return _karsilastirmaya_cevir(analiz)


@router.get("/watchlist/{kalem_id}/price-history", response_model=FiyatGecmisiOut)
def fiyat_gecmisi(kalem_id: int, db: Session = Depends(get_db)) -> FiyatGecmisiOut:
    kalem = db.get(WatchlistItem, kalem_id)
    if kalem is None:
        raise HTTPException(status_code=404, detail="Takip kalemi bulunamadı")

    gunluk = kalem_fiyat_gecmisi(db, kalem_id)
    noktalar = [
        FiyatGecmisiNoktasi(gun=gun, slug=m.slug, market=m.ad, fiyat=m.fiyat)
        for gun in sorted(gunluk)
        for m in sorted(gunluk[gun], key=lambda x: (x.fiyat, x.slug))
    ]

    return FiyatGecmisiOut(
        kalem_id=kalem_id,
        etiket=kalem.label,
        gozlem_gunu_sayisi=len(gunluk),
        noktalar=noktalar,
    )


@router.get("/messages/whatsapp-preview", response_model=MesajYanit)
def whatsapp_onizleme(
    db: Session = Depends(get_db),
    kalem_siniri: int | None = Query(
        None, ge=1, le=200,
        description="Mesaj başına ürün. Verilmezse MESSAGE_ITEM_LIMIT geçerli.",
    ),
) -> MesajYanit:
    """Panoya kopyalanmaya hazır mesaj(lar). Otomatik gönderim YOK."""
    analizler = tum_kalemleri_analiz_et(db)
    mesajlar = whatsapp_mesajlari(analizler, kalem_siniri=kalem_siniri)

    if not mesajlar:
        aciklama = (
            "Paylaşılacak bir şey bulunamadı. "
            + (
                "Henüz hiç fiyat gözlemi yok — önce toplama çalışmalı."
                if not analizler
                else "Eşiği aşan düşüş yok ve marketler arası fark oluşmamış."
            )
        )
        return MesajYanit(mesajlar=[], aciklama=aciklama)

    kalem_toplami = sum(m.kalem_sayisi for m in mesajlar)
    return MesajYanit(
        mesajlar=[MesajOut(**vars(m)) for m in mesajlar],
        aciklama=f"{kalem_toplami} kalem, {len(mesajlar)} mesaj.",
    )
