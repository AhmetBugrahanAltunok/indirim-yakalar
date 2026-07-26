"""marketfiyati.org.tr collector'ı.

Takip listesindeki HER `source_product_id` için `POST /api/v2/searchByIdentity`
çağırır ve yanıtı `raw_records`'a değiştirmeden yazar.

Neden `/search` değil: aynı kelime sorgusu günden güne farklı sonuç kümesi
döndürüyor (26.07.2026 gözlemi — 7 üründen 5'i bir gecede listeden düştü, ama
ID'ler canlıydı). Kelimeyle toplasaydık o ürünlerin geçmişi kopardı.

WAF disiplini istemcide (`market_fiyati_client.py`): yalnız POST, sabit uçlar,
istekler arası bekleme. 418 görülürse toplama DERHAL durur — kalan ürünler
denenmez, IP banı riski alınmaz.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector, ToplamaSonucu
from app.collectors.market_fiyati_client import (
    MarketFiyatiClient,
    MarketFiyatiError,
    WafBlockedError,
)
from app.config import Settings, get_settings
from app.models import RawRecord, WatchlistItem, WatchlistSourceId
from app.services.depot_resolver import aktif_depo_idleri

KAYNAK = "market_fiyati"


class MarketFiyatiCollector(BaseCollector):
    kaynak = KAYNAK

    def __init__(
        self,
        api: MarketFiyatiClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._api = api
        self._istemci_bizim = api is None

    def _istemci(self) -> MarketFiyatiClient:
        if self._api is None:
            self._api = MarketFiyatiClient(
                base_url=self._settings.marketfiyati_base_url,
                delay_sec=self._settings.collector_request_delay_sec,
            )
        return self._api

    def topla(self, db: Session) -> ToplamaSonucu:
        sonuc = ToplamaSonucu(kaynak=self.kaynak)

        depolar = aktif_depo_idleri(db)
        if not depolar:
            sonuc.durduruldu = True
            sonuc.durma_nedeni = (
                "Aktif depo yok. Önce POST /depots/refresh — depo listesi olmadan "
                "fiyatlar yanlış şehirden gelir ve bu sessizce olur."
            )
            return sonuc

        hedefler = self._hedefler(db)
        sonuc.istenen = len(hedefler)
        if not hedefler:
            sonuc.durduruldu = True
            sonuc.durma_nedeni = "Takip listesi boş. Önce seed.py veya POST /watchlist."
            return sonuc

        api = self._istemci()
        try:
            for spid in hedefler:
                try:
                    yanit_metni = self._cek(api, spid, depolar)
                except WafBlockedError as hata:
                    # Anayasa md. 12: 418 görülürse derhal durulur.
                    sonuc.durduruldu = True
                    sonuc.durma_nedeni = str(hata)
                    db.commit()
                    return sonuc
                except MarketFiyatiError as hata:
                    sonuc.hatali += 1
                    sonuc.hatalar.append(f"{spid}: {hata}")
                    continue

                icerik_var = self._kaydet(db, spid, yanit_metni)
                if icerik_var:
                    sonuc.basarili += 1
                else:
                    sonuc.bos_donen += 1
            db.commit()
        finally:
            if self._istemci_bizim and self._api is not None:
                self._api.close()
                self._api = None

        return sonuc

    # --- iç işleyiş ------------------------------------------------------

    @staticmethod
    def _hedefler(db: Session) -> list[str]:
        """Aktif takip kalemlerine bağlı tüm platform ID'leri."""
        return list(
            db.scalars(
                select(WatchlistSourceId.source_product_id)
                .join(WatchlistItem, WatchlistItem.id == WatchlistSourceId.watchlist_item_id)
                .where(WatchlistItem.active.is_(True))
                .order_by(WatchlistSourceId.source_product_id)
            )
        )

    def _cek(self, api: MarketFiyatiClient, spid: str, depolar: list[str]) -> str:
        """Tek ürünü çeker ve yanıtı HAM METİN olarak döndürür.

        Ham metin saklanır çünkü `parse_float=Decimal` ile ayrıştırılmış yapı
        JSON'a geri serileştirilemez (Decimal serileştirilemez) ve float'a
        çevirmek anayasa md. 1'i kırar.
        """
        veri = api.search_by_identity(
            identity=spid,
            depots=depolar,
            latitude=self._settings.location_lat,
            longitude=self._settings.location_lon,
            distance_km=self._settings.location_distance_km,
        )
        # Decimal'leri metne çevirerek sadakati koru (float'a düşürme).
        return json.dumps(veri, ensure_ascii=False, default=str)

    @staticmethod
    def _kaydet(db: Session, spid: str, yanit_metni: str) -> bool:
        """Ham yanıtı `raw_records`'a yazar. İçerik boşsa False döner."""
        try:
            yapisal = json.loads(yanit_metni)
        except json.JSONDecodeError:
            yapisal = None

        icerik = (yapisal or {}).get("content") or []

        db.add(RawRecord(
            source=KAYNAK,
            source_product_id=spid,
            raw_json=yanit_metni,
            # JSONB yalnız sorgulanabilirlik için; PARA BURADAN OKUNMAZ,
            # yetkili kaynak `raw_json`'dır.
            raw_data=yapisal,
            processed=False,
        ))
        return bool(icerik)
