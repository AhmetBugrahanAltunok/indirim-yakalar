"""marketfiyati.org.tr iç API'si için ince adaptör.

Bu dosya projedeki TEK yerdir ki platforma HTTP isteği atar. Sebebi: API belgesiz
ve WAF'ı agresif; kuralları tek yerde toplamak, her çağrı noktasında tekrar
hatırlamaktan güvenli.

Uyulan kurallar (Obsidian → İndirimYakalar anayasa md. 12):
  * Yalnız POST. GET denemesi 418 blok yiyor.
  * Yalnız aşağıda sabit olarak tanımlı uç noktalar — path TAHMİN EDİLMEZ.
  * Yalnız bilinen gövde alanları — tanınmayan alan da 418 blok yiyor.
  * İstekler arasında zorunlu bekleme (`COLLECTOR_REQUEST_DELAY_SEC`).
  * 418 görülürse `WafBlockedError` fırlatılır ve çağıran DERHAL durur (IP banı riski).
  * Yanıt `parse_float=Decimal` ile ayrıştırılır — para asla float'a düşmez.

Konum `depots` (depo ID listesi) ile uygulanır; yalnız lat/lon göndermek konumu
AYARLAMAZ, sunucu varsayılan (İstanbul) depolarını döner ve bu sessizce olur.
"""

from __future__ import annotations

import json
import time
from decimal import Decimal
from types import TracebackType
from typing import Any

import httpx

# Doğrulanmış uç noktalar (Obsidian → Veri-Kaynaklari). Buraya yeni bir yol
# eklemeden önce tarayıcıdan gerçek istek yakalanır; uydurulmaz.
_UC_NEAREST = "/api/v2/nearest"
_UC_SEARCH = "/api/v2/search"
_UC_SEARCH_BY_IDENTITY = "/api/v2/searchByIdentity"

# Sunucu ~25 kayıttan fazlasını dönmüyor; daha büyük istemek işe yaramıyor.
MAKS_SAYFA_BOYUTU = 24


class MarketFiyatiError(RuntimeError):
    """Platform API'siyle ilgili genel hata."""


class WafBlockedError(MarketFiyatiError):
    """HTTP 418 — WAF bloğu. Görüldüğü anda tüm toplama durdurulur."""


class MarketFiyatiClient:
    """Platform API'sine ince, kurallı erişim.

    Kullanım:
        with MarketFiyatiClient(base_url, delay_sec=2.0) as api:
            depolar = api.nearest(lat, lon, 10)
    """

    def __init__(
        self,
        base_url: str,
        delay_sec: float = 2.0,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._delay_sec = delay_sec
        self._son_istek: float | None = None
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": "https://marketfiyati.org.tr",
                "Referer": "https://marketfiyati.org.tr/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            },
        )

    # --- yaşam döngüsü ---------------------------------------------------

    def __enter__(self) -> MarketFiyatiClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # --- iç işleyiş ------------------------------------------------------

    def _bekle(self) -> None:
        """Kaynağa saygılı hız: iki istek arasında en az `delay_sec` geçer."""
        if self._son_istek is None:
            return
        gecen = time.monotonic() - self._son_istek
        kalan = self._delay_sec - gecen
        if kalan > 0:
            time.sleep(kalan)

    def _post(self, uc_nokta: str, govde: dict[str, Any]) -> Any:
        self._bekle()
        try:
            yanit = self._client.post(f"{self._base_url}{uc_nokta}", json=govde)
        except httpx.HTTPError as hata:
            raise MarketFiyatiError(f"{uc_nokta} isteği başarısız: {hata}") from hata
        finally:
            self._son_istek = time.monotonic()

        if yanit.status_code == 418:
            raise WafBlockedError(
                f"HTTP 418 — WAF bloğu ({uc_nokta}). Toplama durduruldu; "
                "istek deseni gözden geçirilmeden tekrar denenmez."
            )
        if yanit.status_code >= 400:
            raise MarketFiyatiError(
                f"{uc_nokta} → HTTP {yanit.status_code}: {yanit.text[:200]}"
            )

        # Para float'a düşmesin (anayasa md. 1).
        return json.loads(yanit.text, parse_float=Decimal)

    @staticmethod
    def _konum_govdesi(
        latitude: float, longitude: float, distance_km: int
    ) -> dict[str, Any]:
        return {
            "latitude": latitude,
            "longitude": longitude,
            "distance": distance_km,
        }

    # --- uç noktalar -----------------------------------------------------

    def nearest(
        self, latitude: float, longitude: float, distance_km: int
    ) -> list[dict[str, Any]]:
        """Koordinat + mesafe → yakındaki depolar.

        Yanıt bir LİSTE döner (sarmalayıcı sözlük yok). Her kayıt:
        `id`, `sellerName`, `marketName`, `location{lat,lon}`, `distance` (metre).
        """
        sonuc = self._post(
            _UC_NEAREST, self._konum_govdesi(latitude, longitude, distance_km)
        )
        if not isinstance(sonuc, list):
            raise MarketFiyatiError(
                f"/nearest liste bekleniyordu, {type(sonuc).__name__} geldi — "
                "API sözleşmesi değişmiş olabilir."
            )
        return sonuc

    def search(
        self,
        keywords: str,
        depots: list[str],
        latitude: float,
        longitude: float,
        distance_km: int,
        page: int = 0,
        size: int = MAKS_SAYFA_BOYUTU,
    ) -> dict[str, Any]:
        """Kelime araması. `depots` ZORUNLU — yoksa konum sessizce yok sayılır.

        ⚠️ Sonuç kümesi günden güne değişir (26.07.2026 gözlemi): aynı sorgu
        ertesi gün ürünlerin bir kısmını döndürmeyebilir. Bu bir ENVANTER aracı
        değildir; takip `search_by_identity` ile ID üzerinden yapılır.
        """
        if not depots:
            raise ValueError(
                "depots boş — konum uygulanmaz ve fiyatlar yanlış şehirden gelir."
            )
        govde = self._konum_govdesi(latitude, longitude, distance_km)
        govde.update({
            "keywords": keywords,
            "pages": page,
            "size": min(size, MAKS_SAYFA_BOYUTU),
            "depots": depots,
        })
        return self._post(_UC_SEARCH, govde)

    def search_by_identity(
        self,
        identity: str,
        depots: list[str],
        latitude: float,
        longitude: float,
        distance_km: int,
        identity_type: str = "id",
    ) -> dict[str, Any]:
        """Tek ürünü platform ID'siyle çeker — günlük toplamanın yolu budur.

        `identity_type` zorunlu; `"id"` çalıştığı doğrulandı. Ürün ID'lerinin
        günler arası kalıcı olduğu 26.07.2026'da teyit edildi (7/7).
        """
        if not depots:
            raise ValueError(
                "depots boş — konum uygulanmaz ve fiyatlar yanlış şehirden gelir."
            )
        govde = self._konum_govdesi(latitude, longitude, distance_km)
        govde.update({
            "identity": identity,
            "identityType": identity_type,
            "depots": depots,
        })
        return self._post(_UC_SEARCH_BY_IDENTITY, govde)
